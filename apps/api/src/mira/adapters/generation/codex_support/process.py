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
from .types import (
    DISABLED_FEATURES, CodexGenerationError, CodexLimits, CodexRuntime,
    ReadonlyInstallationApproval,
    current_codex_platform_pin,
)


_READONLY_STARTUP_LINE = b'Error: Read-only file system (os error 30)'
_READONLY_STARTUP_REASON = 'codex_startup_readonly_filesystem'


class _TerminalStderrMatcher:
    """Recognize one complete final nonempty line without retaining stderr bytes."""

    __slots__ = ('_position', '_line_nonempty', '_line_valid', '_terminal_cr',
                 '_last_nonempty_matches', '_finished')

    def __init__(self):
        self._position = 0
        self._line_nonempty = False
        self._line_valid = True
        self._terminal_cr = False
        self._last_nonempty_matches = False
        self._finished = False

    def feed(self, chunk: bytes) -> None:
        if self._finished:
            return
        for byte in chunk:
            if byte == 10:
                if self._line_nonempty:
                    self._last_nonempty_matches = (
                        self._line_valid and
                        (self._position == len(_READONLY_STARTUP_LINE) or self._terminal_cr)
                    )
                self._position = 0
                self._line_nonempty = False
                self._line_valid = True
                self._terminal_cr = False
                continue

            self._line_nonempty = True
            if not self._line_valid:
                continue
            if self._terminal_cr:
                self._line_valid = False
            elif self._position < len(_READONLY_STARTUP_LINE):
                if byte == _READONLY_STARTUP_LINE[self._position]:
                    self._position += 1
                else:
                    self._line_valid = False
            elif byte == 13:
                self._terminal_cr = True
            else:
                self._line_valid = False

    def finish(self) -> bool:
        if self._line_nonempty:
            # A final line without LF is not a complete line and cannot classify.
            self._last_nonempty_matches = False
        self._finished = True
        return self._last_nonempty_matches

    def read_failed(self) -> None:
        self._last_nonempty_matches = False
        self._finished = True


def _validate_readonly_installation(runtime: CodexRuntime,
                                    approval: ReadonlyInstallationApproval) -> None:
    """Verify the exact managed binary and every installation path component."""
    uid = os.getuid()
    if (str(runtime.executable) != approval.executable_path
            or approval.verified_uid in (0, uid)):
        raise CodexGenerationError('codex_runtime_permissions')
    try:
        components = (*reversed(runtime.executable.parents), runtime.executable)
        for component in components:
            metadata = component.lstat()
            is_executable = component == runtime.executable
            if (stat.S_ISLNK(metadata.st_mode)
                    or (not stat.S_ISREG(metadata.st_mode) if is_executable
                        else not stat.S_ISDIR(metadata.st_mode))
                    or metadata.st_mode & (0o022 | stat.S_ISUID | stat.S_ISGID)):
                raise CodexGenerationError('codex_runtime_permissions')
            if is_executable:
                if (metadata.st_uid != approval.verified_uid
                        or stat.S_IMODE(metadata.st_mode) != approval.verified_mode):
                    raise CodexGenerationError('codex_runtime_permissions')
            elif metadata.st_uid not in (0, uid, approval.verified_uid):
                raise CodexGenerationError('codex_runtime_permissions')

            # The effective current user must not be able to mutate any part of the
            # installation. The read-only mount check below is independent of this.
            if os.access(component, os.W_OK):
                raise CodexGenerationError('codex_runtime_permissions')

            if metadata.st_uid not in (0, uid):
                # A foreign owner is accepted only for the explicitly approved UID,
                # and only while the kernel reports this component's mount read-only.
                readonly_flag = getattr(os, 'ST_RDONLY', None)
                if (metadata.st_uid != approval.verified_uid or readonly_flag is None
                        or not os.statvfs(component).f_flag & readonly_flag):
                    raise CodexGenerationError('codex_runtime_permissions')
    except CodexGenerationError:
        raise
    except (OSError, ValueError):
        raise CodexGenerationError('codex_runtime_permissions') from None


def _development_home_binding(runtime: CodexRuntime) -> Path:
    """Bind the approved home to CODEX_HOME or Codex's HOME/.codex default."""
    environment = runtime.environment

    def canonical_absolute(value: str) -> Path:
        path = Path(value)
        if not value or not path.is_absolute() or '..' in path.parts or str(path) != value:
            raise CodexGenerationError('codex_development_home_drift')
        try:
            canonical = path.resolve()
        except (OSError, RuntimeError):
            raise CodexGenerationError('codex_development_home_drift') from None
        if canonical != path:
            raise CodexGenerationError('codex_development_home_drift')
        return path

    home_value = environment.get('HOME')
    home = canonical_absolute(home_value) if home_value is not None else None
    if 'CODEX_HOME' in environment:
        bound_home = canonical_absolute(environment['CODEX_HOME'])
    elif home is not None:
        bound_home = canonical_absolute(str(home / '.codex'))
    else:
        raise CodexGenerationError('codex_development_home_drift')

    if bound_home != runtime.codex_home:
        raise CodexGenerationError('codex_development_home_drift')
    return bound_home


def _validate_runtime(runtime: CodexRuntime, *, require_config_pin: bool = True) -> None:
    try:
        current_pin = current_codex_platform_pin()
    except ValueError:
        raise CodexGenerationError('codex_platform_pin_unavailable') from None
    if (runtime.platform_family != current_pin.platform_family
            or runtime.platform_os != current_pin.platform_os
            or runtime.platform_machine != current_pin.machine
            or runtime.executable_sha256 != current_pin.executable_sha256):
        raise CodexGenerationError('codex_platform_pin_drift')
    # Read executable bytes only. Never enumerate/read CODEX_HOME contents or auth files.
    if require_config_pin and runtime.expected_config_sha256 is None:
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
            _development_home_binding(runtime)
        if not permitted_mode or metadata.st_uid != os.getuid():
            raise CodexGenerationError('codex_runtime_permissions')
    readonly_approval = (runtime.development_context.readonly_installation
                         if runtime.development_context is not None else None)
    executable_metadata = runtime.executable.stat()
    if (not stat.S_ISREG(executable_metadata.st_mode)
            or (executable_metadata.st_uid not in (0, os.getuid())
                and readonly_approval is None)
            or executable_metadata.st_mode & (0o022 | stat.S_ISUID | stat.S_ISGID)):
        raise CodexGenerationError('codex_runtime_permissions')
    if readonly_approval is not None:
        _validate_readonly_installation(runtime, readonly_approval)
    for path in (runtime.executable, runtime.codex_home, runtime.runtime_cwd):
        for parent in path.parents:
            metadata = parent.lstat()
            approved_install_parent = (readonly_approval is not None
                                       and path == runtime.executable
                                       and metadata.st_uid == readonly_approval.verified_uid)
            if (not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)
                    or (metadata.st_uid not in (0, os.getuid())
                        and not approved_install_parent)):
                raise CodexGenerationError('codex_runtime_permissions')
            writable_by_others = bool(metadata.st_mode & 0o022)
            safe_system_temp = (metadata.st_uid == 0 and bool(metadata.st_mode & stat.S_ISVTX)
                                and parent in (Path('/tmp'), Path('/var/tmp')))
            if writable_by_others and not safe_system_temp:
                raise CodexGenerationError('codex_runtime_permissions')
    digest = hashlib.sha256()
    with runtime.executable.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != runtime.executable_sha256:
        raise CodexGenerationError('codex_executable_drift')


def _argv(runtime: CodexRuntime | None = None) -> tuple[str, ...]:
    development = runtime is not None and runtime.development_context is not None
    args = ['--no-daemon'] if development else ['-c', 'features.respect_system_proxy=true']
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
        self._stdout_bytes_seen = False
        self._stderr_matcher = _TerminalStderrMatcher()
        self._stderr_read_failed = False
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
                self._stdout_bytes_seen = True
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
            while True:
                chunk = await self._process.stderr.read(8192)
                if not chunk:
                    self._stderr_matcher.finish()
                    return
                self._stderr_matcher.feed(chunk)
        except OSError:
            self._stderr_read_failed = True
            self._stderr_matcher.read_failed()

    async def _eof_reason(self) -> str:
        """Use the fixed startup reason only after bounded natural exit and stderr EOF."""
        if self._closed or self._stdout_bytes_seen:
            return 'codex_transport_eof'

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._limits.shutdown_seconds
        process = self._process
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), max(0, deadline - loop.time()))
            except TimeoutError:
                return 'codex_transport_eof'
        if self._closed or process.returncode is None or process.returncode <= 0:
            return 'codex_transport_eof'

        if not self._stderr.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                return 'codex_transport_eof'
            # Wait on the already-owned task without wrapping it in a shield task.
            completed, _ = await asyncio.wait((self._stderr,), timeout=remaining)
            if self._stderr not in completed:
                return 'codex_transport_eof'
        if (self._closed or self._stderr.cancelled() or self._stderr_read_failed
                or self._stderr.exception() is not None):
            return 'codex_transport_eof'
        if self._stderr_matcher._last_nonempty_matches:
            return _READONLY_STARTUP_REASON
        return 'codex_transport_eof'

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
            raise CodexGenerationError(await self._eof_reason())
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
            # Process.wait() can return an exit code while backpressure leaves a
            # read pipe paused and open. Explicitly close the owned asyncio
            # transport, then await its pipe callbacks before releasing ownership.
            process._transport.close()
            for task in (self._reader, self._stderr):
                task.cancel()
            cleanup = asyncio.create_task(self._finish_pipe_shutdown())
            try:
                try:
                    await asyncio.wait_for(asyncio.shield(cleanup),
                                           self._limits.shutdown_seconds)
                except asyncio.CancelledError:
                    await asyncio.wait_for(asyncio.shield(cleanup),
                                           self._limits.shutdown_seconds)
                    raise
            except (OSError, TimeoutError):
                raise CodexGenerationError('codex_process_cleanup_failed') from None
            finally:
                cleanup.cancel()
                await asyncio.gather(cleanup, return_exceptions=True)
                while not self._queue.empty():
                    self._queue.get_nowait()

    async def _finish_pipe_shutdown(self) -> None:
        await asyncio.gather(self._reader, self._stderr, return_exceptions=True)
        process = self._process
        if process.stdin is not None:
            with suppress(BrokenPipeError, ConnectionResetError):
                await process.stdin.wait_closed()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                # Discard only bounded existing buffers; the OS pipes are closing.
                while await stream.read(8192):
                    pass
        await process.wait()


def _process_environment(runtime: CodexRuntime) -> dict[str, str]:
    if runtime.development_context is None:
        environment = dict(runtime.environment)
        environment['CODEX_HOME'] = str(runtime.codex_home)
        return environment
    # Preserve the already-approved managed context, never discover/copy auth files.
    # Caller input cannot substitute a different environment or home.
    _development_home_binding(runtime)
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


async def open_stdio_preflight(runtime: CodexRuntime, limits: CodexLimits) -> StdioProcessTransport:
    """Start the pinned public app-server for the metadata-only setup handshake.

    This separate entry point may run before a config digest exists. The ordinary
    generation factory above continues to require that digest before it can spawn.
    The preflight transport restricts all outbound RPCs to initialize/config/read.
    """
    if runtime.development_context is not None:
        raise CodexGenerationError('codex_preflight_route_unsupported')
    try:
        await asyncio.to_thread(_validate_runtime, runtime, require_config_pin=False)
        environment = _process_environment(runtime)
        return await StdioProcessTransport._spawn(runtime.executable, _argv(runtime),
                                                   runtime.runtime_cwd, environment, limits)
    except CodexGenerationError:
        raise
    except OSError:
        raise CodexGenerationError('codex_runtime_invalid') from None
