"""Real stdio plumbing with synthetic Python children only; no Codex/auth/inference."""
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mira.adapters.generation.codex_app_server import CodexGenerationError, CodexLimits, CodexRuntime
from mira.adapters.generation.codex_support.process import StdioProcessTransport, _argv, open_stdio

PYTHON = Path(sys.executable).resolve()


async def spawn(tmp_path, source, limits=None):
    return await StdioProcessTransport._spawn(PYTHON, ('-c', source), tmp_path, {},
                                              limits or CodexLimits())


@pytest.mark.asyncio
async def test_adjacent_lines_are_queued_without_another_os_readiness_event(tmp_path):
    source = 'import sys,time; sys.stdout.write("{\\\"id\\\":1}\\n{\\\"id\\\":2}\\n"); sys.stdout.flush(); time.sleep(5)'
    transport = await spawn(tmp_path, source)
    try:
        async with asyncio.timeout(1):
            assert json.loads(await transport.receive()) == {'id': 1}
            assert json.loads(await transport.receive()) == {'id': 2}
    finally:
        await transport.close()
    assert transport._process.returncode is not None
    assert transport._reader.done() and transport._stderr.done()


@pytest.mark.asyncio
async def test_process_send_and_stderr_drain_do_not_expose_private_output(tmp_path):
    source = ('import sys; sys.stderr.write("SECRET-STDERR"*100000); sys.stderr.flush(); '
              'line=sys.stdin.readline(); sys.stdout.write(line); sys.stdout.flush()')
    transport = await spawn(tmp_path, source)
    try:
        async with asyncio.timeout(2):
            await transport.send({'id': 1, 'method': 'synthetic'})
            assert json.loads(await transport.receive()) == {'id': 1, 'method': 'synthetic'}
            with pytest.raises(CodexGenerationError) as caught:
                await transport.receive()
            assert 'SECRET' not in str(caught.value)
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_overlong_and_unterminated_line_fail_closed(tmp_path):
    transport = await spawn(tmp_path, 'print("x"*3000)',
                            replace(CodexLimits(), max_line_bytes=1024))
    try:
        with pytest.raises(CodexGenerationError):
            async with asyncio.timeout(1):
                await transport.receive()
    finally:
        await transport.close()
    transport = await spawn(tmp_path, 'import sys; sys.stdout.write("truncated")')
    try:
        with pytest.raises(CodexGenerationError):
            async with asyncio.timeout(1):
                await transport.receive()
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_queue_flood_fails_bounded_and_child_is_reaped(tmp_path):
    limits = replace(CodexLimits(), queue_capacity=1, shutdown_seconds=0.1)
    transport = await spawn(tmp_path, 'import sys; sys.stdout.write("{}\\n"*1000000); sys.stdout.flush()', limits)
    try:
        await asyncio.wait_for(transport._process.stdout.read(0), 1)
        # Reader completion is deterministic once its bounded queue overflows.
        await asyncio.wait_for(transport._reader, 2)
        with pytest.raises(CodexGenerationError):
            await transport.receive()
    finally:
        await transport.close()
    assert transport._process.returncode is not None


@pytest.mark.asyncio
async def test_sigterm_ignoring_child_is_killed_and_reaped(tmp_path):
    limits = replace(CodexLimits(), shutdown_seconds=0.05)
    source = ('import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
              'print("ready",flush=True); time.sleep(30)')
    transport = await spawn(tmp_path, source, limits)
    assert await asyncio.wait_for(transport.receive(), 1) == b'ready\n'
    await asyncio.wait_for(transport.close(), 1)
    assert transport._process.returncode == -9


@pytest.mark.asyncio
async def test_cancellation_during_spawn_reaps_created_child(tmp_path, monkeypatch):
    created, release = asyncio.Event(), asyncio.Event()
    processes = []
    real_create = asyncio.create_subprocess_exec

    async def delayed_create(*args, **kwargs):
        process = await real_create(*args, **kwargs)
        processes.append(process)
        created.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', delayed_create)
    task = asyncio.create_task(spawn(tmp_path, 'import time; time.sleep(30)'))
    try:
        await asyncio.wait_for(created.wait(), 1)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].returncode is not None
    finally:
        for process in processes:
            if process.returncode is None:
                process.kill()
                await process.wait()


def test_fixed_process_profile_has_all_disabled_categories_and_no_shell_command():
    args = _argv()
    assert args[:6] == ('-c', 'features.respect_system_proxy=true', 'app-server', '--listen',
                        'stdio://', '--disable')
    assert args[-2:] == ('-c', 'web_search="disabled"')
    for flag in ('apps', 'plugins', 'browser_use', 'computer_use', 'multi_agent', 'shell_tool',
                 'image_generation', 'tool_suggest', 'sleep_tool', 'token_budget'):
        assert args[args.index(flag) - 1] == '--disable'


@pytest.mark.asyncio
async def test_real_factory_requires_config_pin_before_spawn_or_auth_read(tmp_path, monkeypatch):
    called = False

    async def no_spawn(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError('must not spawn')

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', no_spawn)
    runtime = CodexRuntime(tmp_path / 'codex', tmp_path / 'home', tmp_path / 'run')
    with pytest.raises(CodexGenerationError, match='codex_config_pin_missing'):
        await open_stdio(runtime, CodexLimits())
    assert not called


def test_runtime_never_accepts_credential_override_or_relative_paths(tmp_path):
    with pytest.raises(ValueError, match='codex_environment_invalid'):
        CodexRuntime(tmp_path / 'codex', tmp_path / 'home', tmp_path / 'run',
                     environment={'OPENAI_API_KEY': 'synthetic-do-not-use'})
    with pytest.raises(ValueError):
        CodexRuntime(Path('codex'), tmp_path / 'home', tmp_path / 'run')


@pytest.mark.asyncio
async def test_cancellation_during_close_still_kills_and_reaps_child(tmp_path, monkeypatch):
    import os
    import signal
    limits = replace(CodexLimits(), shutdown_seconds=0.1)
    source = ('import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
              'print("ready",flush=True); time.sleep(30)')
    transport = await spawn(tmp_path, source, limits)
    assert await asyncio.wait_for(transport.receive(), 1) == b'ready\n'
    terminated = asyncio.Event()
    real_killpg = os.killpg

    def observe_killpg(pid, sig):
        real_killpg(pid, sig)
        if sig == signal.SIGTERM:
            terminated.set()

    monkeypatch.setattr(os, 'killpg', observe_killpg)
    task = asyncio.create_task(transport.close())
    try:
        await asyncio.wait_for(terminated.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert transport._process.returncode is not None
    finally:
        if transport._process.returncode is None:
            transport._process.kill()
            await transport._process.wait()


@pytest.mark.asyncio
async def test_real_factory_requires_policy_environment_confirmation(tmp_path, monkeypatch):
    called = False

    async def no_spawn(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError('must not spawn')

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', no_spawn)
    runtime = CodexRuntime(tmp_path / 'codex', tmp_path / 'home', tmp_path / 'run',
                           expected_config_sha256='0' * 64)
    with pytest.raises(CodexGenerationError, match='codex_policy_environment_unverified'):
        await open_stdio(runtime, CodexLimits())
    assert not called


def test_supported_managed_policy_environment_is_preserved_verbatim(tmp_path):
    policy = {'CODEX_PERMISSION_PROFILE': '{"synthetic":"restricted"}',
              'CODEX_NETWORK_PROXY_ACTIVE': '1', 'CODEX_SANDBOX_NETWORK_DISABLED': '1'}
    runtime = CodexRuntime(tmp_path / 'codex', tmp_path / 'home', tmp_path / 'run', policy)
    assert dict(runtime.environment) == policy


@pytest.mark.asyncio
@pytest.mark.parametrize('shutdown', ['terminate', 'already_exited', 'cancel'])
async def test_queue_failure_close_awaits_paused_pipe_shutdown(tmp_path, monkeypatch, shutdown):
    """A real flood reproduces the pipe state that can outlive process.wait()."""
    import os
    import signal

    limits = replace(CodexLimits(), queue_capacity=1, shutdown_seconds=0.1)
    ignore_term = ('signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                   if shutdown == 'cancel' else '')
    source = ('import signal,sys; ' + ignore_term
              + 'sys.stdout.write("{}\\n"*1000000); sys.stdout.flush()')
    transport = await spawn(tmp_path, source, limits)
    process = transport._process
    paused = asyncio.Event()
    stdout = process.stdout
    real_pause = stdout._transport.pause_reading

    def observe_pause():
        real_pause()
        paused.set()

    monkeypatch.setattr(stdout._transport, 'pause_reading', observe_pause)
    if stdout._paused:
        paused.set()
    try:
        await asyncio.wait_for(transport._reader, 2)
        assert transport._failure == 'codex_queue_limit'
        # Event barrier establishes real OS-pipe backpressure without timing sleeps.
        await asyncio.wait_for(paused.wait(), 2)
        assert stdout._paused
        pipes = [process._transport.get_pipe_transport(fd).get_extra_info('pipe')
                 for fd in (0, 1, 2)]
        if shutdown == 'already_exited':
            exited = asyncio.Event()
            original_exited = process._protocol.process_exited

            def observe_exit():
                original_exited()
                exited.set()

            monkeypatch.setattr(process._protocol, 'process_exited', observe_exit)
            os.killpg(process.pid, signal.SIGTERM)
            await asyncio.wait_for(exited.wait(), 1)
            assert process.returncode == -signal.SIGTERM
        if shutdown == 'cancel':
            terminated = asyncio.Event()
            original_killpg = os.killpg

            def observe_terminate(pid, sig):
                original_killpg(pid, sig)
                if pid == process.pid and sig == signal.SIGTERM:
                    terminated.set()

            monkeypatch.setattr(os, 'killpg', observe_terminate)
            closing = asyncio.create_task(transport.close())
            await asyncio.wait_for(terminated.wait(), 1)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
        else:
            await asyncio.wait_for(transport.close(), 1)
        assert process.returncode == (-signal.SIGKILL if shutdown == 'cancel'
                                      else -signal.SIGTERM)
        assert all(pipe.closed for pipe in pipes), {
            'shutdown': shutdown, 'returncode': process.returncode,
            'stdout_paused': stdout._paused, 'stdout_buffered': len(stdout._buffer),
            'pipe_closed': [pipe.closed for pipe in pipes],
        }
        assert process._transport.is_closing()
        assert transport._reader.done() and transport._stderr.done()
    finally:
        # Keep a failing RED from leaking its synthetic child/pipes into another test.
        if process.returncode is None:
            process.kill()
        for task in (transport._reader, transport._stderr):
            task.cancel()
        await asyncio.gather(transport._reader, transport._stderr, return_exceptions=True)
        await asyncio.wait_for(process.communicate(), 2)
        await process.wait()
