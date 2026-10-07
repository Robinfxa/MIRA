"""MIRA direct-provider entry: subscription OAuth or official API, never CLI fallback."""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[1]


class EntryError(ValueError):
    """Actionable fixed messages, never provider payloads or credential values."""

    def __init__(self, message: str, *, stage: str | None = None,
                 invalid_fields: tuple[str, ...] = ()):
        super().__init__(message)
        self.stage = stage
        self.invalid_fields = invalid_fields


def _configuration_entry_error(error: ValueError) -> EntryError:
    """Map loader field paths to known public labels; never return exception text."""
    from mira.config.loader import ENV_FIELDS
    safe_fields = {'.'.join(location):
        (location[-1].upper() if location[:2] == ('services', 'speech') else name)
        for name, location in ENV_FIELDS.items()}
    prefix = 'Invalid configuration fields: '
    message = str(error)
    fields: tuple[str, ...] = ()
    # Unknown TOML keys and profile names can contain arbitrary user input. Only
    # bounded, exact matches from the loader's declared field table are emitted.
    if len(message) <= 4096 and message.startswith(prefix):
        fields = tuple(dict.fromkeys(safe_fields[field]
            for field in message[len(prefix):].split(', ') if field in safe_fields))[:8]
    recovery = 'Configuration validation failed; review the selected env file and supported MIRA fields.'
    if 'TTS_LOCATION' in fields:
        recovery = ('Configuration validation failed. Set MIRA_SERVICES__SPEECH__TTS_LOCATION=global; '
            'select the voice separately with MIRA_SERVICES__SPEECH__TTS_VOICE.')
    return EntryError(recovery + ' No values were printed.',
        stage='config_validation', invalid_fields=fields)


@dataclass(frozen=True, slots=True)
class ApiCredential:
    access_token: SecretStr = field(repr=False)
    account_id: None = None
    residency: None = None


class ApiCredentialSource:
    def __init__(self, key: SecretStr):
        if type(key) is not SecretStr or not key.get_secret_value():
            raise EntryError('Official API mode needs an explicitly configured API key.')
        self._credential = ApiCredential(key)

    async def get_credentials(self) -> ApiCredential:
        return self._credential

    def __repr__(self) -> str:
        return '<ApiCredentialSource redacted>'


def _private_file(path: Path, label: str) -> Path:
    # A normal project .env is supported; no artificial outside-checkout rule.
    path = path.expanduser().absolute()
    stage = {'MIRA environment file': 'env_file_metadata',
        'Google ADC file': 'adc_file_metadata'}.get(label, 'private_file_metadata')
    try:
        info = path.lstat()
    except OSError:
        raise EntryError(f'{label} is missing or unreadable.', stage=stage) from None
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise EntryError(f'{label} must be an owner-only regular file; values were not read.', stage=stage)
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('check', 'serve'):
        item = commands.add_parser(command)
        item.add_argument('--provider', choices=('chatgpt_subscription', 'openai_api'), required=True)
        item.add_argument('--model', required=True)
        item.add_argument('--service-tier', choices=('fast', 'standard'),
            help='requested tier: subscription gpt-6-luna defaults to Fast (2.5x included usage); '
                 'other defaults unchanged; standard opts out; provider confirmation is separate')
        item.add_argument('--env-file', type=Path, required=True)
        item.add_argument('--auth-store', type=Path,
            help='MIRA-owned subscription session only; never a Codex CLI auth file')
        item.add_argument('--port', type=int, default=8000)
        from tools.private_device_access import add_device_arguments
        add_device_arguments(item)
        item.add_argument('--authorize-provider-data', action='store_true',
            help='send dialogue to the selected OpenAI service; explicit legacy_jev mode also uses TypeSafe/JEV')
        item.add_argument('--action-review-mode', choices=('luna_tools', 'legacy_jev'), default='luna_tools',
            help='default Luna native tools with local typed/permission checks; legacy_jev explicitly restores bounded historical reviews')
        item.add_argument('--authorize-api-billing', action='store_true',
            help='explicit official API-key billing route; no automatic subscription fallback')
        item.add_argument('--generation-requests', type=int, default=None,
            help='explicit finite request ceiling; subscription default has no local count limit; API default is 20')
        item.add_argument('--legacy-media-proposals', action='store_true',
            help='explicitly retain the pre-tool media proposal path; default uses bounded Luna media tools with at most two existing generation requests per tool turn')
        item.add_argument('--turns', type=int, default=None,
            help='explicit finite text-turn ceiling; subscription default is unlimited; API default is 20')
        item.add_argument('--local-unlimited', action='store_true',
            help='compatibility flag: voice limits are already unlimited by default; explicit finite options still apply')
        item.add_argument('--input-jev-requests', type=int, default=40)
        item.add_argument('--output-jev-requests', type=int, default=40)
        item.add_argument('--boundary-max-requests', type=int, default=0,
            help='legacy_jev only: opt-in caption-boundary attempts, 0–100; native mode uses deterministic sentence boundaries with no service call')
        item.add_argument('--boundary-timeout-seconds', type=float, default=0.4,
            help='hard caption-tail planning wait, >0 and <=2 seconds; timeout keeps the whole original tail')
        item.add_argument('--review-timeout-seconds', type=float, default=10)
        item.add_argument('--input-review-max-bytes', type=int,
            help='finite JEV input request limit, 1024–131072; character application default 32768')
        item.add_argument('--output-review-max-bytes', type=int,
            help='finite JEV output-review request limit, 1024–131072; character application default 65536')
        item.add_argument('--turn-timeout-seconds', type=float, default=60)
        item.add_argument('--voice', action='store_true')
        item.add_argument('--story', action='store_true',
            help='include MIRA authored fiction and reviewed story/affect suggestions; no private recording by default')
        item.add_argument('--story-images', action='store_true',
            help='optional story pictures, off by default; subscription first with separate image-data/usage consent')
        item.add_argument('--story-image-provider',
            help='chatgpt_subscription by default on subscription text; openai_api remains explicit; mixed routes require this choice; no fallback')
        item.add_argument('--story-image-model', help='subscription is pinned to gpt-image-2; API requires an explicit model; does not enable images')
        item.add_argument('--story-image-review-model', help='independent pixel-review model; subscription defaults to selected dialogue model; capability unverified')
        item.add_argument('--story-image-quality', help='subscription auto only; API requires explicit low, medium, or high')
        item.add_argument('--authorize-story-image-data-to-openai', action='store_true',
            help='send released fictional scene specification and generated PNG/criteria to the selected OpenAI image and pixel-review route')
        item.add_argument('--authorize-story-image-custom-brief', action='store_true',
            help='also allow the current requested fictional environment/object brief (up to600 characters) to the selected OpenAI image route; no full transcript, memory packets or reference images are attached')
        item.add_argument('--authorize-story-image-api-spend', action='store_true',
            help='separate image + pixel review API billing consent; planning reservations are not provider dollar caps')
        item.add_argument('--authorize-story-image-subscription-usage', action='store_true',
            help='separate consent for internal subscription image + pixel-review usage; entitlement and quota consumption unknown')
        item.add_argument('--story-image-max-attempts', type=int, default=1, help='1–4 admitted jobs per process; one image and at most one review each; no retry')
        item.add_argument('--story-image-max-output-bytes', type=int, default=8388608)
        item.add_argument('--story-image-max-total-bytes', type=int, default=8388608,
            help='nonrefundable output-byte reservations per process, at most 33554432')
        item.add_argument('--story-image-timeout-seconds', type=float, default=120)
        item.add_argument('--story-image-generation-timeout-seconds', type=float, default=90)
        item.add_argument('--story-image-review-timeout-seconds', type=float, default=45)
        item.add_argument('--story-image-max-wire-bytes', type=int, default=12000000)
        item.add_argument('--story-image-review-max-wire-bytes', type=int, default=65536)
        item.add_argument('--story-image-review-max-output-tokens', type=int,
            help='API only, default 512 and range 128–512; subscription remote token cap unavailable')
        item.add_argument('--story-image-reservation-microusd', type=int,
            help='positive local planning reservation per admitted job, in millionths of USD; not a bill cap')
        item.add_argument('--story-image-total-reservation-microusd', type=int,
            help='positive process planning allowance in millionths of USD; not a provider-enforced limit')
        item.add_argument('--character-renderer',choices=('static-pixi','code-native-review'),default='code-native-review',
            help='current adopted code-native character; static-pixi remains an explicit fallback')
        item.add_argument('--story-db', type=Path,
            help='optional private character checkpoint database; only qualified fictional presentations are saved')
        item.add_argument('--story-scope',
            help='explicit local character-history scope, never inferred from a browser or sent as raw text')
        item.add_argument('--authorize-story-persistence-and-recall', action='store_true',
            help='save character receipts locally and recall them to the selected OpenAI service (plus JEV only in legacy_jev mode); with voice, approved derived speech also goes to Google TTS')
        item.add_argument('--adc-file', type=Path)
        item.add_argument('--authorize-google-voice-data-and-spend', action='store_true')
        item.add_argument('--stt-requests', type=int, default=None,
            help='optional finite shared STT request ceiling; default has no local count cap, Google usage remains billable')
        item.add_argument('--tts-requests', type=int, default=20)
        item.add_argument('--stt-max-seconds', type=float, default=120,
            help='finite per-recognition-RPC duration; continuous listening rolls streams without closing the microphone')
        item.add_argument('--tts-max-seconds', type=float, default=30)
        item.add_argument('--listen-silence-ms', type=int, default=700,
            help='Captured speech quiet interval before bounded final drain, 250–2000 milliseconds; heuristic, not a spend cap.')
        item.add_argument('--listen-grace-seconds', type=float, default=0.65,
            help='Natural endpoint grace after provider activity/final evidence, 0.25–2 seconds; heuristic.')
        item.add_argument('--listen-drain-seconds', type=float, default=2.0,
            help='Bounded final-result drain before a visible stop, 0.1–5 seconds.')
        item.add_argument('--listen-max-recognition-streams', type=int, default=None,
            help='optional finite recognition substream ceiling per listening lease, 1–32; default unlimited')
        item.add_argument('--listen-max-seconds', type=int, default=None, help='optional local lease duration, 1–290 seconds; default unlimited')
        item.add_argument('--listen-max-utterances', type=int, default=None, help='optional sends per lease, 1–32; default unlimited')
        item.add_argument('--listen-max-session-starts', type=int, default=None, help='optional starts per session, 1–16; default unlimited')
        item.add_argument('--listen-max-total-starts', type=int, default=None, help='optional starts per service process, 1–100; default unlimited')
        item.add_argument('--memory-db', type=Path, help='existing private memory database; default disabled')
        item.add_argument('--memory-scope-config', type=Path, help='private operator-owned scope file')
        item.add_argument('--memory-scope', help='one operator-selected scope alias')
        item.add_argument('--authorize-memory-to-selected-provider', '--authorize-memory-to-selected-provider-and-jev',
            dest='authorize_memory_to_selected_provider_and_jev', action='store_true',
            help='allow selected stored evidence to the chosen OpenAI route (and JEV only in explicit legacy_jev mode); does not record dialogue')
        item.add_argument('--authorize-memory-derived-speech-to-google', action='store_true',
            help='separate consent: approved generated speech may include recalled evidence and be sent to Google Cloud TTS')
        item.add_argument('--authorize-local-memory-management', action='store_true',
            help='separate local save/correct/soft-forget/restore consent in the paired UI')
        item.add_argument('--conversation-db', type=Path, help='dedicated private transcript database; default disabled')
        item.add_argument('--conversation-scope-config', type=Path, help='existing private scope file; never chosen by the browser')
        item.add_argument('--conversation-scope', help='one fixed local scope alias')
        item.add_argument('--authorize-conversation-persistence', action='store_true', help='save accepted dialogue and actual software receipt facts locally after pairing')
        item.add_argument('--authorize-local-conversation-management', action='store_true', help='allow paired confirmed correction/soft-forget/restore of transcript inputs')
        item.add_argument('--recall-conversation-session', help='exact prior local session ID, no automatic latest-session recall')
        item.add_argument('--authorize-conversation-to-selected-provider', '--authorize-conversation-to-selected-provider-and-jev',
            dest='authorize_conversation_to_selected_provider_and_jev', action='store_true',
            help='separate transcript recall consent for the chosen OpenAI route (and JEV only in explicit legacy_jev mode)')
        item.add_argument('--authorize-conversation-derived-speech-to-google', action='store_true', help='separate consent for recalled details in generated Google TTS speech')
        item.add_argument('--create-local-operator-pairing', action='store_true',
            help='serve creates a private one-use pairing file; check creates nothing')
    return parser


def _memory_recipients(provider: str, voice: bool = False, action_review_mode: str = 'luna_tools') -> list[str]:
    names = {'chatgpt_subscription': 'OpenAI ChatGPT subscription backend',
             'openai_api': 'OpenAI official API'}
    if provider not in names:
        raise EntryError('Choose an explicit supported provider before memory transmission.')
    if action_review_mode not in ('luna_tools', 'legacy_jev'):
        raise EntryError('Choose an explicit supported action review mode.')
    return [names[provider]] + (['TypeSafe/JEV output review'] if action_review_mode == 'legacy_jev' else []) + ([
        'Google Cloud TTS (approved generated speech may contain recalled evidence)'] if voice else [])


def _memory_options(args):
    values = (args.memory_db, args.memory_scope_config, args.memory_scope)
    authorized = args.authorize_memory_to_selected_provider_and_jev
    if args.authorize_memory_derived_speech_to_google and (not authorized or not args.voice):
        raise EntryError('Google stored-evidence consent requires explicitly configured memory and voice modes.')
    if not authorized and all(value is None for value in values):
        if args.authorize_local_memory_management:
            raise EntryError('Local memory management alone does not enable recall or transmission; configure memory mode explicitly.')
        if args.create_local_operator_pairing and args.story_db is None and args.conversation_db is None:
            raise EntryError('Operator pairing is only available with explicitly configured memory mode.')
        return None
    if not authorized or any(value is None for value in values):
        raise EntryError('Memory recall needs database, scope config, scope alias, and separate stored-evidence transmission consent.')
    if not args.create_local_operator_pairing:
        raise EntryError('Memory mode needs --create-local-operator-pairing; check creates no credential.')
    if args.voice and not args.authorize_memory_derived_speech_to_google:
        raise EntryError('Memory with voice requires --authorize-memory-derived-speech-to-google; Google TTS may receive recalled details in approved generated speech.')
    _memory_recipients(args.provider, args.voice, args.action_review_mode)
    from mira.config.memory import load_memory_recall_options
    from mira.config.loader import ConfigurationError
    try:
        return load_memory_recall_options(database=args.memory_db,
            scope_config=args.memory_scope_config, scope_alias=args.memory_scope,
            authorized_transmission=True, checkout_root=ROOT)
    except ConfigurationError as error:
        # The existing memory loader emits fixed codes, never file contents/scope IDs.
        raise EntryError(str(error)) from None


def _conversation_options(args):
    values=(args.conversation_db,args.conversation_scope_config,args.conversation_scope)
    flags=(args.authorize_conversation_persistence,args.authorize_local_conversation_management,
        args.authorize_conversation_to_selected_provider_and_jev,args.authorize_conversation_derived_speech_to_google)
    if not any(flags) and all(v is None for v in values) and args.recall_conversation_session is None:return None
    if not args.authorize_conversation_persistence or any(v is None for v in values) or not args.create_local_operator_pairing:
        raise EntryError('Conversation recording requires a dedicated database, fixed scope file/alias, separate persistence consent, and local operator pairing.')
    from mira.config.conversation import load_conversation_options
    return load_conversation_options(database=args.conversation_db,scope_config=args.conversation_scope_config,
        scope_alias=args.conversation_scope,checkout_root=ROOT,authorize_persistence=True,
        authorize_management=args.authorize_local_conversation_management,
        recall_session_id=args.recall_conversation_session,
        authorize_recall_to_provider_and_jev=args.authorize_conversation_to_selected_provider_and_jev,
        authorize_recalled_speech_to_google=args.authorize_conversation_derived_speech_to_google,
        speech_enabled=args.voice,excluded_databases=tuple(p for p in (args.memory_db,args.story_db) if p is not None))


def _load(args):
    from mira.config.loader import ConfigurationError, load_settings
    from mira.bootstrap.development_usage import (UsageProfile, validate_count,
        validate_optional_count, validate_boundary_timeout)
    from mira.bootstrap.direct_provider_app import _bounded_timeout, validate_natural_listening_options
    import math
    import re

    legacy_jev = args.action_review_mode == 'legacy_jev'
    if not legacy_jev and (args.legacy_media_proposals or args.boundary_max_requests):
        raise EntryError('Legacy media proposals and JEV boundary budgets require explicit --action-review-mode legacy_jev.',
            stage='action_review_configuration')
    try:
        _listening_limits(args)
        validate_natural_listening_options(client_silence_ms=args.listen_silence_ms,
            natural_grace_seconds=args.listen_grace_seconds,
            drain_timeout_seconds=args.listen_drain_seconds,
            max_recognition_streams=args.listen_max_recognition_streams)
    except ConfigurationError as error:
        field = str(error).partition(' ')[0]
        allowed = {'listen_silence_ms', 'listen_grace_seconds', 'listen_drain_seconds', 'listen_max_recognition_streams',
            'listen_max_seconds', 'listen_max_utterances', 'listen_max_session_starts', 'listen_max_total_starts'}
        raise EntryError('Continuous listening limits must use the documented finite ranges.',
            stage='continuous_settings', invalid_fields=(field,) if field in allowed else ()) from None
    if not 1024 <= args.port <= 65535:
        raise EntryError('Port must be between1024 and65535.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', args.model):
        raise EntryError('Select an explicit model identifier, not instructions.')
    if args.turns is not None:
        validate_count(args.turns, UsageProfile.APPLICATION, name='turns', turns=True)
    for name, value in (('generation_requests', _generation_request_limit(args)),
                        ('turns', _session_turn_limit(args)),
                        ('input_jev_requests', args.input_jev_requests),
                        ('output_jev_requests', args.output_jev_requests)):
        if value is not None:
            validate_count(value, UsageProfile.APPLICATION, name=name, turns=name == 'turns')
    validate_optional_count(args.boundary_max_requests, UsageProfile.APPLICATION, name='Boundary JEV request ceiling')
    validate_boundary_timeout(args.boundary_timeout_seconds)
    _bounded_timeout(args.review_timeout_seconds, 'Review timeout')
    if not math.isfinite(args.turn_timeout_seconds) or not 0 < args.turn_timeout_seconds <= 120:
        raise EntryError('The complete turn timeout must be finite and at most120 seconds.')
    from tools.private_device_access import device_options
    access = device_options(args)
    env_file = _private_file(args.env_file, 'MIRA environment file')
    try:
        settings = load_settings(root=ROOT, env_file=env_file,
            environ={}, load_legacy_jev=legacy_jev, overrides={'http': access.http_settings() if access is not None else {
                'host': '127.0.0.1', 'port': args.port, 'private_network': False,
                'allowed_origins': [f'http://127.0.0.1:{args.port}', f'http://localhost:{args.port}']},
                'runtime': {'timeout_seconds': args.turn_timeout_seconds}})
    except ConfigurationError as error:
        raise _configuration_entry_error(error) from None
    if legacy_jev and (settings.services.jev.api_key is None or settings.services.jev.model != 'jev-1.13.0'):
        raise EntryError('Configure the TypeSafe/JEV key and model jev-1.13.0 in the explicit env file.')
    if args.provider == 'openai_api' and settings.services.openai.api_key is None:
        raise EntryError('Official API mode needs its own explicit OpenAI API key; no OAuth fallback is used.')
    if args.auth_store is not None and not args.auth_store.expanduser().is_absolute():
        raise EntryError('The selected MIRA OAuth store must be an absolute path.')
    voice_limits = None
    if args.voice:
        if args.adc_file is None:
            raise EntryError('Voice mode needs the explicit Google ADC path.')
        _private_file(args.adc_file, 'Google ADC file')
        from mira.bootstrap.development_voice import DevelopmentVoiceLimits, validate_development_voice_settings
        from mira.config.loader import ConfigurationError
        try:
            validate_development_voice_settings(settings.services.speech, usage_profile=UsageProfile.APPLICATION)
        except ConfigurationError as error:
            # This pure validator emits only fixed configuration instructions,
            # never values from the user's file or a provider response.
            raise EntryError(str(error)) from None
        voice_limits = DevelopmentVoiceLimits(stt_request_limit=args.stt_requests,
            tts_request_limit=args.tts_requests, stt_max_input_seconds=args.stt_max_seconds,
            tts_max_audio_seconds=args.tts_max_seconds, usage_profile=UsageProfile.APPLICATION)
    return settings, voice_limits


def _story_image_options(args):
    from mira.bootstrap.story_image_provider import StoryImageOptions
    if args.authorize_story_image_custom_brief and args.legacy_media_proposals:
        raise EntryError('Custom fictional image briefs require media tools; remove the explicit legacy-media-proposals option.',
            stage='story_image_configuration', invalid_fields=('legacy_media_proposals',))
    provider = args.story_image_provider
    if args.story_images and provider is None and args.provider == 'chatgpt_subscription':
        provider = 'chatgpt_subscription'
    subscription = provider == 'chatgpt_subscription'
    return StoryImageOptions(enabled=args.story_images, provider=provider,
        image_model=args.story_image_model if args.story_image_model is not None else
            ('gpt-image-2' if subscription else None),
        review_model=args.story_image_review_model if args.story_image_review_model is not None else
            (args.model if subscription else None),
        quality=args.story_image_quality if args.story_image_quality is not None else
            ('auto' if subscription else None),
        authorize_data_to_openai=args.authorize_story_image_data_to_openai,
        authorize_api_spend=args.authorize_story_image_api_spend,
        authorize_subscription_usage=args.authorize_story_image_subscription_usage,
        authorize_custom_brief=args.authorize_story_image_custom_brief,
        max_attempts=args.story_image_max_attempts,
        max_output_bytes=args.story_image_max_output_bytes,
        max_total_bytes=args.story_image_max_total_bytes,
        timeout_seconds=args.story_image_timeout_seconds,
        image_timeout_seconds=args.story_image_generation_timeout_seconds,
        review_timeout_seconds=args.story_image_review_timeout_seconds,
        image_max_wire_bytes=args.story_image_max_wire_bytes,
        review_max_wire_bytes=args.story_image_review_max_wire_bytes,
        review_max_output_tokens=args.story_image_review_max_output_tokens if
            args.story_image_review_max_output_tokens is not None else (None if subscription else 512),
        reservation_microusd=args.story_image_reservation_microusd,
        total_reservation_microusd=args.story_image_total_reservation_microusd)


def _story_image_inputs(args, settings):
    from mira.bootstrap.story_image_provider import describe_story_images
    options = _story_image_options(args)
    declaration = describe_story_images(options=options, story_enabled=args.story)
    # A selected API branch receives settings only after all non-secret admission
    # fields are valid. Disabled, denied and subscription paths never access them.
    needs_api_settings = (declaration.get('missing_fields') == ['MIRA_SERVICES__OPENAI__API_KEY']
        and not declaration.get('invalid_fields'))
    return options, settings.services.openai if needs_api_settings else None


def _listening_limits(args):
    from mira.application.continuous_listening import ListeningLimits
    from mira.config.loader import ConfigurationError
    for name, maximum in (('listen_max_seconds', 290), ('listen_max_utterances', 32),
            ('listen_max_session_starts', 16), ('listen_max_total_starts', 100),
            ('listen_max_recognition_streams', 32)):
        value = getattr(args, name)
        if value is not None and (type(value) is not int or not 1 <= value <= maximum):
            raise ConfigurationError(f'{name} must be an integer within [1, {maximum}].')
    try:
        return ListeningLimits(max_seconds=args.listen_max_seconds,
            max_samples=None if args.listen_max_seconds is None else args.listen_max_seconds * 16_000,
            max_utterances=args.listen_max_utterances,
            max_streams_per_session=args.listen_max_session_starts,
            max_total_streams=args.listen_max_total_starts,
            max_recognition_streams=args.listen_max_recognition_streams)
    except ValueError:
        raise ConfigurationError('listening_local_limits_invalid') from None


def _generation_request_limit(args):
    if args.generation_requests is not None:
        return args.generation_requests
    return None if args.provider == 'chatgpt_subscription' else 20


def _session_turn_limit(args):
    if args.turns is not None:
        return args.turns
    if args.local_unlimited:
        return None
    return None if args.provider == 'chatgpt_subscription' else 20


def _story_image_declaration(args, settings):
    from mira.bootstrap.story_image_provider import describe_story_images, describe_story_image_readiness
    options, openai_settings = _story_image_inputs(args, settings)
    declaration = describe_story_images(options=options, story_enabled=args.story,
        openai_settings=openai_settings)
    readiness = describe_story_image_readiness(options=options,
        declaration=declaration, media_tools=not args.legacy_media_proposals)
    request_limit = _generation_request_limit(args)
    if readiness['state'] == 'enabled' and request_limit is not None and request_limit < 2:
        readiness = {**readiness, 'state': 'budget_exhausted', 'reason': 'dialogue_budget',
            'generation_tool': 'absent'}
    # Record explicit CLI choices, including omissions, without inferring consent
    # from model selection or mistaking local configuration for account access.
    return {**declaration, 'readiness': readiness, 'startup_requested': {
        'story': args.story, 'story_images': options.enabled,
        'image_data': options.authorize_data_to_openai,
        'subscription_usage': options.authorize_subscription_usage,
        'custom_brief': options.authorize_custom_brief,
        'api_spend': options.authorize_api_spend}}


def _story_image_factory(args, settings, credential_source=None):
    from mira.bootstrap.story_image_provider import create_story_image_factory, StoryImageConfigurationError
    options, openai_settings = _story_image_inputs(args, settings)
    try:
        return create_story_image_factory(options=options, story_enabled=args.story,
            openai_settings=openai_settings, credential_source=credential_source)
    except StoryImageConfigurationError as error:
        raise EntryError(str(error), stage='story_image_configuration', invalid_fields=error.fields) from None


def _subscription_credentials(args):
    from mira.adapters.auth.openai_codex import CodexOAuthCredentialSource
    return CodexOAuthCredentialSource(store_path=args.auth_store)


def _story_options(args):
    if args.story_db is None and args.story_scope is None and not args.authorize_story_persistence_and_recall:
        return None
    if (not args.story or args.story_db is None or not args.story_scope
            or not args.authorize_story_persistence_and_recall or not args.create_local_operator_pairing):
        raise EntryError('Persistent character history needs --story, an explicit database/scope, --authorize-story-persistence-and-recall, and local pairing.')
    if len(args.story_scope)>128 or any(ord(ch)<32 for ch in args.story_scope):
        raise EntryError('Select a short local character-history scope without control characters.')
    path=args.story_db.expanduser()
    if not path.is_absolute():
        raise EntryError('Character history database must use an explicit absolute path in a private folder.')
    return path


def _review_request_limits(args):
    if args.action_review_mode == 'luna_tools':
        return 0, 0
    from mira.bootstrap.development_review import resolve_review_request_limits
    from mira.bootstrap.development_usage import UsageProfile
    return resolve_review_request_limits(usage_profile=UsageProfile.APPLICATION,
        character_observations=args.story,
        input_max_request_bytes=args.input_review_max_bytes,
        output_max_request_bytes=args.output_review_max_bytes)


def _tier_declaration(args):
    from mira.adapters.generation.direct_codex_responses import (
        ResponsesRoute, resolve_direct_service_tier,
    )
    requested, wire = resolve_direct_service_tier(ResponsesRoute(args.provider), args.model,
        args.service_tier)
    return {'requested': requested, 'wire_value': wire, 'provider_confirmation': 'not_run',
        'subscription_fast_usage_multiplier': 2.5 if args.provider == 'chatgpt_subscription'
            and requested == 'fast' else None,
        'speed_multiplier_guaranteed': False}


def _report_service_tier(diagnostic):
    from mira.application.generation_diagnostics import SafeServiceTierDiagnostic
    if type(diagnostic) is not SafeServiceTierDiagnostic:
        return
    diagnostic.__post_init__()
    report = asdict(diagnostic)
    if diagnostic.reason == 'service_tier_rejected':
        report['recovery'] = 'Restart explicitly with --service-tier standard; no automatic retry was made.'
    elif diagnostic.requested_service_tier == 'fast' and diagnostic.outcome == 'completed' and not diagnostic.fast_confirmed:
        report['notice'] = 'Fast was requested; this response did not confirm priority service.'
    print(json.dumps({'service_tier': report}, sort_keys=True), file=sys.stderr)


def _generation(args, settings, credential_source=None):
    from mira.adapters.generation.direct_codex_responses import DirectCodexResponsesGenerationBackend, ResponsesRoute
    if args.provider == 'chatgpt_subscription':
        credentials = credential_source if credential_source is not None else _subscription_credentials(args)
    else:
        credentials = ApiCredentialSource(settings.services.openai.api_key)
    return DirectCodexResponsesGenerationBackend(route=ResponsesRoute(args.provider), model=args.model,
        credential_source=credentials, admitted=True, request_limit=_generation_request_limit(args),
        native_character_tools=args.action_review_mode == 'luna_tools',
        speech_enabled=args.voice, service_tier=args.service_tier, tier_observer=_report_service_tier)


def _prepare_frontend():
    from tools.live_dev import _prepare_frontend as build
    build()  # Existing local TypeScript bundle build, not a Codex process.


def _voice_factory(args, settings, limits):
    from types import SimpleNamespace
    import httpx
    from tools.live_voice import (_make_google_stt_tls, _load_google_credentials,
        _make_google_token_provider, _NETWORK_KEYS)
    from mira.bootstrap.development_voice import create_development_voice_factory
    from mira.bootstrap.providers import GoogleVoiceProviders
    # Snapshot only the current standard network inputs for the existing verifying
    # TLS bridge. No historical Codex runtime/fingerprint or network change is used.
    network = SimpleNamespace(environment={key: os.environ[key] for key in _NETWORK_KEYS if key in os.environ})
    tls = _make_google_stt_tls(network)
    credentials = _load_google_credentials(_private_file(args.adc_file, 'Google ADC file'))
    client = httpx.AsyncClient(trust_env=True, follow_redirects=False)
    try:
        make = create_development_voice_factory(speech_settings=settings.services.speech,
            credentials=credentials, token_provider=_make_google_token_provider(credentials), authorized=True,
            limits=limits, http_client=client, stt_ssl_channel_credentials=tls)
    except BaseException:
        from tools.live_voice import _close_http_client
        _close_http_client(client)
        raise
    def owned():
        bundle = make()
        async def close():
            try:
                await bundle.close()
            finally:
                await client.aclose()
        # Preserve both new continuous and shared-budget ports across ownership wrapping.
        return GoogleVoiceProviders(bundle.speech_recognition, bundle.speech_synthesis, close,
            continuous_speech_recognition=bundle.continuous_speech_recognition,
            stt_request_budget=bundle.stt_request_budget)
    return owned, client


def _serve(args, settings, voice_limits, memory_options=None, conversation_options=None):
    from mira.bootstrap.direct_provider_app import create_direct_provider_app
    from mira.bootstrap.development_usage import UsageProfile
    from tools.live_voice import _run_uvicorn, _close_http_client
    from tools.private_device_access import resolve_serve_access, create_device_pairing, run_private_server
    if not args.authorize_provider_data:
        raise EntryError('Serve requires explicit dialogue transmission consent for the chosen OpenAI provider' +
            (' and JEV.' if args.action_review_mode == 'legacy_jev' else '.'))
    if args.provider == 'openai_api' and not args.authorize_api_billing:
        raise EntryError('Official API mode requires explicit API-billing acknowledgement; route will not switch.')
    if args.voice and not args.authorize_google_voice_data_and_spend:
        raise EntryError('Voice requires separate Google audio/text transmission and spend consent.')
    if memory_options is not None and (not args.authorize_memory_to_selected_provider_and_jev
            or not args.create_local_operator_pairing):
        raise EntryError('Memory serving requires separate selected-provider transmission consent and pairing.')
    if memory_options is not None and args.voice and not args.authorize_memory_derived_speech_to_google:
        raise EntryError('Stored-memory voice requires separate Google TTS transmission consent.')
    image_declaration = _story_image_declaration(args, settings)
    if image_declaration['status'] == 'unavailable':
        raise EntryError('Story images unavailable; review the named configuration fields. No values were printed.',
            stage='story_image_configuration', invalid_fields=tuple(
                image_declaration['missing_fields'] + image_declaration['invalid_fields']))
    access = resolve_serve_access(args)
    if access is not None:
        settings = settings.model_copy(update={"http": settings.http.model_copy(update=access.http_settings())})
    subscription_credentials = (_subscription_credentials(args)
        if image_declaration.get('provider') == 'chatgpt_subscription' else None)
    story_image_factory = _story_image_factory(args, settings, subscription_credentials)
    _prepare_frontend()
    generation = (_generation(args, settings, subscription_credentials)
        if subscription_credentials is not None and args.provider == 'chatgpt_subscription'
        else _generation(args, settings))
    voice_factory = None; client = None
    try:
        if args.voice:
            voice_factory, client = _voice_factory(args, settings, voice_limits)
        review = None
        if args.action_review_mode == 'legacy_jev':
            from mira.bootstrap.development_app import jev_transport_from_settings
            review = jev_transport_from_settings(settings)
        pairing = None; pairing_path = None; device_pairing_paths = ()
        if access is not None:
            pairing, device_pairing_paths = create_device_pairing(access, checkout_root=ROOT)
        story_database=_story_options(args)
        if memory_options is not None or story_database is not None or conversation_options is not None:
            from tools.operator_pairing_file import create_pairing_material, PairingFileError
            from mira.entrypoints.http.operator_pairing import OperatorPairing
            try:
                pairing_parent=(memory_options.database.parent if memory_options is not None else story_database.parent
                    if story_database is not None else conversation_options.database.parent)
                material = create_pairing_material(pairing_parent, checkout_root=ROOT)
                pairing = OperatorPairing(material.code, tuple(settings.http.allowed_origins))
                pairing_path = material.path
                del material
            except (PairingFileError, ValueError):
                raise EntryError('Operator pairing setup failed; no memory reader or server was started.') from None
        character_factory = None
        character_binding_factory = None
        if args.story:
            from mira.bootstrap.character_story import ephemeral_character_factory,persistent_character_factory
            from mira.bootstrap.character_assets import renderer_readiness
            readiness = renderer_readiness(args.character_renderer)
            if story_database is not None:
                character_binding_factory=persistent_character_factory(database=story_database,
                    scope_id=args.story_scope,authorized=args.authorize_story_persistence_and_recall,
                    readiness=readiness)
            else:
                character_factory = ephemeral_character_factory(readiness=readiness)
        app = create_direct_provider_app(generation=generation, model=args.model, route=args.provider,
            **({'tool_generation': generation} if not args.legacy_media_proposals else {}),
            settings=settings, input_transport=review, output_transport=review, authorized=True,
            action_review_mode=args.action_review_mode,
            api_billing_authorized=args.authorize_api_billing, usage_profile=UsageProfile.APPLICATION,
            generation_request_limit=_generation_request_limit(args), session_turn_limit=_session_turn_limit(args),
            local_listening_limits=_listening_limits(args),
            input_request_limit=args.input_jev_requests, output_request_limit=args.output_jev_requests,
            boundary_request_limit=args.boundary_max_requests,
            boundary_timeout_seconds=args.boundary_timeout_seconds,
            input_timeout_seconds=args.review_timeout_seconds, output_timeout_seconds=args.review_timeout_seconds,
            input_max_request_bytes=args.input_review_max_bytes,
            output_max_request_bytes=args.output_review_max_bytes,
            voice_factory=voice_factory, voice_usage_limits=voice_limits, voice_required=args.voice,
            client_silence_ms=args.listen_silence_ms,
            natural_grace_seconds=args.listen_grace_seconds,
            drain_timeout_seconds=args.listen_drain_seconds,
            max_recognition_streams=args.listen_max_recognition_streams,
            **({'character_renderer':args.character_renderer} if args.character_renderer!='static-pixi' else {}),
            **({'conversation_options':conversation_options} if conversation_options is not None else {}),
            **({'operator_pairing':pairing, 'loopback_port':access.loopback_port} if access is not None else {}),
            **({'operator_pairing':pairing} if conversation_options is not None and memory_options is None and character_binding_factory is None else {}),
            **({'story_image_factory': story_image_factory} if story_image_factory is not None else {}),
            **({'character_factory': character_factory} if character_factory is not None else {}),
            **({'character_binding_factory':character_binding_factory,
                **({'operator_pairing':pairing} if memory_options is None else {})}
               if character_binding_factory is not None else {}),
            **({'memory_options': memory_options, 'operator_pairing': pairing,
                'authorize_memory_to_direct_provider_and_jev': args.authorize_memory_to_selected_provider_and_jev,
                'authorize_memory_derived_speech_to_google': args.authorize_memory_derived_speech_to_google,
                'authorize_local_memory_management': args.authorize_local_memory_management}
               if memory_options is not None else {}))
        service_origin = access.policy.origin if access is not None else 'http://127.0.0.1:'+str(args.port)
        print('Starting MIRA direct provider '+args.provider+' at '+service_origin+
            '. Codex CLI is not required. Request/duration limits are per-process technical limits, not dollar caps. '
            'Microphone starts only after a user gesture and browser permission.', flush=True)
        print(json.dumps({'service_tier': _tier_declaration(args)}, sort_keys=True), flush=True)
        print(json.dumps({'story_images': _story_image_declaration(args, settings)}, sort_keys=True), flush=True)
        if args.action_review_mode == 'legacy_jev':
            print('Explicit legacy JEV request ceilings: input='+str(args.input_jev_requests)+
                ', optional events='+str(args.output_jev_requests)+', caption boundaries='+str(args.boundary_max_requests)+
                ', total='+str(args.input_jev_requests+args.output_jev_requests+args.boundary_max_requests)+'.', flush=True)
        else:
            print('Action mode: luna_tools. JEV requests: 0. Caption boundaries are deterministic; '
                'speech cues remain whole and Google call count is unchanged.', flush=True)
        if memory_options is not None or story_database is not None or conversation_options is not None:
            print('Pair locally with the one-use code from this private file: '+str(pairing_path), flush=True)
            print('Pairing expires after five minutes. The code is never printed or put in a URL. '
                'The boundary does not protect against access to your OS account/browser. '
                'Selected manually stored evidence may be sent to '+', '.join(_memory_recipients(args.provider, args.voice, args.action_review_mode))+'. '+
                ('Accepted conversations will be recorded locally under separate consent.' if conversation_options is not None else 'Automatic recording remains off.'), flush=True)
            if args.authorize_local_memory_management:
                print('Local memory management is enabled after pairing; each save/correction/soft-forget/restore needs explicit confirmation.', flush=True)
        if access is not None:
            if access.trusted_no_pairing:
                print('TRUSTED PRIVATE NETWORK / NO PAIRING: anyone who can reach this origin may use enabled chat, voice and image quotas. '
                    'No code files are created. Up to 16 independent temporary browser sessions (resource limit); access expires after eight hours or restart. '
                    'Refresh starts a new conversation for this browser only.', flush=True)
            else:
                print('Private device access: open the same exact origin on phone and computer. '
                    'Use a different one-use code file for each device; never put a code in a URL or chat. '
                    'Codes expire after five minutes; browser access expires after eight hours. '
                    'Each device has an independent ephemeral session.', flush=True)
            for index, path in enumerate(device_pairing_paths, 1):
                print('Device '+str(index)+' private pairing file: '+str(path), flush=True)
            if access.loopback_port is not None:
                print('Local computer: http://127.0.0.1:'+str(args.port)+' (existing voice option preserved). LAN devices: '+access.policy.origin+' (text-only).', flush=True)
            if access.policy.scheme == 'http':
                print('Private HTTP is plaintext and text-only. Use only a trusted private network.', flush=True)
            else:
                print('Both devices must already trust the supplied HTTPS certificate. '
                    'Certificate trust, DNS and phone microphone access have not been verified.', flush=True)
            run_private_server(app, access)
        else:
            _run_uvicorn(app, port=args.port)
    finally:
        _close_http_client(client)


def main(argv=None) -> int:
    values=list(sys.argv[1:] if argv is None else argv)
    if not values:
        print(json.dumps({'status':'unarmed','codex_cli_required':False,'network':'not_run'}));return 0
    if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
    args=_parser().parse_args(values)
    try:
        input_review_bytes,output_review_bytes=_review_request_limits(args)
        conversation_options=_conversation_options(args)
        memory_options=_memory_options(args)
        story_database=_story_options(args)
        settings,voice_limits=_load(args)
        if args.command=='check':
            result={'status':'configuration_declared','live_ready':False,'provider':args.provider,
                'model':args.model,'codex_cli_required':False,'auth_store':'not_loaded','inference':'not_run',
                'action_review_mode':args.action_review_mode,
                'api_billing_required_for_serve':args.provider=='openai_api','voice_declared':args.voice,
                'generation_request_limit':_generation_request_limit(args),'turn_limit':_session_turn_limit(args),
                'generation_count_policy':'unlimited' if _generation_request_limit(args) is None else 'finite',
                'text_turn_policy':'unlimited' if _session_turn_limit(args) is None else 'finite',
                'local_interaction_policy':'unlimited' if all(value is None for value in (args.listen_max_seconds, args.listen_max_utterances, args.listen_max_session_starts, args.listen_max_total_starts, args.listen_max_recognition_streams)) else 'finite',
                'limits_are_dollar_caps':False}
            from tools.private_device_access import device_options
            access = device_options(args)
            from tools.private_device_access import default_lan_requested
            result['device_access'] = access.declaration() if access is not None else ({'enabled': True,
                'access_mode': 'default_trusted_lan', 'address_selection': 'on_serve',
                'max_device_sessions': 16, 'pairing_required': False, 'listener_started': False}
                if default_lan_requested(args) else {'enabled': False, 'listener_started': False})
            result['service_tier'] = _tier_declaration(args)
            result['media_tools'] = {'enabled': not args.legacy_media_proposals,
                'max_tools_per_turn': 1, 'max_model_requests_per_tool_turn': 2,
                'normal_chat_model_requests': 1, 'automatic_retries': 0,
                'request_limit_unchanged': _generation_request_limit(args),
                'provider_tool_support': 'not_live_verified'}
            result['story_images'] = _story_image_declaration(args, settings)
            legacy_jev = args.action_review_mode == 'legacy_jev'
            result['review_request_limits']={'enabled':legacy_jev,
                'input_max_request_bytes':input_review_bytes,
                'output_max_request_bytes':output_review_bytes,'limits_are_dollar_caps':False,
                'input_max_requests':args.input_jev_requests if legacy_jev else 0,
                'output_max_requests':args.output_jev_requests if legacy_jev else 0,
                'boundary_max_requests':args.boundary_max_requests if legacy_jev else 0,
                'total_max_requests':args.input_jev_requests+args.output_jev_requests+args.boundary_max_requests if legacy_jev else 0}
            result['semantic_chunking']={'enabled':not legacy_jev or args.boundary_max_requests>0,
                'planner':'legacy_jev' if legacy_jev else 'deterministic',
                'boundary_max_requests':args.boundary_max_requests if legacy_jev else 0,
                'timeout_seconds':args.boundary_timeout_seconds if legacy_jev else None,
                'eligible_content':'text_only_complete_candidates','max_caption_chunks':4,
                'max_original_codepoints':4096,'google_request_increase':0,
                'fallback':'whole_unissued_tail' if legacy_jev else 'whole_original_cue',
                'speech_candidates':'whole_original_cue',
                'model_token_streaming':False,'provider_quality_validation':'not_run'}
            result['character_renderer']=args.character_renderer
            if args.voice:
                result['continuous_listening']={
                    'client_silence_ms':args.listen_silence_ms,
                    'natural_grace_seconds':args.listen_grace_seconds,
                    'drain_timeout_seconds':args.listen_drain_seconds,
                    'max_recognition_streams_per_lease':args.listen_max_recognition_streams,
                    'max_utterances_per_lease':args.listen_max_utterances,
                    'max_session_starts':args.listen_max_session_starts,
                    'max_total_starts':args.listen_max_total_starts,
                    'stt_requests_per_process':args.stt_requests,
                    'max_lease_seconds':args.listen_max_seconds if args.stt_max_seconds >= 1 else 0,
                    'max_recognition_rpc_seconds':min(120,int(args.stt_max_seconds)),
                    'grace_is_heuristic':True,'microphone_requires_user_start':True,
                    'limits_are_dollar_caps':False,'provider_quality_validation':'not_run'}
                result['tts_selection']={'model':'gemini-3.8-flash-tts',
                    'voice':settings.services.speech.tts_voice,
                    'language_mode':'model_auto_detection','configured_language_applied':False,
                    'voice_listening_validation':'not_run'}
            if args.story:
                from mira.bootstrap.character_assets import renderer_readiness
                readiness = renderer_readiness(args.character_renderer)
                result['character_story']={'configured':True,'authored_fiction':True,
                    'persistent_history':story_database is not None,'database_opened':False,
                    'pairing_file_created':False,'automatic_user_recording':False,
                    'asset_readiness':'checked_at_presentation','catalog_revision':readiness.revision,
                    'visual_acceptance':'pending','real_model_validation':'not_run'}
            if memory_options is not None:
                result['memory_recall']={'configured':True,'recipients':_memory_recipients(args.provider,args.voice,args.action_review_mode),
                    'transmission_authorized':True,'database_opened':False,'pairing_file_created':False,
                    'operator_pairing_required':True,'automatic_recording':False,
                    'local_management_requested':args.authorize_local_memory_management}
            if conversation_options is not None:
                result['conversation_archive']={'configured':True,'persistence_authorized':True,
                    'database_opened':False,'pairing_file_created':False,'operator_pairing_required':True,
                    'recall_selected':conversation_options.recall_session_id is not None,
                    'recall_authorized':conversation_options.authorize_recall_to_provider_and_jev,
                    'recipients':_memory_recipients(args.provider,args.voice,args.action_review_mode),
                    'local_management_requested':conversation_options.authorize_management}
            print(json.dumps(result,sort_keys=True))
            return 2 if result['story_images']['status'] == 'unavailable' else 0
        _serve(args,settings,voice_limits,memory_options,conversation_options);return 0
    except (EntryError, ValueError, OSError) as error:
        from tools.private_device_access import PrivateDeviceError
        details = {}
        if isinstance(error, PrivateDeviceError):
            message = str(error)
        elif type(error) is EntryError:
            message=str(error)
            if error.stage is not None:
                details['stage'] = error.stage
            if error.invalid_fields:
                details['invalid_fields'] = list(error.invalid_fields)
                if len(error.invalid_fields) == 1:
                    details['invalid_field'] = error.invalid_fields[0]
        else:
            message='Direct provider configuration or resources could not be prepared; no values were printed.'
        print(json.dumps({'status':'blocked','message':message,'live_ready':False,**details}),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
