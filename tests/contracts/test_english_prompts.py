"""Offline English-edition source contracts; no provider or credential access."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'apps/api/src/mira/adapters/story/assets'
GENERATION = ROOT / 'apps/api/src/mira/adapters/generation'


def _assigned_text(path, name):
    """Inspect fixed prompt literals without importing provider adapters."""
    module = ast.parse(path.read_text())
    assignment = next(node for node in module.body if isinstance(node, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == name for t in node.targets))
    return ''.join(node.value for node in ast.walk(assignment.value)
                   if isinstance(node, ast.Constant) and isinstance(node.value, str))


def test_english_is_default_in_every_generation_prompt():
    for path, name in ((GENERATION / 'direct_tools.py', '_TOOL_INSTRUCTIONS'),
                       (GENERATION / 'direct_tools.py', '_LEGACY_TOOL_INSTRUCTIONS'),
                       (GENERATION / 'codex_support/payload.py', 'AUTHOR_INSTRUCTIONS')):
        prompt = _assigned_text(path, name)
        assert 'English unless' in prompt
        assert 'Chinese unless' not in prompt
        assert 'JSON' in prompt
        assert 'receipt' in prompt


def test_english_seed_is_exactly_bound_and_keeps_fiction_boundaries():
    seed_bytes = (ASSETS / 'mira.story-seed.v1.json').read_bytes()
    seed = json.loads(seed_bytes)
    selection = json.loads((ASSETS / 'canon-selection.v1.json').read_text())
    assert hashlib.sha256(seed_bytes).hexdigest() == selection['seed_source']['sha256']
    assert seed['language'] == 'en'
    assert not re.search(r'[\u4e00-\u9fff]', seed_bytes.decode())
    assert seed['real_memory_written'] is False
    assert seed['provider_calls_made'] is False
    for entry in seed['canonical_fiction']:
        assert entry['is_user_fact'] is False
        assert entry['must_not_treat_as_happened_to_user'] is True
    assert seed['pacing']['target_spoken_chinese_characters'] == [15, 65]


def test_english_chapter_matches_runtime_and_retains_wire_role():
    path = ROOT / 'apps/api/src/mira/domain/xiahe_chapter.py'
    spec = importlib.util.spec_from_file_location('_mira_english_chapter_contract', path)
    chapter = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = chapter
    try:
        spec.loader.exec_module(chapter)
        reference = json.loads((ASSETS / 'xiahe-chapter.v1.json').read_text())
        assert reference['source_hash'] == chapter.CHAPTER_SOURCE_HASH
        assert reference['canonical_name'] == chapter.ROLE_NAME == '夏禾'
        assert [(row['beat'], row['source_id'], row['text']) for row in reference['canon']] == list(chapter.CHAPTER_CANON)
        assert all(not re.search(r'[\u4e00-\u9fff]', text) for _, _, text in chapter.CHAPTER_CANON)
        state = chapter.ChapterState()
        assert state.role_active is False
        assert state.stage is chapter.ChapterStage.STRANGER
        assert state.source_hash == chapter.CHAPTER_SOURCE_HASH
    finally:
        sys.modules.pop(spec.name, None)


def test_english_homepage_exposes_runtime_sources_and_chinese_backup():
    home = (ROOT / 'README.md').read_text()
    assert 'README.zh-CN.md' in home
    assert 'docs/prompts/README.md' in home
    assert 'character_voice.py' in home
    assert 'README.md' in (ROOT / 'README.zh-CN.md').read_text()
    guide = (ROOT / 'docs/prompts/README.md').read_text()
    assert 'not complete product localization' in guide
    assert 'legacy validator' in guide
    for target in re.findall(r'\]\(([^)#]+)(?:#[^)]*)?\)', guide):
        if '://' not in target:
            assert (ROOT / 'docs/prompts' / target).exists(), target


def test_waiting_role_binding_uses_reviewed_english_canon_digest():
    seed = json.loads((ASSETS / 'mira.story-seed.v1.json').read_text())
    waiting = next(row for row in seed['canonical_fiction'] if row['id'] == 'canon.waiting')
    source = json.dumps({key: waiting[key] for key in ('text', 'first_person_text')},
                        ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    expected = hashlib.sha256(source.encode()).hexdigest()
    tree = ast.parse((ROOT / 'apps/api/src/mira/domain/story.py').read_text())
    guard = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == 'awaited_friend_claim_available')
    digests = [node.value for node in ast.walk(guard)
               if isinstance(node, ast.Constant) and isinstance(node.value, str)
               and re.fullmatch(r'[0-9a-f]{64}', node.value)]
    assert digests == [expected]


def test_loaded_english_waiting_canon_keeps_role_guard_closed_on_mutation():
    from dataclasses import replace
    from mira.bootstrap.character_story import builtin_definition
    from mira.domain.story import awaited_friend_claim_available
    from mira.domain.xiahe_chapter import ChapterState
    entries = builtin_definition().canon.entries
    state = ChapterState()
    assert awaited_friend_claim_available(state, entries)
    changed = tuple(replace(entry, text=entry.text + ' Altered.')
                    if entry.entry_id == 'canon.waiting' else entry for entry in entries)
    assert not awaited_friend_claim_available(state, changed)
    assert not awaited_friend_claim_available(replace(state, suspended=True), entries)
    assert not awaited_friend_claim_available(replace(state, role_active=True), entries)
