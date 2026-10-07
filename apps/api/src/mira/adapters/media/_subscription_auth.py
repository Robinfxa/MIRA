"""Narrow media auth boundary: injected MIRA credentials, no storage or refresh IO."""
import re

from mira.adapters.generation.direct_codex_responses import CodexCredentialSource
from ._openai_http import ImageProviderError, RequestFence


async def subscription_headers(credential_source: CodexCredentialSource, *,
                               fence: RequestFence) -> dict[str, str]:
    """Caller owns the total timeout; this helper never retries or discovers auth.

    The existing credential source owns any scoped refresh. Values remain opaque;
    nothing here interprets token claims, changes scopes or checks entitlement.
    """
    fence.check()
    try:
        record = await credential_source.get_credentials()
        fence.check()
        token = record.access_token.get_secret_value()
        if (type(token) is not str or not re.fullmatch(r'[\x21-\x7e]{1,8192}', token)
                or token.startswith('sk-')):
            raise ValueError
        headers = {'Authorization': 'Bearer ' + token,
                   'Originator': 'mira', 'User-Agent': 'MIRA/0.4.1'}
        for attribute, name in (
            ('account_id', 'ChatGPT-Account-ID'),
            ('residency', 'x-openai-internal-codex-residency'),
        ):
            value = getattr(record, attribute, None)
            if value is not None:
                if type(value) is not str or not re.fullmatch(r'[\x21-\x7e]{1,256}', value):
                    raise ValueError
                headers[name] = value
        fence.check()
        return headers
    except Exception:
        fence.check()
        raise ImageProviderError('image_subscription_auth') from None
