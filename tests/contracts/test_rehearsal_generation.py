"""DEMO01-001/002/003/004: finite, explicit offline rehearsal contracts."""
from dataclasses import replace
from pathlib import Path

import pytest

from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext, ReviewVerdict
from mira.bootstrap.providers import create_providers
from mira.config.loader import ConfigurationError, load_settings
from mira.config.settings import ProviderSettings
from mira.domain.models import Effect, EffectKind

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = {"你好": "greeting", "不要拍我": "camera", "看照片": "photo", "听雨": "rain", "暖灯": "warm"}


def selected():
    return create_providers(ProviderSettings(generation="rehearsal", mock_delay_ms=0))


def context(text, presented=(), accepted=()):
    return GenerationContext(text, (text,), presented, 1, accepted_prefix=accepted)


def photo():
    return Effect("photo", EffectKind.MEDIA, "trip_photo", "a" * 64, 1, 1)


def test_rehearsal_profile_is_explicit_offline_and_default_is_unchanged():
    settings = load_settings(root=ROOT, environ={"MIRA_PROFILE": "rehearsal"})
    assert settings.providers.generation == "rehearsal"
    assert not settings.providers.allow_external_calls and not settings.providers.allow_paid_api
    assert not settings.diagnostics.development_recording and not settings.diagnostics.recording_consent
    assert load_settings(root=ROOT, environ={}).providers.generation == "mock"


@pytest.mark.asyncio
@pytest.mark.parametrize("command,clip", COMMANDS.items())
async def test_exact_commands_get_distinct_authored_audio_caption_and_action(command, clip):
    providers = selected()
    rows = [row async for row in providers.generation.generate(context(command))]
    assert [row.fixture_id for row in rows] == ["rehearsal:" + clip]
    assert {effect.kind for effect in rows[0].effects} >= {EffectKind.SPEECH, EffectKind.SUBTITLE}
    for row in rows:
        assert (await providers.review.review(context(command), row)).verdict == ReviewVerdict.ALLOW
    changed = replace(rows[0], effects=(EffectProposal(EffectKind.SPEECH, "arbitrary user content"),))
    assert (await providers.review.review(context(command), changed)).verdict == ReviewVerdict.REJECT
    assert (await providers.review.review(context("unrecognized"), rows[0])).verdict == ReviewVerdict.REJECT


@pytest.mark.asyncio
async def test_unknown_text_is_not_recognized_echoed_or_spoken():
    providers = selected()
    rows = [row async for row in providers.generation.generate(context("private words do not echo"))]
    assert [row.fixture_id for row in rows] == ["rehearsal:help"]
    assert [effect.kind for effect in rows[0].effects] == [EffectKind.SUBTITLE]
    assert "private words" not in rows[0].effects[0].value
    assert "看照片" in rows[0].effects[0].value and "离线" in rows[0].effects[0].value
    assert (await providers.review.review(context("private words do not echo"), rows[0])).verdict == ReviewVerdict.ALLOW
    foreign = CandidateRange(rows[0].effects, "hello")
    assert (await providers.review.review(context("private words do not echo"), foreign)).verdict == ReviewVerdict.REJECT


@pytest.mark.asyncio
async def test_follow_up_uses_presented_photo_not_unpresented_plan():
    providers = selected()
    before = [r async for r in providers.generation.generate(context("照片里有什么", accepted=(photo(),)))]
    after = [r async for r in providers.generation.generate(context("照片里有什么", presented=(photo(),)))]
    assert before[0].fixture_id == "rehearsal:absent"
    assert after[0].fixture_id == "rehearsal:detail"
    assert (await providers.review.review(context("照片里有什么"), after[0])).verdict == ReviewVerdict.REJECT


@pytest.mark.asyncio
async def test_story_is_history_gated_and_failure_does_not_fall_back():
    providers = selected()
    before = [r async for r in providers.generation.generate(context("讲讲旅途"))]
    after = [r async for r in providers.generation.generate(context("讲讲旅途", presented=(photo(),)))]
    assert before[0].fixture_id == "rehearsal:absent"
    assert after[0].fixture_id == "rehearsal:story"
    with pytest.raises(RuntimeError, match="rehearsal"):
        _ = [r async for r in providers.generation.generate(context("/fail"))]


@pytest.mark.parametrize("patch", [{"allow_external_calls": True}, {"allow_paid_api": True}, {"review": "jev"}])
def test_rehearsal_rejects_live_or_paid_pairings(patch):
    with pytest.raises(ConfigurationError):
        create_providers(ProviderSettings(generation="rehearsal", **patch))


@pytest.mark.asyncio
async def test_speech_streams_exact_clip_contiguously_and_rejects_arbitrary_text():
    providers = selected()
    row = [r async for r in providers.generation.generate(context("你好"))][0]
    text = next(e.value for e in row.effects if e.kind == EffectKind.SPEECH)
    speech = providers.speech_synthesis
    assert speech is not None
    packets = [p async for p in speech.synthesize(text, "synthetic-stream")]
    cursor = 0
    for packet in packets:
        assert packet.stream_id == "synthetic-stream" and packet.sample_rate_hz == 24000
        assert packet.first_sample == cursor and 0 < len(packet.pcm) <= 12000
        cursor += len(packet.pcm) // 2
    assert cursor > 24000
    with pytest.raises(ValueError, match="exact"):
        _ = [p async for p in speech.synthesize(text + " arbitrary addition", "unapproved")]


def test_corrupted_or_redirected_audio_package_fails_closed(monkeypatch, tmp_path):
    import json
    import shutil
    from mira.adapters.generation.rehearsal import backend

    original = backend.files(backend.__package__)
    copied = tmp_path / "fixtures" / "audio"
    shutil.copytree(original.joinpath("fixtures/audio"), copied)
    monkeypatch.setattr(backend, "files", lambda _: tmp_path)
    target = copied / "greeting.pcm"
    data = target.read_bytes()
    target.write_bytes(b"\xff\xff" + data[2:])
    with pytest.raises(ValueError, match="integrity"):
        backend.load_clips()
    target.write_bytes(data)
    manifest_path = copied / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest['clips']['greeting']['pcm_file'] = "../../external.pcm"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="identity"):
        backend.load_clips()


def test_rehearsal_walkthrough_lists_every_finite_command_and_explicit_limits():
    from html.parser import HTMLParser
    from mira.adapters.generation.rehearsal.backend import COMMANDS

    class Buttons(HTMLParser):
        commands = set()
        def handle_starttag(self, tag, attrs):
            if tag == 'button':
                attrs = dict(attrs)
                if 'data-command' in attrs:
                    self.commands.add(attrs['data-command'])
    html = (ROOT / 'apps/web/index.html').read_text()
    parser = Buttons()
    parser.feed(html)
    assert set(COMMANDS) | {'照片里有什么', '讲讲旅途', '/fail'} <= parser.commands
    assert 'OFFLINE' in html and '不录音' in html and '预录英文合成音频' in html
    assert '3–5 分钟' in html and '固定口令' in html
