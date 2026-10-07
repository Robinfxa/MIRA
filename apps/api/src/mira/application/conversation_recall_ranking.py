"""Local lexical ranking of exact transcript evidence, never semantic inference.

The caller validates and scopes the snapshot first. This module does no IO,
changes no eligibility/source text, and does not interpret a match as a fact.
"""
from __future__ import annotations

import re

# Common, compatibility and supplementary Han blocks. Other Unicode words keep
# whole-word matching; mixed Han/Latin strings form separate runs.
_HAN = '\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f'
_SEGMENTS = re.compile(f'[{_HAN}]+|[^\\W_{_HAN}]+')
_HAN_START = re.compile(f'[{_HAN}]')
_MAX_QUERY_CHARS = 8192
_MAX_QUERY_TERMS = 64


def _query_terms(text: str) -> tuple[tuple[str, str], ...]:
    terms: dict[tuple[str, str], None] = {}
    for match in _SEGMENTS.finditer(text[:_MAX_QUERY_CHARS].casefold()):
        part = match.group()
        if _HAN_START.match(part):
            # Bigrams recover overlap inside natural Chinese questions without
            # inventing word segmentation, synonyms or a learned preference.
            candidates = (part[i:i + 2] for i in range(max(1, len(part) - 1)))
            kind = 'han'
        else:
            candidates, kind = (part,), 'word'
        for term in candidates:
            terms[(kind, term)] = None
            if len(terms) == _MAX_QUERY_TERMS:
                return tuple(terms)
    return tuple(terms)


def _dialogue_text(record) -> str:
    payload = record.payload()
    if record.stage in ('accepted_input', 'corrected_input'):
        return payload['input']['text']
    if record.stage == 'presented_effect' and payload['effect']['kind'] == 'subtitle':
        return payload['effect']['value']
    if (record.stage == 'audio_progress' and payload['progress']['status'] == 'completed'
            and payload['effect']['kind'] == 'speech'):
        return payload['effect']['value']
    # A control receipt or uncompleted audio is still retained as its exact
    # historical source row, but its metadata/planned words cannot win ranking.
    return ''


def rank_conversation_records(records, request_text: str):
    """Return the same validated records ranked by content overlap, then recency.

    Candidate count/window and byte/row selection remain owned by the caller.
    Each distinct query term scores at most once; repeated content/metadata has
    no weight. Unmatched rows retain the existing recent-history fallback.
    """
    terms = _query_terms(request_text)

    def score(pair):
        index, record = pair
        text = _dialogue_text(record).casefold()
        words = {match.group() for match in _SEGMENTS.finditer(text)
                 if not _HAN_START.match(match.group())}
        overlap = sum(term in text if kind == 'han' else term in words for kind, term in terms)
        return overlap, index

    return sorted(enumerate(records), key=score, reverse=True)
