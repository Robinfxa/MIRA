"""One bounded asyncio stdout reader and queue; no select/TextIO buffering race."""
from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import stat
from contextlib import suppress
from pathlib import Path

from .payload import canonical
from .types import DISABLED_FEATURES, CodexGenerationError, CodexLimits, CodexRuntime


def _validate_runtime(runtime: CodexRuntime) -> None:
    # Read executable bytes only. Never enumerate/read CODEX_HOME contents or auth files.
    if runtime.expected_config_sha256 is None:
        raise CodexGenerationError('codex_config_pin_missing')
    if not runtime.policy_environment_confirmed:
        raise CodexGenerationError('codex_policy_environment_unverified')
    for path in (runtime.executable, runtime.codex_home, runtime.runtime_cwd):
        if path.resolve() != path:
            raise CodexGenerationError('codex_runtime_symlink')
    if not runtime.executable.is_file() or not runtime.codex_home.is_dir():
        raise CodexGenerationError('codex_runtime_missing')
    if not runtime.runtime_cwd.is_dir() or next(runtime.runtime_cwd.iterdir(), None) is not None:
        raise CodexGenerationError('codex_runtime_not_empty')
    for directory in (runtime.codex_home, runtime.runtime_cwd):
        metadata = directory.stat()
        permitted_mode = not (metadata.st_mode & 0o077)
        if directory == runtime.codex_home and runtime.development_context is not None:
            permitted_mode = (stat.S_IMODE(metadata.st_mode)
                              == runtime.development_context.observed_home_mode)
            if runtime.environment.get('CODEX_HOME') != str(directory):
                raise CodexGenerationError('codex_development_home_drift')
        if not permitted_mode or metadata.st_uid != os.getuid():
            raise CodexGenerationError('codex_runtime_permissions')
    digest = hashlib.sha256()
    with runtime.executable.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != runtime.executable_sha256:
        raise CodexGenerationError('codex_executable_drift')


def _argv(runtime: CodexRuntime | None = None) -> tuple[str, ...]:
    development = runtime is not None and runtime.development_context is not None
    args = [] if development else ['-c', 'features.respect_system_proxy=true']
    args += ['app-server', '--listen', 'stdio://']
    for feature in DISABLED_FEATURES:
        args += ['--disable', feature]
    if development:
        args += ['-c', 'orchestrator.mcp.enabled=false', '-c', 'cloud.skills.enabled=false']
    return (*args, '-c', 'web_search="disabled"')


class StdioProcessTransport:
    """Private byte transport. Backend owns the only permitted RPC vocabulary."""

    def __init__(self, process: asyncio.subprocess.Process, limits: CodexLimits):
        self._process = process
        self._limits = limits
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(limits.queue_capacity)
        self._failure: str | None = None
        self._closed = False
        self._reader = asyncio.create_task(self._read_stdout())
        self._stderr = asyncio.create_task(self._drain_stderr())

    @classmethod
    async def _spawn(cls, executable: Path, args: tuple[str, ...], cwd: Path,
                     environment: dict[str, str], limits: CodexLimits):
        # Only the fixed factory below calls this in production; tests use a synthetic script.
        try:
            creation = asyncio.create_task(asyncio.create_subprocess_exec(
                str(executable), *args, cwd=cwd, env=environment,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=limits.max_line_bytes + 1,
                start_new_session=True,
            ))
            try:
                process = await asyncio.shield(creation)
            except asyncio.CancelledError:
                # Creation may have reached the OS before cancellation reached this task.
                # Retain ownership until the returned process can be terminated and reaped.
                try:
                    process = await asyncio.wait_for(creation, limits.shutdown_seconds)
                    await cls(process, limits).close()
                except (Exception, asyncio.CancelledError):
                    creation.cancel()
                    with suppress(Exception, asyncio.CancelledError):
                        await creation
                raise
        except (OSError, ValueError):
            raise CodexGenerationError('codex_process_start_failed') from None
        return cls(process, limits)

    async def _read_stdout(self):
        assert self._process.stdout is not None
        total = 0
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    await self._queue.put(None)
                    return
                total += len(line)
                if len(line) > self._limits.max_line_bytes or not line.endswith(b'\n'):
                    raise CodexGenerationError('codex_line_limit')
                if total > self._limits.max_wire_bytes:
                    raise CodexGenerationError('codex_wire_limit')
                self._queue.put_nowait(line)
        except asyncio.CancelledError:
            raise
        except asyncio.QueueFull:
            self._failure = 'codex_queue_limit'
        except (ValueError, CodexGenerationError, OSError):
            self._failure = 'codex_transport_invalid'
        finally:
            if self._failure:
                # Wake a pending receive; never preserve arbitrary exception or stderr text.
                with suppress(asyncio.QueueFull):
                    self._queue.put_nowait(None)

    async def _drain_stderr(self):
        assert self._process.stderr is not None
        try:
            while await self._process.stderr.read(8192):
                pass
        except OSError:
            pass

    async def send(self, message: dict) -> None:
        if self._closed or self._process.stdin is None:
            raise CodexGenerationError('codex_transport_closed')
        raw = canonical(message) + b'\n'
        if len(raw) > self._limits.max_line_bytes:
            raise CodexGenerationError('codex_request_limit')
        try:
            self._process.stdin.write(raw)
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionError, OSError):
            raise CodexGenerationError('codex_transport_closed') from None

    async def receive(self) -> bytes:
        if self._failure:
            raise CodexGenerationError(self._failure)
        value = await self._queue.get()
        if self._failure:
            raise CodexGenerationError(self._failure)
        if value is None:
            raise CodexGenerationError('codex_transport_eof')
        return value

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        try:
            if process.stdin:
                process.stdin.close()
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), self._limits.shutdown_seconds)
                except TimeoutError:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    await asyncio.wait_for(process.wait(), self._limits.shutdown_seconds)
            else:
                await process.wait()
        except asyncio.CancelledError:
            # Cancellation of cleanup cannot convert an ignoring child into an orphan.
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                with suppress(Exception, asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(process.wait()),
                                           self._limits.shutdown_seconds)
            raise
        except (OSError, TimeoutError):
            raise CodexGenerationError('codex_process_cleanup_failed') from None
        finally:
            for task in (self._reader, self._stderr):
                task.cancel()
            await asyncio.gather(self._reader, self._stderr, return_exceptions=True)
            while not self._queue.empty():
                self._queue.get_nowait()


def _process_environment(runtime: CodexRuntime) -> dict[str, str]:
    if runtime.development_context is None:
        environment = dict(runtime.environment)
        environment['CODEX_HOME'] = str(runtime.codex_home)
        return environment
    # Preserve the already-approved managed context, never discover/copy auth files.
    # Caller input cannot substitute a different environment or home.
    if runtime.environment.get('CODEX_HOME') != str(runtime.codex_home):
        raise CodexGenerationError('codex_development_home_drift')
    forbidden = ('CODEX_API_KEY', 'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'CODEX_ACCESS_TOKEN',
                 'CODEX_REFRESH_TOKEN_URL_OVERRIDE', 'TYPESAFE_API_KEY')
    if any(key in runtime.environment for key in forbidden):
        raise CodexGenerationError('codex_development_environment_drift')
    if not runtime.environment.get('HTTPS_PROXY') or not runtime.environment.get('SSL_CERT_FILE'):
        raise CodexGenerationError('codex_policy_environment_unverified')
    return dict(runtime.environment)


async def open_stdio(runtime: CodexRuntime, limits: CodexLimits) -> StdioProcessTransport:
    try:
        await asyncio.to_thread(_validate_runtime, runtime)
        environment = _process_environment(runtime)
        return await StdioProcessTransport._spawn(runtime.executable, _argv(runtime), runtime.runtime_cwd,
                                                   environment, limits)
    except CodexGenerationError:
        raise
    except OSError:
        raise CodexGenerationError('codex_runtime_invalid') from None
