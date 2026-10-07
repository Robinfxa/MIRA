"""Terminal native startup failures are classified without retaining stderr."""
import asyncio
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mira.adapters.generation.codex_app_server import CodexGenerationError, CodexLimits
from mira.adapters.generation.codex_support.process import StdioProcessTransport


STARTUP_REASON = 'codex_startup_readonly_filesystem'
TERMINAL = 'Error: Read-only file system (os error 30)'
PYTHON = Path(sys.executable).resolve()


async def spawn(tmp_path, source, limits=None):
    return await StdioProcessTransport._spawn(PYTHON, ('-c', source), tmp_path, {},
                                              limits or CodexLimits())


def stderr_child(stderr: str, *, code: int = 1, stdout: str = '') -> str:
    return (
        'import sys; '
        f'sys.stderr.write({stderr!r}); sys.stderr.flush(); '
        f'sys.stdout.write({stdout!r}); sys.stdout.flush(); '
        f'sys.exit({code})'
    )


async def raised_code(transport):
    with pytest.raises(CodexGenerationError) as caught:
        async with asyncio.timeout(2):
            await transport.receive()
    return caught.value.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', ['\n', '\r\n', '\n\n'])
async def test_exact_terminal_readonly_line_after_confirmed_nonzero_exit_is_classified(
        tmp_path, ending):
    transport = await spawn(tmp_path, stderr_child(TERMINAL + ending))
    try:
        assert await raised_code(transport) == STARTUP_REASON
    finally:
        await transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('stderr', [
    'WARNING: PATH aliases are unavailable\n',
    'ERROR: ignoring configuration\n',
    TERMINAL + '\nUnrelated later line\n',
    'prefix ' + TERMINAL + '\n',
    TERMINAL + ' suffix\n',
    TERMINAL,
])
async def test_nonterminal_or_incomplete_stderr_does_not_classify(tmp_path, stderr):
    transport = await spawn(tmp_path, stderr_child(stderr))
    try:
        assert await raised_code(transport) == 'codex_transport_eof'
    finally:
        await transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(('stderr', 'code', 'stdout'), [
    (TERMINAL + '\n', 0, ''),
    ('ordinary failure\n', 1, ''),
    (TERMINAL + '\n', 1, 'one stdout line\n'),
])
async def test_exit_status_and_stdout_are_required_for_classification(tmp_path, stderr, code, stdout):
    transport = await spawn(tmp_path, stderr_child(stderr, code=code, stdout=stdout))
    try:
        if stdout:
            assert await transport.receive() == stdout.encode()
        assert await raised_code(transport) == 'codex_transport_eof'
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_large_secret_stderr_is_streamed_without_leaking_into_fixed_reason(tmp_path):
    source = (
        'import sys\n'
        'for _ in range(20000):\n'
        '    sys.stderr.write("SENTINEL_SECRET_PATH_1234567890")\n'
        'sys.stderr.write("\\n")\n'
        f'sys.stderr.write({(TERMINAL + chr(10))!r})\n'
        'sys.stderr.flush()\n'
        'sys.exit(1)\n'
    )
    transport = await spawn(tmp_path, source)
    try:
        code = await raised_code(transport)
        assert code == STARTUP_REASON
        assert 'SENTINEL_SECRET_PATH_1234567890' not in repr(transport.__dict__)
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_readonly_line_is_not_classified_until_owned_child_exits(tmp_path):
    limits = replace(CodexLimits(), shutdown_seconds=0.05)
    source = (
        'import os,sys,time; '
        f'sys.stderr.write({(TERMINAL + chr(10))!r}); sys.stderr.flush(); '
        'os.close(1); time.sleep(30)'
    )
    transport = await spawn(tmp_path, source, limits)
    try:
        assert await raised_code(transport) == 'codex_transport_eof'
        assert transport._process.returncode is None
    finally:
        await transport.close()
    assert transport._process.returncode is not None


@pytest.mark.asyncio
async def test_cancellation_while_waiting_for_owned_exit_remains_cancellable_and_reaped(tmp_path):
    limits = replace(CodexLimits(), shutdown_seconds=0.1)
    transport = await spawn(tmp_path, 'import os,time; os.close(1); time.sleep(30)', limits)
    await asyncio.wait_for(transport._reader, 1)
    task = asyncio.create_task(transport.receive())
    try:
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await transport.close()
    assert transport._process.returncode is not None


@pytest.mark.asyncio
async def test_signal_termination_is_not_natural_startup_failure(tmp_path):
    source = ('import os,signal,sys; '
              f'sys.stderr.write({(TERMINAL + chr(10))!r}); sys.stderr.flush(); '
              'os.kill(os.getpid(), signal.SIGTERM)')
    transport = await spawn(tmp_path, source)
    try:
        assert await raised_code(transport) == 'codex_transport_eof'
        assert transport._process.returncode < 0
    finally:
        await transport.close()
