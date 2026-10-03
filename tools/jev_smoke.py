"""Bounded opt-in synthetic JEV smoke. Never logs keys, bodies or private dialogue."""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import re
import ssl
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api/src'))

from mira.adapters.review.jev import (
    QUESTION_SET_VERSION, JevReviewBackend, JevReviewContract,
    JevResponseError, _parse_response, candidate_digest, context_digest,
)
from mira.adapters.review.jev_support.http import HttpxJevTransport
from mira.application.contracts import CandidateRange, EffectProposal, GenerationContext
from mira.config.loader import load_settings
from mira.domain.models import EffectKind

MODEL = 'jev-1.13.0'
TOTAL_LIMIT = Decimal('0.01')
PRICE_PER_INPUT_TOKEN = Decimal('0.042') / Decimal(1_000_000)
# Official fixed-model limit checked 2026-10-03:64K tokens across state/questions;
# output is free. Keep10% headroom. This is a local estimate, not an invoice cap.
PER_ATTEMPT_RESERVE = Decimal(64_000) * PRICE_PER_INPUT_TOKEN * Decimal('1.1')


def cases():
    return (
        ('compatible-greeting', '请简单问好。', '你好，很高兴见到你。', ()),
        ('explicit-speech-boundary', '请不要说话，只安静地看雨。', '我现在继续大声说话。',
         ('不要说话，只安静地看雨。',)),
    )


def contract(context, candidate, restrictions):
    return JevReviewContract(
        'synthetic-connectivity', QUESTION_SET_VERSION, context_digest(context),
        candidate_digest(candidate), restrictions, (context.user_text,),
        ('这是虚构的雨夜咖啡馆场景。', 'MIRA是原创成年角色。'),
        synthetic=True,
    )


async def probe_case(case, transport):
    name, user_text, candidate_text, restrictions = case
    context = GenerationContext(user_text, (user_text,), (), 1)
    candidate = CandidateRange((EffectProposal(EffectKind.SPEECH, candidate_text),), name)
    binding = contract(context, candidate, restrictions)
    backend = JevReviewBackend(transport=transport, model=MODEL,
        contract_resolver=lambda *_: binding, calibration_ref=None,
        request_limit=1, timeout_seconds=10)
    result = await backend.review_detailed(context, candidate)
    usage = result.usage
    estimate = (Decimal(usage.input_tokens) * PRICE_PER_INPUT_TOKEN if usage else None)
    return {
        'case': name, 'model': result.model,
        'transport_and_schema_verified': result.model == MODEL and usage is not None,
        'verdict': result.observation.verdict.value,
        'reason_code': result.observation.reason_code,
        'input_tokens': usage.input_tokens if usage else None,
        'output_tokens': usage.output_tokens if usage else None,
        'estimated_usd_from_published_rate': str(estimate) if estimate is not None else None,
        'production_calibration_admitted': False,
    }


def approved_transport(secret):
    """Explicitly reuse existing infrastructure; never mutate or print proxy/CA settings."""
    import httpx
    ca = os.environ.get('SSL_CERT_FILE') or os.environ.get('REQUESTS_CA_BUNDLE')
    context = ssl.create_default_context(cafile=ca)
    proxy = (os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
             or os.environ.get('ALL_PROXY') or os.environ.get('all_proxy'))
    return HttpxJevTransport(secret, transport=httpx.AsyncHTTPTransport(
        proxy=proxy, verify=context, trust_env=False, retries=0))


def diagnosed_transport(delegate, trace):
    """Keep only HTTP status and allowlisted schema/type metadata, never raw content."""
    async def call(payload, **kwargs):
        try:
            response = await delegate(payload, **kwargs)
        except JevResponseError as error:
            trace['transport_representation_error'] = (
                str(error) if str(error) in {
                    'jev_response_encoding_invalid', 'jev_response_too_large'
                } else 'representation_invalid')
            raise
        trace['http_status'] = response.status_code
        trace['response_bytes'] = len(response.body)
        try:
            body = json.loads(response.body)
            trace['root_type'] = type(body).__name__
            if isinstance(body, dict):
                allowed = {'model', 'answers', 'usage', 'error', 'detail', 'id', 'object'}
                trace['known_root_fields'] = sorted(set(body) & allowed)
                trace['additional_root_field_count'] = len(set(body) - allowed)
                model = body.get('model')
                trace['response_model'] = (model if isinstance(model, str) and
                    re.fullmatch(r'jev-[0-9]+\.[0-9]+(?:\.[0-9]+)?', model) else 'unrecognized')
                answers = body.get('answers')
                trace['answers_type'] = type(answers).__name__
                if isinstance(answers, dict):
                    trace['answer_count'] = len(answers)
                    example = next(iter(answers.values()), None)
                    fields = {'type', 'choice', 'confidence', 'probabilities', 'value', 'noul', 'score'}
                    if isinstance(example, dict):
                        trace['answer_field_types'] = {k: type(v).__name__ for k, v in example.items()
                            if k in fields}
                        trace['additional_answer_field_count'] = len(set(example) - fields)
                usage = body.get('usage')
                if isinstance(usage, dict):
                    trace['usage_field_types'] = {k: type(v).__name__ for k, v in usage.items()
                        if k in {'input_tokens', 'output_tokens', 'total_tokens'}}
                    trace['additional_usage_field_count'] = len(set(usage) - {
                        'input_tokens', 'output_tokens', 'total_tokens'})
            _parse_response(response.body, MODEL, set(json.loads(payload)['questions']))
            trace['parser_result'] = 'valid'
        except Exception as error:
            safe = {'response_shape', 'model_mismatch', 'answer_coverage', 'usage_shape',
                    'answer_shape', 'probabilities', 'choice_not_maximum',
                    'inconsistent_confidence', 'duplicate_key', 'nonfinite_number', 'body_size'}
            trace['parser_result'] = str(error) if str(error) in safe else 'invalid_representation'
        return response
    return call


def save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


async def run_live(report_path, max_cases=2):
    settings = load_settings(root=ROOT, env_file=ROOT / '.env', environ={})
    secret = settings.services.jev.api_key
    if secret is None or (settings.services.jev.model not in (None, MODEL)):
        raise ValueError('jev_configuration_missing_or_model_mismatch')
    ledger_path = ROOT / 'var/mission/jev-live-budget.json'
    ledger = (json.loads(ledger_path.read_text()) if ledger_path.exists() else
              {'maximum_attempts': 20, 'maximum_usd': str(TOTAL_LIMIT), 'attempts': []})
    rows = []
    for case in cases()[:max_cases]:
        charged = sum((Decimal(item['budget_charge_usd']) for item in ledger['attempts']), Decimal(0))
        if len(ledger['attempts']) >= 20 or charged + PER_ATTEMPT_RESERVE > TOTAL_LIMIT:
            rows.append({'case': case[0], 'reason_code': 'local_budget_exhausted'})
            break
        attempt = {'case': case[0], 'started_at': datetime.now(UTC).isoformat(),
                   'budget_charge_usd': str(PER_ATTEMPT_RESERVE), 'status': 'reserved'}
        ledger['attempts'].append(attempt)
        save(ledger_path, ledger)  # Reserve BEFORE any potentially billable request.
        trace = {}
        try:
            row = await probe_case(case, diagnosed_transport(approved_transport(secret), trace))
        except Exception:
            row = {'case': case[0], 'transport_and_schema_verified': False,
                   'reason_code': 'sanitized_probe_error', 'production_calibration_admitted': False}
        row['completed_at'] = datetime.now(UTC).isoformat()
        row['diagnostics'] = trace
        rows.append(row)
        attempt['status'] = row['reason_code']
        estimate = row.get('estimated_usd_from_published_rate')
        if estimate is not None:
            # Conservative 50% buffer; a token estimate is not an invoice or provider hard cap.
            attempt['budget_charge_usd'] = str(max(Decimal(estimate) * Decimal('1.5'), Decimal('0.00001')))
        save(ledger_path, ledger)
        save(report_path, {'model': MODEL, 'results': rows,
             'attempted_requests': len(rows), 'retries': 0,
             'production_calibration_admitted': False,
             'billing_note': 'Token-price estimate with local reserve; invoice unverified.'})
        if not row.get('transport_and_schema_verified'):
            break  # No automatic retry of a failed/uncertain request.
    return {'model': MODEL, 'results': rows, 'attempted_requests': len(rows), 'retries': 0,
            'production_calibration_admitted': False,
            'billing_note': 'Token-price estimate with local reserve; invoice unverified.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-live', action='store_true', help='Only after explicit bounded user approval')
    parser.add_argument('--max-cases', type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    if not args.allow_live:
        print(json.dumps({'armed': False, 'requests': 0, 'model': MODEL,
                          'requires': 'explicit user approval then --allow-live'}))
        return
    folder = ROOT / 'var/mission/jev-smoke'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    with (ROOT / 'var/mission/jev-live-budget.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            result = asyncio.run(run_live(path, args.max_cases))
        except Exception:
            result = {'status': 'configuration_or_runtime_failure', 'details_redacted': True}
        save(path, result)
        print(json.dumps(result, ensure_ascii=False))
        print('Sanitized report:', path)


if __name__ == '__main__':
    main()
