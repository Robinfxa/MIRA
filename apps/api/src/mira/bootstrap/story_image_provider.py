"""Explicit optional image composition. Configuration and factories make no external calls.

The API route receives OpenAISettings only from the existing loader. Subscription
receives an opaque MIRA credential source, never an API key or automatic fallback.
Neither route discovers credentials or accepts private memory/arbitrary briefs.
Local reservations bound admitted jobs, not provider charges or subscription quota.
"""
from dataclasses import dataclass
import math
import re

from pydantic import SecretStr

from mira.application.ports.media import ImageOperationAdmissionDenied
from mira.domain.story_images import SQUARE_OUTPUT_POLICY, SUBSCRIPTION_OUTPUT_POLICY, image_output_dimensions


class StoryImageConfigurationError(ValueError):
    def __init__(self, fields: tuple[str, ...]):
        self.fields = fields
        super().__init__('Story images unavailable; review the named configuration fields. No values were printed.')


@dataclass(frozen=True, slots=True)
class StoryImageOptions:
    enabled: bool = False
    provider: str | None = None
    image_model: str | None = None
    review_model: str | None = None
    quality: str | None = None
    authorize_data_to_openai: bool = False
    authorize_api_spend: bool = False
    authorize_subscription_usage: bool = False
    max_attempts: int = 1
    max_output_bytes: int = 8_388_608
    max_total_bytes: int = 8_388_608
    timeout_seconds: float = 120.0
    image_timeout_seconds: float = 90.0
    review_timeout_seconds: float = 45.0
    image_max_wire_bytes: int = 12_000_000
    review_max_wire_bytes: int = 65_536
    review_max_output_tokens: int | None = 512
    reservation_microusd: int | None = None
    total_reservation_microusd: int | None = None
    authorize_custom_brief: bool = False


def _issues(options: StoryImageOptions, story_enabled: bool):
    missing, invalid = [], []
    if type(options.enabled) is not bool:
        return (), ('story_images',)
    if type(options.authorize_custom_brief) is not bool:
        return (), ('authorize_story_image_custom_brief',)
    if not options.enabled:
        if options.authorize_custom_brief:
            return ('story_images',), ('authorize_story_image_custom_brief',)
        return (), ()
    subscription = options.provider == 'chatgpt_subscription'
    usage_consent = ((options.authorize_subscription_usage, 'authorize_story_image_subscription_usage')
        if subscription else (options.authorize_api_spend, 'authorize_story_image_api_spend'))
    for value, field in ((story_enabled, 'story'),
            (options.authorize_data_to_openai, 'authorize_story_image_data_to_openai'), usage_consent):
        if value is not True:
            (missing if value is False else invalid).append(field)
    for value, field, valid in (
        (options.provider, 'story_image_provider', lambda v: v in ('openai_api', 'chatgpt_subscription')),
        (options.image_model, 'story_image_model', lambda v: type(v) is str
            and (v == 'gpt-image-2' if subscription
                else re.fullmatch(r'gpt-image-[A-Za-z0-9._-]{1,118}', v))),
        (options.review_model, 'story_image_review_model', lambda v: type(v) is str
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', v)),
        (options.quality, 'story_image_quality', lambda v: v == 'auto' if subscription
            else v in ('low', 'medium', 'high')),
    ):
        if value is None or value == '':
            missing.append(field)
        elif not valid(value):
            invalid.append(field)
    for value, field, lower, upper in (
        (options.max_attempts, 'story_image_max_attempts', 1, 4),
        (options.max_output_bytes, 'story_image_max_output_bytes', 1024, 8_388_608),
        (options.max_total_bytes, 'story_image_max_total_bytes', 1024, 33_554_432),
        (options.image_max_wire_bytes, 'story_image_max_wire_bytes', 1024, 12_000_000),
        (options.review_max_wire_bytes, 'story_image_review_max_wire_bytes', 1024, 65_536),
    ):
        if value is None:
            missing.append(field)
        elif type(value) is not int or not lower <= value <= upper:
            invalid.append(field)
    for value, field, lower, upper in (
        (options.review_max_output_tokens, 'story_image_review_max_output_tokens', 128, 512),
        (options.reservation_microusd, 'story_image_reservation_microusd', 1, 1_000_000_000),
        (options.total_reservation_microusd, 'story_image_total_reservation_microusd', 1, 1_000_000_000),
    ):
        if subscription:
            if value is not None:
                invalid.append(field)
        elif value is None:
            missing.append(field)
        elif type(value) is not int or not lower <= value <= upper:
            invalid.append(field)
    if (type(options.max_output_bytes) is int and type(options.max_total_bytes) is int
            and options.max_total_bytes < options.max_output_bytes):
        invalid.append('story_image_max_total_bytes')
    if (type(options.reservation_microusd) is int and type(options.total_reservation_microusd) is int
            and options.total_reservation_microusd < options.reservation_microusd):
        invalid.append('story_image_total_reservation_microusd')
    for value, field in (
        (options.timeout_seconds, 'story_image_timeout_seconds'),
        (options.image_timeout_seconds, 'story_image_generation_timeout_seconds'),
        (options.review_timeout_seconds, 'story_image_review_timeout_seconds'),
    ):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 120:
            invalid.append(field)
    return tuple(dict.fromkeys(missing)), tuple(dict.fromkeys(invalid))


def describe_story_images(*, options: StoryImageOptions, story_enabled: bool,
                          openai_settings=None) -> dict:
    """Declaration only. No credential sources, secret unwrapping, clients or inference."""
    missing, invalid = _issues(options, story_enabled)
    base = {'status': 'disabled', 'live_verified': False, 'inference': 'not_run'}
    if not options.enabled and not invalid:
        return base
    subscription = options.provider == 'chatgpt_subscription'
    if not subscription and not missing and not invalid:
        key = None if openai_settings is None else openai_settings.api_key
        if key is None:
            missing = ('MIRA_SERVICES__OPENAI__API_KEY',)
        elif type(key) is not SecretStr:
            invalid = ('MIRA_SERVICES__OPENAI__API_KEY',)
    if missing or invalid:
        return {**base, 'status': 'unavailable', 'missing_fields': list(missing),
            'invalid_fields': list(invalid)}
    return {**base, 'status': 'configured_not_live_verified', 'provider': options.provider,
        'image_model': options.image_model, 'review_model': options.review_model,
        'quality': options.quality, 'size': '1024x1024', 'format': 'opaque_png',
        'accepted_output_sizes': [f'{w}x{h}' for w, h in image_output_dimensions(
            SUBSCRIPTION_OUTPUT_POLICY if subscription else SQUARE_OUTPUT_POLICY)],
        'output_dimension_policy': SUBSCRIPTION_OUTPUT_POLICY if subscription else SQUARE_OUTPUT_POLICY,
        'recipients': (['OpenAI Codex Images internal compatibility endpoint',
            'OpenAI Codex Responses internal pixel review'] if subscription else
            ['OpenAI Images API', 'OpenAI Responses API pixel review']),
        'data_scope': ('released_fiction_and_bounded_custom_brief' if options.authorize_custom_brief
                       else 'released_fiction_catalog_only'), 'private_memory_transmitted': False,
        'actual_user_brief_supported': options.authorize_custom_brief,
        'custom_brief_max_characters': 600 if options.authorize_custom_brief else 0,
        'custom_brief_semantic_scope': ('review_required_not_proven_by_string_checks'
            if options.authorize_custom_brief else 'unavailable'),
        'reference_images_supported': False,
        'max_attempts_per_process': options.max_attempts,
        'max_reviews_per_process': options.max_attempts, 'max_in_flight_jobs': 1,
        'automatic_retries': 0, 'automatic_fallback': False,
        'attempt_unit': 'admitted_job_before_first_provider_await',
        'max_output_bytes_per_image': options.max_output_bytes,
        'max_reserved_output_bytes_per_process': options.max_total_bytes,
        'generation_max_wire_bytes': options.image_max_wire_bytes,
        'review_max_wire_bytes': options.review_max_wire_bytes,
        'job_timeout_seconds': options.timeout_seconds,
        'generation_timeout_seconds': options.image_timeout_seconds,
        'review_timeout_seconds': options.review_timeout_seconds,
        'review_max_output_tokens': options.review_max_output_tokens,
        'review_remote_token_cap': 'unavailable' if subscription else 'requested',
        'review_local_max_output_bytes': 8192 if subscription else None,
        'planning_reservation_microusd_per_job': options.reservation_microusd,
        'planning_reservation_microusd_per_process': options.total_reservation_microusd,
        'planning_reservation_status': 'not_applicable' if subscription else 'local_planning_only',
        'planning_reservation_is_provider_limit': False, 'limits_are_dollar_caps': False,
        'limits_are_plan_caps': False,
        'subscription_quota_consumption': 'unknown' if subscription else 'not_applicable',
        'subscription_entitlement': 'not_checked' if subscription else 'not_applicable',
        'compatibility': 'internal_unverified' if subscription else 'official_api_unverified',
        'failed_or_unknown_jobs_refunded': False, 'account_access': 'not_checked',
        'credential_value_validated': False}


def describe_story_image_readiness(*, options, declaration, media_tools=True):
    """Operator declaration for custom-brief tools, not a provider qualification probe."""
    value = {'state': 'disabled', 'reason': 'feature_disabled', 'scope': 'configuration_only',
        'generation_tool': 'absent', 'account_access': 'not_checked',
        'provider_observation': 'not_observed', 'missing_consents': []}
    if not options.enabled:
        return value
    consents = ((options.authorize_data_to_openai, 'image_data'),
        (options.authorize_subscription_usage if options.provider == 'chatgpt_subscription'
         else options.authorize_api_spend, 'subscription_usage' if options.provider == 'chatgpt_subscription'
         else 'api_spend'))
    missing = [name for allowed, name in consents if allowed is not True]
    if media_tools and options.authorize_custom_brief is not True:
        missing.append('custom_brief')
    if missing:
        return {**value, 'state': 'missing_consent',
            'reason': 'custom_brief_consent' if missing == ['custom_brief'] else 'consent_required',
            'missing_consents': missing}
    if declaration['status'] != 'configured_not_live_verified':
        return {**value, 'state': 'configuration_unavailable', 'reason': 'configuration_required'}
    return {**value, 'state': 'enabled' if media_tools else 'legacy_catalog_only',
        'reason': 'configured' if media_tools else 'legacy_mode',
        'generation_tool': 'configured' if media_tools else 'absent',
        'max_jobs_per_process': options.max_attempts, 'max_reviews_per_process': options.max_attempts,
        'automatic_retries': 0}


class _ProcessImageAdmission:
    """One application process, one entire job in flight, at most four admitted jobs.

    reserve/release run synchronously on the application's single event loop. No
    lock spans an await. Reserved bytes and planning amounts are conservative and
    never refunded, even when failure occurs before the first HTTP request.
    """
    def __init__(self, options: StoryImageOptions):
        self.options = options
        self.active_request = None
        self.attempts = 0
        self.reserved_bytes = 0
        self.reserved_microusd = 0
        self.request_ids = set()

    def readiness(self):
        o = self.options
        remaining = min(o.max_attempts - self.attempts,
            (o.max_total_bytes - self.reserved_bytes) // o.max_output_bytes)
        if o.provider != 'chatgpt_subscription':
            remaining = min(remaining, (o.total_reservation_microusd - self.reserved_microusd)
                // o.reservation_microusd)
        remaining = max(0, remaining)
        return ('busy' if self.active_request is not None else
            'budget_exhausted' if not remaining else 'enabled', remaining)

    def reserve(self, request):
        if self.active_request is not None:
            raise ImageOperationAdmissionDenied('busy')
        o = self.options
        reservation = 0 if o.provider == 'chatgpt_subscription' else o.reservation_microusd
        total_reservation = 0 if o.provider == 'chatgpt_subscription' else o.total_reservation_microusd
        if (type(request.request_id) is not str or not request.request_id
                or request.request_id in self.request_ids
                or type(request.max_output_bytes) is not int
                or not 1 <= request.max_output_bytes <= o.max_output_bytes):
            raise ValueError('image_process_request_invalid')
        if (self.attempts >= o.max_attempts
                or self.reserved_bytes + o.max_output_bytes > o.max_total_bytes
                or self.reserved_microusd + reservation > total_reservation):
            raise ImageOperationAdmissionDenied('budget')
        self.attempts += 1
        self.reserved_bytes += o.max_output_bytes
        self.reserved_microusd += reservation
        self.request_ids.add(request.request_id)
        self.active_request = request.request_id

    def release(self, request_id):
        if self.active_request == request_id:
            self.active_request = None


def create_story_image_factory(*, options: StoryImageOptions, story_enabled: bool,
                               openai_settings=None, credential_source=None,
                               image_transport=None, review_transport=None):
    declaration = describe_story_images(options=options, story_enabled=story_enabled,
        openai_settings=openai_settings)
    if declaration['status'] == 'disabled':
        return None
    if declaration['status'] != 'configured_not_live_verified':
        raise StoryImageConfigurationError(tuple(declaration['missing_fields'] + declaration['invalid_fields']))
    subscription = options.provider == 'chatgpt_subscription'
    if subscription and (credential_source is None
            or not callable(getattr(credential_source, 'get_credentials', None))):
        raise StoryImageConfigurationError(('story_image_subscription_credentials',))
    # Imports and side-effect-free adapter construction follow complete admission.
    # Credential retrieval/HTTP client allocation only happen during a user operation.
    try:
        from mira.adapters.media.png_decoder import PillowPngDecoder
        from mira.application.story_images import StoryImageAdmission, StoryImageRuntime
        if subscription:
            from mira.adapters.media.subscription_images import SubscriptionImageBackend
            from mira.adapters.media.subscription_vision_review import (
                SubscriptionVisionReviewBackend, SubscriptionVisionOptions,
            )
        else:
            from mira.adapters.media.openai_images import OpenAIImageBackend, OpenAIImageOptions
            from mira.adapters.media.openai_vision_review import OpenAIVisionReviewBackend, OpenAIVisionOptions
    except ImportError:
        raise StoryImageConfigurationError(('story_image_runtime_dependencies',)) from None
    # Explicit in-process injection supports bounded offline/probe consumers. It
    # cannot change endpoints and is never inferred from environment or CLI input.
    image_http = {} if image_transport is None else {'transport': image_transport}
    review_http = {} if review_transport is None else {'transport': review_transport}
    try:
        if subscription:
            image_backend = SubscriptionImageBackend(credential_source=credential_source,
                timeout_seconds=options.image_timeout_seconds, max_wire_bytes=options.image_max_wire_bytes,
                **image_http)
            vision_backend = SubscriptionVisionReviewBackend(credential_source=credential_source,
                options=SubscriptionVisionOptions(model=options.review_model),
                timeout_seconds=options.review_timeout_seconds, max_wire_bytes=options.review_max_wire_bytes,
                **review_http)
        else:
            image_backend = OpenAIImageBackend(api_key=openai_settings.api_key,
                options=OpenAIImageOptions(model=options.image_model, quality=options.quality),
                timeout_seconds=options.image_timeout_seconds, max_wire_bytes=options.image_max_wire_bytes,
                **image_http)
            vision_backend = OpenAIVisionReviewBackend(api_key=openai_settings.api_key,
                options=OpenAIVisionOptions(model=options.review_model,
                    max_output_tokens=options.review_max_output_tokens),
                timeout_seconds=options.review_timeout_seconds, max_wire_bytes=options.review_max_wire_bytes,
                **review_http)
    except ValueError:
        field = 'story_image_subscription_configuration' if subscription else 'MIRA_SERVICES__OPENAI__API_KEY'
        raise StoryImageConfigurationError((field,)) from None
    output_policy = SUBSCRIPTION_OUTPUT_POLICY if subscription else SQUARE_OUTPUT_POLICY
    decoder = PillowPngDecoder(max_bytes=options.max_output_bytes, output_dimension_policy=output_policy)
    admission = StoryImageAdmission(reference=('explicit-subscription-fiction-only-v1' if subscription
        else 'explicit-official-api-fiction-only-v1'),
        authorized_fiction_only=True, max_attempts=options.max_attempts,
        max_output_bytes=options.max_output_bytes, max_total_bytes=options.max_total_bytes,
        max_cost_microunits=0 if subscription else options.total_reservation_microusd,
        cost_per_attempt_microunits=0 if subscription else options.reservation_microusd,
        timeout_seconds=options.timeout_seconds,
        authorized_custom_brief=options.authorize_custom_brief, output_dimension_policy=output_policy)
    process_admission = _ProcessImageAdmission(options)

    def create(_state):
        # Runtime/session artifacts are never shared. This one gate survives all
        # session creation and Close calls until this application process exits.
        return StoryImageRuntime(image_backend, vision_backend, decoder, admission,
            operation_admission=process_admission)
    return create
