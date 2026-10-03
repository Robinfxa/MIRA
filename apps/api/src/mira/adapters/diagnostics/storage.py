"""Private bounded JSONL files. No arbitrary file discovery or symlink following."""
import os
import re
import stat
import uuid
from pathlib import Path


_FILE_NAME = re.compile(r"(?:events|raw)-[a-zA-Z0-9-]+\.jsonl\Z")


def open_directory(path: Path, *, create: bool = False) -> int:
    """Walk with directory fds and O_NOFOLLOW, closing symlink replacement races."""
    path = path.absolute()
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if part in ("", ".", ".."):
                raise ValueError("unsafe directory")
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        if create:
            os.fchmod(fd, 0o700)
        return fd
    except BaseException:
        os.close(fd)
        raise


def matching_files(fd: int, prefix: str) -> list[tuple[str, os.stat_result]]:
    result = []
    with os.scandir(fd) as entries:
        for index, entry in enumerate(entries):
            if index >= 4096:
                raise ValueError("diagnostic directory has too many entries")
            if (_FILE_NAME.fullmatch(entry.name) and entry.name.startswith(prefix + "-")
                    and entry.is_file(follow_symlinks=False)):
                info = entry.stat(follow_symlinks=False)
                if info.st_nlink == 1:
                    result.append((entry.name, info))
    return sorted(result, key=lambda value: (value[1].st_mtime_ns, value[0]))


class JsonlStore:
    def __init__(self, root: Path, prefix: str, max_file_bytes: int,
                 max_files: int, retention_seconds: float, clock):
        self.root, self.prefix = root, prefix
        self.max_file_bytes, self.max_files = max_file_bytes, max_files
        self.retention_seconds, self.clock = retention_seconds, clock
        self._current: str | None = None

    def _directory(self) -> int:
        root_fd = open_directory(self.root, create=True)
        os.close(root_fd)
        return open_directory(self.root / self.prefix, create=True)

    def _cleanup(self, fd: int, *, reserve: int = 0) -> None:
        files = matching_files(fd, self.prefix)
        remaining = []
        for name, info in files:
            if self.clock() - info.st_mtime >= self.retention_seconds:
                os.unlink(name, dir_fd=fd)
                if self._current == name:
                    self._current = None
            else:
                remaining.append(name)
        while len(remaining) > max(0, self.max_files - reserve):
            name = remaining.pop(0)
            os.unlink(name, dir_fd=fd)
            if self._current == name:
                self._current = None

    def cleanup(self) -> None:
        if not self.root.exists():
            return
        fd = self._directory()
        try:
            self._cleanup(fd)
        finally:
            os.close(fd)

    def append(self, line: bytes) -> None:
        if not line.endswith(b"\n") or len(line) > self.max_file_bytes:
            raise ValueError("record exceeds file budget")
        fd = self._directory()
        try:
            self._cleanup(fd)
            if self._current is not None:
                try:
                    info = os.stat(self._current, dir_fd=fd, follow_symlinks=False)
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                            or info.st_size + len(line) > self.max_file_bytes):
                        self._current = None
                except FileNotFoundError:
                    self._current = None
            created = self._current is None
            if created:
                self._cleanup(fd, reserve=1)
                self._current = f"{self.prefix}-{uuid.uuid4().hex}.jsonl"
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            else:
                flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW
            file_fd = os.open(self._current, flags, 0o600, dir_fd=fd)
            try:
                info = os.fstat(file_fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("unsafe diagnostic file")
                os.fchmod(file_fd, 0o600)
                oldest_record_at = self.clock() if created else info.st_mtime
                view = memoryview(line)
                while view:
                    written = os.write(file_fd, view)
                    if written <= 0:
                        raise OSError("diagnostic write incomplete")
                    view = view[written:]
                # Retention is bounded by the oldest record, not a sliding last-write clock.
                os.utime(file_fd, (oldest_record_at, oldest_record_at))
            finally:
                os.close(file_fd)
        finally:
            os.close(fd)
