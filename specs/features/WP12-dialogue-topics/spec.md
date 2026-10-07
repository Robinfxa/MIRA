# WP12TOPICS: 可绕开、可回返的话题网

## Scope and original-source findings

Base: `1eaceff2e9e78f157f7325c22b753383c8b360da`, verified frozen0221 public source plus exactly six frozen continuity files. No private transcript, DB, provider, environment, credentials or current media-tool source is used.

The packaged seed has 18 canon rows and 16 planned events. Existing XiaHe, first seaside trip, unfulfilled printed-photo promise, star clip, raincoat, photography attention and small delights are the factual spine. The parser accepts only the existing four story states and t.chat / t.offer / t.yes / t.window. Planned seed events are not runtime transitions. This slice adds an optional topic graph, not more execution states.

### WP12TOPICS-001 — Bounded author detail and attribution

Given the selected author package, when constructing character context, then four small additions may enrich photography taste, cafe habits, the existing first-trip mishap and an after-rain plan. They extend existing attention / small_delights / first_trip / waiting rows; existing source text remains and gains an attributed addition, and their first-person rendering is compacted. All other canon rows remain unchanged. Updated rows retain S12 and add S14 with source version 3. No new canon rows, user facts or shared history are created. The three-year-old trip remains authored past; after-rain remains a possible future. No new romance, arrival, delivered print, displayed picture, unbounded biography or second trip is added.

### WP12TOPICS-002 — Connected optional topics

Given a valid version-bound story projection, dialogue_topic_options returns at most nine topics for inspecting the author graph. A turn consumer may explicitly select zero to two topic IDs; unknown, duplicate, non-tuple or larger selections are rejected. Each topic resolves at most three canon IDs from that same projection, has at most three related details and three edges. Entry and return rules are shared once, without repeating global constraints per topic. It copies no biography or user text. Unselected canon or topic selection removes dangling edges. Omissions are explicit and do not ban other conversation. There is no keyword classifier, current_topic lock, relationship score, timer, provider call or persistence.

### WP12TOPICS-003 — Digressions and return remain normal dialogue

Given any scene node, an unrelated topic, disagreement, refusal, silence or Stop never requires a topic or new plot node. Topics are optional writing choices after responding to the current input. Recent exact inputs and presented dialogue resolve short follow-ups; returning requires the user's current direction, and missing evidence requires clarification. Projection does not mark anything disclosed, heard or completed. A withheld story option remains undisclosed until supported by the actual runtime path.

### WP12TOPICS-004 — One facts source and no new parser authority

The integration seam is first_person_dialogue.optional_topics = dialogue_topic_options(story_projection=story_projection, topic_ids=selected_ids). None inspects the full author graph and is not a recommendation to inject all nine every turn. The personal-memory owner or director owns the shared hook and turn selection; this slice does not edit character_memory.py, character_voice.py, contracts.py, domain/story.py or bootstrap. Both generation and JEV output review already serialize first_person_dialogue through generation_context_data; integration must run both actual serializers and the normal prompt budget before release. Topic text cannot become an effect, story proposal, memory-write permission or authoritative intention classification. Existing parser continues to reject an invented topic_proposal. Real effects and future-event completion still require their existing exact presentation receipts.

### WP12TOPICS-005 — Synthetic scenarios and resource limits

Offline scenarios cover XiaHe detail, print/perfection, photography differences, first-trip past, cafe daily life, small stories, rain/after-rain plans, unrelated chat, digression/return, refusal, Stop and unavailable alternate photos. Structural fixtures do not grade model prose or prove natural trigger selection. Full graph projection is limited to 4096 UTF-8 JSON bytes; selected zero-to-two views are tested below 2200 bytes. The current full model context and post-merge provider budgets must also pass. No new installed dependencies or calls.

Canon revision 3 intentionally changes the version/hash binding. Existing revision-2 persisted story checkpoints are rejected by the unchanged drift guard. This slice does not migrate, delete or open any real checkpoint. Session-only use has no old checkpoint to migrate.

## Test ownership and handoff

- Owner: providers via existing tests/contracts/test_*.py glob in tests/quality.toml (no catalogue change needed).
- Consumers: first_person_dialogue shared generation/JEV output context; packaged author seed/selection.
- RED/GREEN: same tests/contracts/test_dialogue_topics.py, real source capture and external logs.
- Handoff: affected from the common base, jobs 3 maximum subject to director resource budget. Architecture/config/actor/providers/http/tooling/specs selected; no full/release by this worker.
- Resources: supplied Python environment only; no Node work expected, no real DB, network or provider.
- Live natural dialogue quality, user device and media-tool integration remain unverified.

### WP12TOPICS-006 — Joined production runtime and explicit budget fallback

The frozen0323 integration installs compact dialogue_topic_guidance in generation_context_data. It ranks zero to two optional writing resources from current accepted text and the immediately previous accepted subject for short references. No activity/input-count association is inferred for replies. Stop, digression and unknown referents never force a return. Both normal direct/JEV wires share canon/self sources; smaller wires may omit hints with an exact optional_topics_omitted count before any inherited history bound. Existing v4 lossless references compact only byte-identical author metadata. Actual synthetic direct Actor HTTP and JEV5/10/20turns, relevant-topic PROBE4turns, no-fact-loss fallback and tool continuation are covered. See [integration contract](integration.md) for exact fields, ownership and limits. Component monkeypatch tests above remain historical component probes, not proof of this installed hook.
