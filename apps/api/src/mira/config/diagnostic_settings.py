"""Local bounded diagnostics. Development environment does not imply raw consent."""
from pathlib import PurePosixPath

from pydantic import Field, field_validator, model_validator

from mira.config.base import FrozenSettings


class DiagnosticSettings(FrozenSettings):
    enabled: bool = True
    directory: str = "var/diagnostics"
    max_file_bytes: int = Field(default=1024 * 1024, ge=1024, le=4 * 1024 * 1024)
    max_files: int = Field(default=4, ge=1, le=16)
    retention_seconds: float = Field(default=86400, gt=0, le=86400, allow_inf_nan=False)
    queue_capacity: int = Field(default=256, ge=1, le=1024)
    development_recording: bool = False
    recording_consent: bool = False
    raw_max_file_bytes: int = Field(default=4 * 1024 * 1024, ge=1024, le=4 * 1024 * 1024)
    raw_max_files: int = Field(default=4, ge=1, le=4)
    raw_retention_seconds: float = Field(default=86400, gt=0, le=86400, allow_inf_nan=False)

    @field_validator("directory")
    @classmethod
    def private_local_directory(cls, value):
        # Keep all runtime/private data under the repository's existing ignored var/.
        path = PurePosixPath(value)
        if (path.is_absolute() or path.parts[:1] != ("var",) or len(path.parts) < 2
                or ".." in path.parts or "\\" in value
                or any(not part.replace("-", "").replace("_", "").isalnum() for part in path.parts)):
            raise ValueError("Diagnostics must use a private path below var/.")
        return path.as_posix()

    @model_validator(mode="after")
    def explicit_recording_consent(self):
        if self.development_recording and (not self.enabled or not self.recording_consent):
            raise ValueError("Development recording needs enabled diagnostics and explicit local consent.")
        return self
