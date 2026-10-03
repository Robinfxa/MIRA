"""Finite speech assets are real PCM, exact-caption bound, and visibly synthetic English."""
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "apps/api/src/mira/adapters/generation/rehearsal/fixtures/audio"
SCRIPT = ROOT / "tools/generate_rehearsal_audio.py"
IDS = {"greeting", "camera", "photo", "detail", "absent", "story", "rain", "warm"}


def manifest():
    path = ASSETS / "manifest.json"
    assert path.is_file(), "Finite rehearsal speech manifest must ship with the package"
    return json.loads(path.read_text(encoding="utf-8"))


def test_assets_are_finite_bounded_and_disclosed_as_synthetic_english():
    data = manifest()
    assert set(data["clips"]) == IDS
    assert data["schema_version"] == 1
    assert data["fixture_set"] == "offline-rehearsal-v1"
    assert data["language"] == "en-US"
    assert data["synthetic"] is True and data["offline_only"] is True
    assert data["human_listening_verified"] is False
    assert "No Chinese speech" in data["limitation"]
    assert data["maximum_total_duration_seconds"] == 90
    assert data["maximum_clip_duration_seconds"] == 30
    assert 0 < data["total_frames"] <= 90 * 24000
    assert data["total_frames"] == sum(clip["frames"] for clip in data["clips"].values())
    assert data["total_duration_ms"] == round(data["total_frames"] * 1000 / 24000)
    assert 10_000 <= data["clips"]["story"]["duration_ms"] < 30_000


@pytest.mark.parametrize("clip_id", sorted(IDS))
def test_each_clip_has_exact_pcm_wav_caption_and_signal_integrity(clip_id):
    data = manifest()
    assert (data["sample_rate"], data["channels"], data["sample_width_bytes"],
            data["encoding"]) == (24000, 1, 2, "pcm_s16le")
    clip = data["clips"][clip_id]
    assert clip["pcm_file"] == f"{clip_id}.pcm"
    assert clip["wav_file"] == f"{clip_id}.wav"
    pcm = (ASSETS / clip["pcm_file"]).read_bytes()
    wav = (ASSETS / clip["wav_file"]).read_bytes()
    assert hashlib.sha256(pcm).hexdigest() == clip["pcm_sha256"]
    assert hashlib.sha256(wav).hexdigest() == clip["wav_sha256"]
    assert hashlib.sha256(clip["caption"].encode("ascii")).hexdigest() == clip["caption_sha256"]
    assert len(pcm) == clip["frames"] * 2 and 0 < len(pcm) <= 30 * 24000 * 2
    samples = struct.unpack(f"<{clip['frames']}h", pcm)
    assert clip["peak_abs"] == max(abs(sample) for sample in samples)
    assert 500 <= clip["peak_abs"] < 32767
    assert clip["clipped_samples"] == sum(value in (-32768, 32767) for value in samples) == 0
    assert clip["nonzero_samples"] == sum(value != 0 for value in samples) > 0
    assert min(samples) < 0 < max(samples)
    assert clip["duration_ms"] == round(len(samples) * 1000 / 24000)
    with wave.open(str(ASSETS / clip["wav_file"]), "rb") as source:
        assert (source.getnchannels(), source.getsampwidth(), source.getframerate(),
                source.getcomptype()) == (1, 2, 24000, "NONE")
        assert source.getnframes() == clip["frames"]
        assert source.readframes(source.getnframes()) == pcm


def test_provenance_records_original_script_installed_tool_and_voice_hashes():
    data = manifest()
    assert SCRIPT.is_file()
    provenance = data["provenance"]
    assert "Original MIRA" in provenance["script_author"]
    assert provenance["voice"] == "slt"
    assert "Flite" in provenance["voice_source"]
    assert provenance["ffmpeg_version"].startswith("ffmpeg version ")
    assert provenance["generator_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert provenance["upstream_license_url"] == "https://github.com/festvox/flite/blob/master/COPYING"
    assert "cmu_us_slt" in provenance["voice_source_url"]
    for item in provenance["installed_source_files"].values():
        assert len(item["sha256"]) == 64
        int(item["sha256"], 16)
    assert "No microphone, physical playback, listening" in provenance["verification_scope"]


@pytest.mark.parametrize("damage", ["pcm", "caption", "path", "format"])
def test_offline_verifier_rejects_modified_assets_and_claims(tmp_path, damage):
    assert SCRIPT.is_file(), "Offline verifier must ship with the assets"
    manifest()
    folder = tmp_path / "audio"
    shutil.copytree(ASSETS, folder)
    path = folder / "manifest.json"
    data = json.loads(path.read_text())
    if damage == "pcm":
        pcm = folder / "greeting.pcm"
        pcm.write_bytes(b"\x00\x00" * (len(pcm.read_bytes()) // 2))
    elif damage == "caption":
        data["clips"]["greeting"]["caption"] = "This was never the recorded caption."
    elif damage == "path":
        data["clips"]["greeting"]["pcm_file"] = "../greeting.pcm"
    else:
        data["language"] = "cmn-CN"
    path.write_text(json.dumps(data))
    result = subprocess.run([sys.executable, str(SCRIPT), "--check", "--asset-dir", str(folder)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "check failed" in result.stdout


def test_shipped_assets_verify_without_using_ffmpeg_or_provider_environment(tmp_path):
    assert SCRIPT.is_file(), "Offline verifier must ship with the assets"
    manifest()
    result = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True,
                            text=True, timeout=10, env={"PATH": str(tmp_path)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Verified 8 synthetic English clips" in result.stdout
    assert "physical playback/listening not verified" in result.stdout
