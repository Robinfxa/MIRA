from mira.adapters.memory.sqlite import SQLiteMemoryStore
from mira.domain.memory import MemoryEntry, MemoryKind, MemoryScope, MemorySource


def test_page_byte_budget_continues_without_trimming_or_skipping_heads(tmp_path):
    scope = MemoryScope("user-a", "mira", "rain-cafe")
    path = tmp_path / "private" / "memory.sqlite"
    store = SQLiteMemoryStore(path, max_entry_chars=16_384).open()
    first_text = "x" * 16_384
    second_text = "y" * 16_384
    try:
        store.append(MemoryEntry(
            "legacy-large-first", scope, MemorySource.USER_STATEMENT,
            first_text, "evt-large-first", 1, kind=MemoryKind.EPISODIC,
        ))
        store.append(MemoryEntry(
            "legacy-large-second", scope, MemorySource.USER_STATEMENT,
            second_text, "evt-large-second", 1, kind=MemoryKind.EPISODIC,
        ))
        first_page = store.management_list(scope, limit=20)
        assert [item.entry_id for item in first_page.entries] == ["legacy-large-second"]
        assert first_page.entries[0].text == second_text
        assert first_page.next_cursor is not None
        assert 1024 + 6 * len(second_text) + 1024 <= 128 * 1024

        second_page = store.management_list(
            scope, limit=20, cursor=first_page.next_cursor
        )
        assert [item.entry_id for item in second_page.entries] == ["legacy-large-first"]
        assert second_page.entries[0].text == first_text
        assert second_page.next_cursor is None
    finally:
        store.close()
