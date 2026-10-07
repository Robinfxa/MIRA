"""Explicit per-launch operator capability delivery through a private local file.

No credential is generated on import. The CLI calls this only for an explicitly
requested memory-mode serve operation. The code is never placed in a URL or log;
the app holds only its verifier and invalidates it when the process stops.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import secrets
import stat
from uuid import uuid4


class PairingFileError(ValueError):
    """Fixed safe setup failure, without path contents or credential values."""


@dataclass(frozen=True, slots=True)
class PairingMaterial:
    path: Path
    code: str = field(repr=False)


def create_pairing_material(directory: Path, *, checkout_root: Path,
                            code_factory: Callable[[], str] | None = None) -> PairingMaterial:
    """Create exactly one new 0600 file in an existing operator-private directory.

    Existing files and OS modes are never changed. Tests inject a fixed synthetic
    code; normal explicit CLI use generates an independent 256-bit capability.
    A leftover file from a stopped/failed launch has no authority in a later app.
    """
    if (not isinstance(directory, Path) or not directory.is_absolute()
            or ".." in directory.parts or not hasattr(os, "geteuid")):
        raise PairingFileError("operator_pairing_directory_invalid")
    descriptor = None
    output_descriptor = None
    try:
        root = checkout_root.resolve()
        if directory == root or root in directory.parents:
            raise PairingFileError("operator_pairing_outside_checkout_required")
        current = Path(directory.anchor)
        for part in directory.parts[1:]:
            current /= part
            info = current.lstat()
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or info.st_uid not in {0, os.geteuid()}
                    or (stat.S_IMODE(info.st_mode) & 0o022
                        and not info.st_mode & stat.S_ISVTX)):
                raise PairingFileError("operator_pairing_directory_not_private")
        before = directory.lstat()
        if before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o700:
            raise PairingFileError("operator_pairing_directory_not_private")
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                             | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise PairingFileError("operator_pairing_directory_changed")
        code = code_factory() if code_factory is not None else secrets.token_urlsafe(32)
        if type(code) is not str or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", code) is None:
            raise PairingFileError("operator_pairing_code_invalid")
        filename = "mira-operator-" + uuid4().hex + ".txt"
        output_descriptor = os.open(filename,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600, dir_fd=descriptor)
        body = (code + "\n").encode("ascii")
        offset = 0
        while offset < len(body):
            written = os.write(output_descriptor, body[offset:])
            if written <= 0:
                raise PairingFileError("operator_pairing_write_failed")
            offset += written
        os.fsync(output_descriptor)
        after = directory.lstat()
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            raise PairingFileError("operator_pairing_directory_changed")
        return PairingMaterial(directory / filename, code)
    except PairingFileError:
        raise
    except (OSError, ValueError, RuntimeError):
        raise PairingFileError("operator_pairing_file_unavailable") from None
    finally:
        if output_descriptor is not None:
            os.close(output_descriptor)
        if descriptor is not None:
            os.close(descriptor)
