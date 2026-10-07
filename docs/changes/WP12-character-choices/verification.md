# WP12 character choices: offline proposal and request evidence

Status: proposed speaker refinement, not behavioral/live acceptance. Checked 2026-10-06 UTC.
The sole runtime edit is `apps/api/src/mira/adapters/generation/codex_support/character_voice.py`.
Baseline: frozen1645 `mira-post1515-integration-20261006T1623Z`. The original speaker is preserved
verbatim in `specs/features/WP12-prompt-refinement/fixtures/speaker-baseline-v4.txt`.

## What changes

Replace repeated rule wording with a compact positive characterization layer: supplied tastes
can affect a choice and reason; the tension between careful selection and finishing a delayed
promise can matter; candor need not become coyness. Current-topic replies may use their own
point of view, including off-plot interests. An invited idle turn may end with one thought.
None of reaction, personal detail, follow-up question, scene description or plot is mandatory.

The existing first-person/provenance distinction remains, including the concrete prohibition
on unsolicited 故事里 / 角色设定 / 现实里的我 prefixes. Explicit AI or real-world questions are
truthful. Private user facts, consent, feelings and perception must not be invented. Internal
instructions and status labels guide generation without becoming spoken lines. Failure,
pending and completion retain their actual application meanings. No canon source, release
state, recognition state, tool implementation, parser, JEV, call count, permission or memory
scope changed. The separate native story dialogue repair is not contained in this patch.

## Current primary research

- [Official bot configuration](https://docs.mai-mai.org/manual/configuration/bot-config): identity,
  behavior style and reply style are separate configuration concerns; the documented private-chat
  guidance is short and attends to the ongoing exchange. The useful principle is separation of
  responsibilities, not adoption of its group-chat behavior, style switching or learning.
- [Official speaker template](https://github.com/Mai-with-u/MaiBot/blob/main/prompts/zh-CN/maisaka_replyer.prompt):
  concise identity/topic/style/output guidance, with reference information treated as optional.
- [Official planner template](https://github.com/Mai-with-u/MaiBot/blob/main/prompts/zh-CN/maisaka_chat.prompt):
  action analysis is explicitly distinct from speaking as the character. MIRA keeps its existing
  one-call/one-continuation protocol; no second planner or speaker call is added here.
- [Actual reply generator](https://github.com/Mai-with-u/MaiBot/blob/main/src/chat/replyer/maisaka_generator_base.py):
  `_build_system_prompt` composes identity and reply style; `_build_request_messages` keeps history,
  reference information and the final target request distinct. This is implementation evidence
  for the separation above, not evidence that copying a prompt would improve MIRA.
- [Actual reply tool](https://github.com/Mai-with-u/MaiBot/blob/main/src/maisaka/builtin_tool/reply.py):
  reply-reference/style inputs and generated visible reply are separate; a duplicate-target
  reminder uses the already sent reply. MIRA already supplies exact presented history, so this
  change requires no new retrieval or classifier.

Sources were read through public web tools on 2026-10-06. Branch URLs are mutable; page crawl
freshness varied from yesterday to three weeks for directory indexes. Only the current fetched
primary content above informed this small change. No community anecdotes are asserted as
measurements; no third-party private logs, user transcripts or corpus uploads were used.

## A/B material

`fixtures/behavior-review.json` contains 13 self-authored positive/negative editorial pairs:
recurring greeting; off-plot hobby; short hobby follow-up; another photo with generation available;
another photo without it; indirect recognition; recognition confirmation; released role canon;
invited idle topic; actual failed tool; pending tool; explicit AI; ordinary why-here.
The positive lines illustrate a direction, are not injected into the speaker prompt and are not
model outputs. Both positive and negative text parse, so syntax cannot certify conversational
quality. The failure/recognition expectations still depend on truthful application results.

`test_ab_uses_identical_real_serialized_context_and_protocol` runs each case through the actual
Direct Responses adapter, over `httpx.MockTransport`, on both configured route types. It injects
the same neutral response in A and B. A uses the frozen speaker text; B uses the candidate.
Every serialized request field except `instructions` is asserted equal, including exact user
history, presented effects, tool schemas, current capability booleans and output contract. Tool
continuations retain the exact supplied result JSON and cannot issue another call. Confirmation
references in this request test are synthetic; actual receipt-origin enforcement remains covered
by existing native-character tests owned by the separate integration.

For genuine A/B review later, use these same contexts and application states, hide arm labels,
and read the actual generated text/tool choices for topic fit, personal viewpoint, natural
continuity, and truthful status. Keep negative examples out of prompts. This run performs no
live model comparison and does not approve a subjective improvement or a release.

## Actual checks and limits

- Initial new tests: 42 failed, as expected, on the original missing choices layer / identical
  A and B instructions. Log: `/tmp/mira-speaker-red-20261006T1802Z.log`. This is a prompt/wire
  contract RED, not an observed live language failure.
- Final focused regression: 224 passed in 4.46 s. Includes 44 new cases (16 instruction flag
  combinations, 26 serialized A/B cases, 2 large synthetic recall requests) and 180 existing
  prompt, first-person, tone, ordinary-scene and role-canon checks.
  Log: `/tmp/mira-speaker-final-20261006T1809Z.log`.
- Full spec traceability collect/check completed successfully, exit 0:
  `/tmp/mira-speaker-specs-20261006T1809Z.log`.
- Affected plan generated successfully. Selected: architecture, config, actor, providers,
  http, tooling, specs. Plan: `/tmp/mira-speaker-affected-plan-20261006T1809Z.json`.
  Affected execution/full/release are **not_run in this isolated partial source copy**; the
  integration owner must run them on the final combined source. No dependency installation.
- Speaker text: 6,327 UTF-8 bytes (baseline 6,309). Maximum composed author instructions:
  11,898 bytes (baseline 11,880), under the unchanged 12,000 assertion across all 16 flag
  combinations. No prompt cap was raised.
- Large recall capture on both routes: 7 synthetic 4,000-character rows plus authored character
  and active released-role context. Serialized payload 51,741 bytes; instructions 10,676 bytes;
  aggregate HTTP body 67,122 bytes. The existing application caps payload separately from
  instructions; 65,536 is not a universal aggregate HTTP-body bound. The same frozen speaker
  yields 67,104 aggregate bytes, so this distinction predates the refinement.

Exact adapter-generated A/B request bodies and case IDs are under
`/tmp/mira-speaker-final-20261006T1809Z/test_ab_uses_identical_real_se*/` (`case.json`,
`request-a.json`, `request-b.json`). Large-memory request bodies and measured sizes are under
`test_large_synthetic_recall_an0/` and `test_large_synthetic_recall_an1/` in that same run.
Pytest `*current` entries are aliases, not additional cases. All contents are synthetic.
