"""Bounded, nonblocking local diagnostics; business behavior never waits for disk."""
import json
import math
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from mira.adapters.diagnostics.privacy import PrivacyFilter, encode_event
from mira.adapters.diagnostics.storage import JsonlStore
from mira.application.diagnostic_events import (
    ContentReview,
    DiagnosticContext,
    DiagnosticEvent,
    RecordingKind,
    DiagnosticStatus,
    ReviewedRecording,
)


@dataclass(frozen=True, slots=True)
class DiagnosticOptions:
    root: Path
    max_file_bytes: int = 1024 * 1024
    max_files: int = 4
    retention_seconds: float = 86400
    queue_capacity: int = 256
    raw_max_file_bytes: int = 4 * 1024 * 1024
    raw_max_files: int = 4
    raw_retention_seconds: float = 86400
    max_text_bytes: int = 128 * 1024
    max_audio_bytes: int = 512 * 1024

    def __post_init__(self):
        bounds = {"max_file_bytes": (1024, 4 * 1024 * 1024), "max_files": (1, 16),
                  "raw_max_file_bytes": (1024, 4 * 1024 * 1024), "raw_max_files": (1, 4),
                  "queue_capacity": (1, 1024), "max_text_bytes": (1, 128 * 1024),
                  "max_audio_bytes": (2, 512 * 1024)}
        for key, (minimum, maximum) in bounds.items():
            value = getattr(self, key)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError("invalid diagnostic budget")
        for value in (self.retention_seconds, self.raw_retention_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 86400:
                raise ValueError("invalid diagnostic retention")


class NullDiagnostics:
    def emit(self, event: DiagnosticEvent) -> bool:
        return False

    def capture(self, record: ReviewedRecording) -> bool:
        return False

    def capture_text(self, kind: RecordingKind, text: str, context: DiagnosticContext) -> bool:
        return False

    def add_secret(self, value: str) -> bool:
        return False

    def status(self) -> DiagnosticStatus:
        return DiagnosticStatus()

    def close(self) -> None:
        pass


class LocalDiagnostics:
    def __init__(self, options: DiagnosticOptions, *, secrets=(), worker: bool = True, clock=None):
        self.options = options
        self._clock = clock or time.time
        self._privacy = PrivacyFilter(secrets)
        self._queue: queue.Queue = queue.Queue(maxsize=options.queue_capacity)
        self._lock = threading.Lock()
        self._closed = False
        self._recording = False
        self._filter_ready = True
        self._generation = 0
        self._queued_bytes = 0
        self._counts = dict(accepted_events=0, written_events=0, dropped_events=0,
                            accepted_recordings=0, written_recordings=0, dropped_recordings=0,
                            io_failures=0)
        self._events = JsonlStore(options.root, "events", options.max_file_bytes,
                                 options.max_files, options.retention_seconds, self._clock)
        self._raw = JsonlStore(options.root, "raw", options.raw_max_file_bytes,
                              options.raw_max_files, options.raw_retention_seconds, self._clock)
        self._halt = threading.Event()
        self._thread = None
        if worker:
            self._thread = threading.Thread(target=self._run, name="mira-diagnostics", daemon=True)
            self._thread.start()

    def _count(self, key: str) -> None:
        with self._lock:
            self._counts[key] = min(self._counts[key] + 1, 2 ** 63 - 1)

    def _enqueue(self, record: dict, *, raw: bool, generation: int = 0) -> bool:
        suffix = "recordings" if raw else "events"
        try:
            line = (json.dumps(record, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":")) + "\n").encode()
            budget = self.options.raw_max_file_bytes if raw else self.options.max_file_bytes
            if len(line) > budget:
                raise ValueError("record exceeds budget")
            with self._lock:
                if self._closed or (raw and (not self._recording or generation != self._generation)):
                    raise ValueError("recording unavailable")
                if self._queued_bytes + len(line) > 2 * 1024 * 1024:
                    raise ValueError("diagnostic queue byte budget reached")
                self._queue.put_nowait((raw, generation, line))
                self._queued_bytes += len(line)
                self._counts["accepted_" + suffix] += 1
            return True
        except Exception:
            self._count("dropped_" + suffix)
            return False

    def emit(self, event: DiagnosticEvent) -> bool:
        try:
            record = encode_event(event, self._clock())
        except Exception:
            self._count("dropped_events")
            return False
        return self._enqueue(record, raw=False)

    def capture(self, record: ReviewedRecording) -> bool:
        with self._lock:
            permitted, generation = self._recording and not self._closed, self._generation
        if not permitted:
            self._count("dropped_recordings")
            return False
        try:
            checked = self._privacy.recording(record, now=self._clock(),
                max_text_bytes=self.options.max_text_bytes, max_audio_bytes=self.options.max_audio_bytes)
        except Exception:
            self._count("dropped_recordings")
            return False
        return self._enqueue(checked, raw=True, generation=generation)

    def add_secret(self, value: str) -> bool:
        try:
            with self._lock:
                self._privacy.add_secret(value)
            return True
        except Exception:
            # Cannot protect a newly active credential: raw capture fails closed.
            with self._lock:
                self._filter_ready = False
            self.set_recording(False)
            return False

    def capture_text(self, kind: RecordingKind, text: str, context: DiagnosticContext) -> bool:
        # Text eligibility is a privacy check, unrelated to semantic review verdicts.
        with self._lock:
            permitted = self._recording and not self._closed and self._filter_ready
        if not permitted:
            return False
        try:
            if type(text) is not str or len(text) > self.options.max_text_bytes:
                raise ValueError("text buffer exceeds budget")
            filtered = self._privacy.text(text)
            review = ContentReview.REDACTED if filtered != text else ContentReview.APPROVED
            return self.capture(ReviewedRecording(kind, context, review, text=filtered))
        except Exception:
            self._count("dropped_recordings")
            return False

    def set_recording(self, enabled: bool, *, consent: bool = False) -> bool:
        if type(enabled) is not bool or (enabled and consent is not True):
            return False
        with self._lock:
            if self._closed or (enabled and not self._filter_ready):
                return False
            if self._recording != enabled:
                self._generation += 1
            self._recording = enabled
        return True

    def status(self) -> DiagnosticStatus:
        with self._lock:
            return DiagnosticStatus(available=not self._closed, recording_active=self._recording,
                notice=("开发录制中：已获隐私审核的原始内容可能保存在本机。请勿输入秘密。"
                        if self._recording else ""), pending_records=self._queue.qsize(), **self._counts)

    def _write(self, item) -> None:
        raw, generation, line = item
        suffix = "recordings" if raw else "events"
        try:
            with self._lock:
                eligible = not raw or (self._recording and generation == self._generation)
            if not eligible:
                self._count("dropped_recordings")
                return
            (self._raw if raw else self._events).append(line)
            self._count("written_" + suffix)
        except Exception:
            self._count("io_failures")
            self._count("dropped_" + suffix)
        finally:
            with self._lock:
                self._queued_bytes -= len(line)
            self._queue.task_done()

    def _run(self) -> None:
        last_cleanup = time.monotonic()
        while not self._halt.is_set() or not self._queue.empty():
            try:
                self._write(self._queue.get(timeout=.25))
            except queue.Empty:
                pass
            if time.monotonic() - last_cleanup >= 1:
                self.cleanup()
                last_cleanup = time.monotonic()

    def flush(self, timeout: float = 2.0) -> bool:
        """Test/shutdown helper only; never call on the request event loop."""
        deadline = time.monotonic() + max(0, timeout)
        if self._thread is None:
            while not self._queue.empty() and time.monotonic() < deadline:
                try:
                    self._write(self._queue.get_nowait())
                except queue.Empty:
                    break
        else:
            while self._queue.unfinished_tasks and time.monotonic() < deadline:
                time.sleep(.001)
        return self._queue.unfinished_tasks == 0

    def cleanup(self) -> None:
        for store in (self._events, self._raw):
            try:
                store.cleanup()
            except Exception:
                self._count("io_failures")

    def close(self) -> None:
        with self._lock:
            self._recording = False
            self._generation += 1
            self._closed = True
        self._halt.set()
        # Deliberately no join: stuck storage cannot delay application shutdown.
