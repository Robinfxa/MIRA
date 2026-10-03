"""Local-only export. Raw inclusion always needs separate explicit operator consent."""
import json
import os
import stat
import time
import zipfile
from pathlib import Path

from mira.adapters.diagnostics.privacy import validate_event_record, validate_raw_record
from mira.adapters.diagnostics.storage import matching_files, open_directory

MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_EXPORT_BYTES = 32 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024


def _records(root: Path, prefix: str):
    try:
        fd = open_directory(root / prefix)
    except FileNotFoundError:
        return
    try:
        total = 0
        for name, info in matching_files(fd, prefix):
            if info.st_size > MAX_FILE_BYTES or total + info.st_size > MAX_EXPORT_BYTES:
                yield None
                continue
            total += info.st_size
            file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            with os.fdopen(file_fd, "rb") as source:
                actual = os.fstat(source.fileno())
                if not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1:
                    yield None
                    continue
                consumed = 0
                while consumed <= MAX_FILE_BYTES:
                    line = source.readline(MAX_LINE_BYTES + 1)
                    if not line:
                        break
                    consumed += len(line)
                    if len(line) > MAX_LINE_BYTES or consumed > MAX_FILE_BYTES:
                        yield None
                        break
                    try:
                        record = json.loads(line)
                        yield (validate_event_record(record) if prefix == "events"
                               else validate_raw_record(record))
                    except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
                        yield None
    finally:
        os.close(fd)


def export_diagnostics(root: Path, destination: Path, *, include_raw: bool = False,
                       confirm_sensitive_export: bool = False) -> dict:
    if include_raw and confirm_sensitive_export is not True:
        raise ValueError("separate explicit consent is required for raw export")
    manifest = {"schema": 1, "created_at_unix": round(time.time(), 3),
                "raw_included": bool(include_raw), "event_count": 0, "raw_count": 0,
                "skipped_records": 0, "scope": "local diagnostic metadata",
                "limitations": "Best-effort logs; not a durable history or proof of live success."}
    if include_raw:
        manifest["scope"] = "explicitly consented export including privacy-reviewed content"
        manifest["limitations"] += " Reviewed audio may contain sensitive speech; review before sharing."
    data = {}
    for prefix in (("events", "raw") if include_raw else ("events",)):
        values = []
        for record in _records(root, prefix):
            if record is None:
                manifest["skipped_records"] += 1
                continue
            values.append(json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        manifest["event_count" if prefix == "events" else "raw_count"] = len(values)
        data["events.jsonl" if prefix == "events" else "reviewed-raw.jsonl"] = (
            "\n".join(values) + ("\n" if values else ""))
    parent_fd = open_directory(destination.parent)
    try:
        file_fd = os.open(destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600, dir_fd=parent_fd)
        try:
            with os.fdopen(file_fd, "wb") as output, zipfile.ZipFile(
                    output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                for name, content in data.items():
                    bundle.writestr(name, content)
        except BaseException:
            os.unlink(destination.name, dir_fd=parent_fd)
            raise
    finally:
        os.close(parent_fd)
    return manifest
