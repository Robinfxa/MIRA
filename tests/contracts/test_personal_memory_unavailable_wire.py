"""Independent synthetic wire checks. No providers or personal records."""
import json
from dataclasses import replace

import pytest

from mira.adapters.generation.codex_support.payload import build_prompt
from mira.adapters.generation.codex_support.types import CodexLimits
from mira.application.contracts import generation_context_data
from tests.contracts.test_actor_memory_recall import valid_past_line
from tests.contracts.test_personal_memory_projection import archive, context, empty_manual, input_record


@pytest.mark.parametrize('kind', ['manual', 'archive'])
def test_unavailable_omits_leftover_record_from_generation_wire(kind):
    marker = 'SYNTHETIC_STALE_RECALL_SHOULD_NOT_BE_CURRENT'
    fields = ({'memory_packet': replace(empty_manual(), past_candidates=(valid_past_line(marker),)),
               'memory_recall_status': 'unavailable'} if kind == 'manual' else
              {'conversation_recall': archive((input_record(marker),)),
               'conversation_recall_status': 'unavailable'})
    value = context(**fields)
    facts = generation_context_data(value)
    source = 'memory_evidence' if kind == 'manual' else 'conversation_recall'
    assert facts['first_person_dialogue']['self_continuity'][source] == 'unavailable'
    wire = build_prompt(value, CodexLimits())
    assert marker not in wire, 'Unavailable recall still transmits the leftover record in provider facts'
