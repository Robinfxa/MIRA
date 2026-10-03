"""Verify finite English rehearsal assets; regenerate only with installed local Flite.

No provider, credentials, network, installation, browser speech, or app import.
The one manifest is the caption source. This is a build tool, never a runtime TTS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import subprocess
import tempfile
import wave
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "apps/api/src/mira/adapters/generation/rehearsal/fixtures/audio"
IDS = frozenset({"greeting", "camera", "photo", "detail", "absent", "story", "rain", "warm"})
RATE = 24_000
FORMAT = {"schema_version": 1, "fixture_set": "offline-rehearsal-v1", "sample_rate": RATE,
          "channels": 1, "sample_width_bytes": 2, "encoding": "pcm_s16le", "language": "en-US",
          "synthetic": True, "offline_only": True, "human_listening_verified": False,
          "maximum_total_duration_seconds": 90, "maximum_clip_duration_seconds": 30}
FFMPEG = Path("/usr/bin/ffmpeg")
SOURCE_FILES = {
    "ffmpeg": FFMPEG,
    "flite_library": Path("/usr/lib/x86_64-linux-gnu/libflite.so.2.2"),
    "voice_library": Path("/usr/lib/x86_64-linux-gnu/libflite_cmu_us_slt.so.2.2"),
    "license": Path("/usr/share/doc/libflite1/copyright"),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate manifest key")
        result[key] = value
    return result


def load_manifest(folder: Path) -> dict:
    raw = (folder / "manifest.json").read_bytes()
    if len(raw) > 24_000:
        raise ValueError("Manifest exceeds finite fixture limit")
    data = json.loads(raw, object_pairs_hook=unique_keys)
    if any(data.get(key) != value for key, value in FORMAT.items()):
        raise ValueError("Unsupported fixture format or disclosure")
    clips = data.get("clips", {})
    if not isinstance(clips, dict) or set(clips) != IDS:
        raise ValueError("Exactly eight known fixture IDs are required")
    for clip in clips.values():
        caption = clip.get("caption")
        if not isinstance(caption, str) or not 10 <= len(caption) <= 400 or not caption.isascii():
            raise ValueError("Expected bounded original English caption")
    return data


def pcm_stats(pcm: bytes) -> dict:
    if not pcm or len(pcm) % 2 or len(pcm) > 30 * RATE * 2:
        raise ValueError("PCM must contain complete frames within 30 seconds")
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    peak = max(abs(value) for value in samples)
    clipped = sum(value in (-32768, 32767) for value in samples)
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    if clipped or peak < 500 or rms < 100:
        raise ValueError("PCM is clipped, silent, or unexpectedly quiet")
    return {"frames": len(samples), "duration_ms": round(len(samples) * 1000 / RATE),
            "peak_abs": peak, "clipped_samples": clipped,
            "nonzero_samples": sum(value != 0 for value in samples),
            "rms_dbfs": round(20 * math.log10(rms / 32768), 3)}


def verify(folder: Path) -> dict:
    data = load_manifest(folder)
    total_frames = 0
    for name, clip in data["clips"].items():
        if clip.get("pcm_file") != f"{name}.pcm" or clip.get("wav_file") != f"{name}.wav":
            raise ValueError("Fixture paths must be fixed local filenames")
        pcm = (folder / clip["pcm_file"]).read_bytes()
        wav = (folder / clip["wav_file"]).read_bytes()
        expected = {"pcm_sha256": digest(pcm), "wav_sha256": digest(wav),
                    "caption_sha256": digest(clip["caption"].encode("ascii")), **pcm_stats(pcm)}
        if any(clip.get(key) != value for key, value in expected.items()):
            raise ValueError(f"Fixture integrity mismatch: {name}")
        with wave.open(str(folder / clip["wav_file"]), "rb") as source:
            if (source.getnchannels(), source.getsampwidth(), source.getframerate(),
                    source.getcomptype()) != (1, 2, RATE, "NONE"):
                raise ValueError(f"Unexpected WAV format: {name}")
            if source.getnframes() != clip["frames"] or source.readframes(clip["frames"]) != pcm:
                raise ValueError(f"WAV and PCM do not match: {name}")
        total_frames += clip["frames"]
    if total_frames > 90 * RATE or data.get("total_frames") != total_frames:
        raise ValueError("Invalid finite fixture total")
    if data.get("total_duration_ms") != round(total_frames * 1000 / RATE):
        raise ValueError("Invalid total duration")
    return data


def regenerate(folder: Path) -> dict:
    data = load_manifest(folder)
    # Fixed reputable installed tools only; never inherit provider credential variables.
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    source_hashes = {name: {"path": str(path), "sha256": digest(path.read_bytes())}
                     for name, path in SOURCE_FILES.items()}
    version = subprocess.run([str(FFMPEG), "-version"], capture_output=True, text=True,
                             check=True, timeout=10, env=environment).stdout.splitlines()[0]
    with tempfile.TemporaryDirectory(prefix="mira-offline-speech-") as temporary:
        staging = Path(temporary)
        for name, clip in data["clips"].items():
            (staging / "caption.txt").write_text(clip["caption"], encoding="ascii")
            command = [str(FFMPEG), "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                       "flite=textfile=caption.txt:voice=slt", "-af", "volume=0.75", "-ac", "1",
                       "-ar", str(RATE), "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"]
            pcm = subprocess.run(command, cwd=staging, env=environment, capture_output=True,
                                 check=True, timeout=30).stdout
            stats = pcm_stats(pcm)  # Refuse rather than truncate an overlong or damaged clip.
            (staging / f"{name}.pcm").write_bytes(pcm)
            with wave.open(str(staging / f"{name}.wav"), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(RATE)
                output.writeframes(pcm)
            clip.update({"pcm_file": f"{name}.pcm", "wav_file": f"{name}.wav",
                         "pcm_sha256": digest(pcm),
                         "wav_sha256": digest((staging / f"{name}.wav").read_bytes()),
                         "caption_sha256": digest(clip["caption"].encode("ascii")), **stats})
        data["total_frames"] = sum(clip["frames"] for clip in data["clips"].values())
        data["total_duration_ms"] = round(data["total_frames"] * 1000 / RATE)
        data["provenance"].update({"ffmpeg_version": version,
                                    "generator_sha256": digest(Path(__file__).read_bytes()),
                                    "installed_source_files": source_hashes,
                                    "generated_at": datetime.now(UTC).isoformat()})
        (staging / "manifest.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        verify(staging)
        # Replace manifest last. A crash leaves detectable hash mismatch, never fabricated success.
        for name in data["clips"]:
            for extension in ("pcm", "wav"):
                (folder / f"{name}.{extension}").write_bytes((staging / f"{name}.{extension}").read_bytes())
        (folder / "manifest.json").write_bytes((staging / "manifest.json").read_bytes())
    return verify(folder)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Verify shipped bytes; default, no FFmpeg needed")
    mode.add_argument("--regenerate", action="store_true", help="Rebuild with installed local FFmpeg/Flite")
    parser.add_argument("--asset-dir", type=Path, default=ASSET_DIR)
    args = parser.parse_args()
    try:
        data = regenerate(args.asset_dir) if args.regenerate else verify(args.asset_dir)
    except (OSError, ValueError, KeyError, TypeError, wave.Error, subprocess.SubprocessError) as error:
        print(f"Offline rehearsal audio check failed: {type(error).__name__}")
        return 2
    print(f"Verified 8 synthetic English clips, {data['total_duration_ms'] / 1000:.3f}s, "
          "PCM16 mono 24000 Hz; physical playback/listening not verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
