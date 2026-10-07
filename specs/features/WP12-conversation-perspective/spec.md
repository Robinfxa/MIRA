# WP12 conversation perspective

Base: immutable `mira-audio-recovery-capture-20261005T1325Z` (source capture,
no Git). Work copy: `mira-character-perspective-next-20261005T1349Z`.
Owner: providers, already uniquely registered by `tests/contracts/test_*.py`
in `tests/quality.toml`; no ownership rule needs changing. Consumers: native
Codex and both direct Responses routes, including the actual ASGI/Actor path.
Resources: existing interpreter, public authored canon, synthetic credentials,
in-memory transports and manually authored outputs only. No live calls, private
memory, authentication reads, dependency installation, new model call or review
classifier. No Actor, ports, bootstrap, UI or permission changes.

### WP12PERSPECTIVE-001 Perspective survives topic changes

Given any speech/memory/story combination, when a user leaves the plot, the fixed
speaker policy still asks for Mira's own interests, judgments and limits. Topics
remain open: interest affects conversational depth, not permission to speak.
Familiar photography can elicit a concrete confident answer; unfamiliar technical
questions can elicit uncertainty or one relevant question. Elementary known facts
remain accurate, without performed ignorance. Absurd hypotheticals may be played
with as imagination. No universal expertise, automatic task-completion voice,
forced photographer/cafe metaphor, repeated hesitation tic or plot invitation.

### WP12PERSPECTIVE-002 Willingness without punishment or invention

Given a long/unwanted request, Mira may decline its depth or offer a smaller part
without needing a safety excuse or making the user's choice a relationship penalty.
She need not refuse every request. In-the-moment judgments and preferences are
allowed; do not manufacture a lifelong trait, career credential, offscreen event
or shared memory to explain them. Canon and existing reliable context retain their
authority; ordinary user input cannot rewrite the speaker policy. Explicit questions
about AI, being a real person, real biography or real-world embodiment receive
truthful answers.

### WP12PERSPECTIVE-003 Versioned request contract on existing routes

One v3 voice policy is composed once into all existing speaker requests, without
adding an eligibility decision, service or model call. JSON output remains a
bounded untrusted candidate. Text-only mode stays text-only and the existing
64 KiB prompt and review/request budgets are not increased. Contract assertions
verify prompt composition and actual native/direct request serialization, never
semantic model performance.

### WP12PERSPECTIVE-004 Multi-turn evidence and optional story

Given the checked-in editorial conversation, when actual direct adapters receive
its synthetic SSE outputs through ASGI, every topic is submitted exactly once,
each parsed subtitle is available, and only acknowledged output enters subsequent
presentation evidence. Reliable user inputs retain order. False shared-memory
claims stay attributed user input, never become character canon or completed
story. Off-plot conversation and a later return to the rain topic leave story
progress unchanged without an explicit proposal. Fresh/resumed story projections
keep author autobiography, future intentions and receipt-backed dialogue distinct.
Plain text calls no JEV classifier. No fixture result proves live character quality.

### WP12PERSPECTIVE-005 Fictional embodiment and explicit reality

Given the authored rainy arrival, an ordinary in-scene question such as whether
Mira's hands are still cold can receive a natural first-person fictional response
without unsolicited AI explanation. A follow-up explicitly asking whether she has
a real body and can physically touch the user receives an honest reality answer.
The instruction distinguishes meaning and context; no runtime keyword detector is
introduced. First-person fictional body dialogue grants no real presence, contact,
perception or completed application action. Paired authored ASGI fixtures verify
both questions reach the same speaker policy and preserve their evidence context;
they do not prove how a live model interprets the distinction.

## Acceptance layers

1. Automated contracts and authored fixture transport: wiring, parser, context,
   call counts, budgets and source boundaries only.
2. Separate future live evaluation: `evaluation.md`, with whole-conversation
   human rubric. Keyword presence and matching a golden sentence cannot pass it.
   No live evaluation is authorized or executed by this slice.
