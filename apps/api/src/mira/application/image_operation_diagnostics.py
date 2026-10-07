"""Closed, payload-free image operation observations; never admission authority."""
from dataclasses import dataclass, replace

STAGES = ('unobserved', 'admission', 'generation', 'generated_validation', 'png_decode',
          'canonical_validation', 'review_admission', 'pixel_review', 'review_validation', 'review_passed', 'qualified')
REASONS = ('none', 'unknown', 'timeout', 'image_generation_invalid', 'image_decode_invalid',
    'image_review_invalid', 'image_png_input', 'image_png_container', 'image_png_animation',
    'image_png_header', 'image_png_dimensions', 'image_png_crc', 'image_png_trailing',
    'image_png_missing_pixels', 'image_png_truncated', 'image_png_deflate_trailing',
    'image_png_deflate_limit', 'image_png_deflate_incomplete', 'image_png_deflate_invalid',
    'image_png_decoder_tolerance', 'image_png_mode', 'image_png_transparency',
    'image_png_output_limit', 'image_png_decode', 'image_http_timeout', 'image_http_transport',
    'image_http_status', 'image_http_content_type', 'image_http_encoding',
    'image_http_content_length', 'image_http_wire_limit', 'image_http_decoded_limit',
    'image_generation_envelope', 'image_generation_created', 'image_generation_incomplete',
    'image_generation_count', 'image_generation_resource', 'image_base64_limit',
    'image_base64_invalid', 'image_generation_bytes', 'image_json_invalid',
    'subscription_review_wire_limit', 'subscription_review_content_length',
    'subscription_review_event', 'subscription_review_event_limit',
    'subscription_review_output_limit', 'subscription_review_decoded_limit',
    'subscription_review_line_limit',
    'subscription_review_item', 'subscription_review_terminal',
    'subscription_review_incomplete', 'subscription_review_artifact_binding',
    'subscription_review_not_canonical', 'subscription_review_request_limit',
    'subscription_review_timeout', 'subscription_review_response',
    'subscription_review_transport', 'subscription_review_observation_binding',
    'subscription_review_checks', 'subscription_review_http_status',
    'subscription_review_content_type', 'subscription_review_encoding')
EXCEPTIONS = ('none', 'timeout', 'image_provider_error', 'value_error', 'type_error',
              'import_error', 'other')


@dataclass(frozen=True, slots=True)
class SafeImageOperationDiagnostic:
    operation_stage: str = 'unobserved'
    failure_reason: str = 'none'
    failure_exception: str = 'none'
    png_width: int | None = None
    png_height: int | None = None
    png_dimensions: str = 'unobserved'
    png_mode: str = 'unobserved'
    png_bit_depth: str = 'unobserved'
    png_alpha: str = 'unobserved'

    def __post_init__(self):
        for value, allowed in ((self.operation_stage, STAGES), (self.failure_reason, REASONS),
                (self.failure_exception, EXCEPTIONS),
                (self.png_dimensions, ('unobserved', 'bounded', 'invalid', 'over_limit')),
                (self.png_mode, ('unobserved', 'gray', 'rgb', 'indexed', 'gray_alpha', 'rgba', 'unknown')),
                (self.png_bit_depth, ('unobserved', '1', '2', '4', '8', '16', 'unknown')),
                (self.png_alpha, ('unobserved', 'channel', 'undetermined', 'opaque', 'nonopaque'))):
            if type(value) is not str or value not in allowed:
                raise ValueError('invalid image operation diagnostic')
        for value in (self.png_width, self.png_height):
            if value is not None and (type(value) is not int or not 1 <= value <= 16384):
                raise ValueError('invalid image diagnostic dimensions')
        if ((self.png_width is not None or self.png_height is not None)
                != (self.png_dimensions == 'bounded')):
            raise ValueError('invalid image diagnostic dimensions')
        if self.png_dimensions == 'bounded' and (self.png_width is None or self.png_height is None):
            raise ValueError('invalid image diagnostic dimensions')


def png_header_observation(value, data):
    """Read only the 29-byte IHDR envelope; observed numbers are not validation."""
    if (type(data) is not bytes or len(data) < 29
            or data[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'):
        return value
    width, height = int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
    dimension_class = ('invalid' if not width or not height else
                       'over_limit' if max(width, height) > 16384 else 'bounded')
    mode = {0: 'gray', 2: 'rgb', 3: 'indexed', 4: 'gray_alpha', 6: 'rgba'}.get(data[25], 'unknown')
    return replace(value, png_width=width if dimension_class == 'bounded' else None,
        png_height=height if dimension_class == 'bounded' else None, png_dimensions=dimension_class,
        png_mode=mode, png_bit_depth=str(data[24]) if data[24] in (1, 2, 4, 8, 16) else 'unknown',
        png_alpha='channel' if mode in ('gray_alpha', 'rgba') else 'undetermined')


def failure_observation(value, error):
    # Reflect only exact, fixed local codes; never arbitrary exception text/class names.
    if isinstance(error, TimeoutError):
        reason, kind = 'timeout', 'timeout'
    else:
        code = error.args[0] if type(getattr(error, 'args', None)) is tuple and len(error.args) == 1 else None
        reason = code if type(code) is str and code in REASONS[3:] else 'unknown'
        kind = ('image_provider_error' if type(error).__name__ == 'ImageProviderError' else
                'type_error' if isinstance(error, TypeError) else
                'value_error' if isinstance(error, ValueError) else
                'import_error' if isinstance(error, ImportError) else 'other')
    return replace(value, failure_reason=reason, failure_exception=kind,
        png_alpha='nonopaque' if reason == 'image_png_transparency' else value.png_alpha)
