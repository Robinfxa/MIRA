# SEMANTIC-CHUNK-01 Bounded semantic caption planning

Base: immutable 0550 capture, 1091 source files. Owner: providers (new Python
contract tests match its existing glob), web (new Node tests match existing glob).
Consumers: complete CandidateRange producer, SessionActor, compiler, HTTP schema,
presentation gate/controller and actual subtitle receipts. Resources: existing Python
and Node only, injected fake JEV/TTS, no network/auth/install. Shared metadata/schema
and controller changes are explicitly assigned to this slice; director owns final
integration checks. This is post-completion planning, not token streaming.

### SEMANTICCHUNK01-001 Immediate prefix and unchanged speech
Given one eligible ordinary text-only caption, publish an exact first whole-sentence
caption immediately and start tail planning independently. All speech-bearing
candidates retain their complete original cue and one original speech effect: the
current Actor serially awaits speech permission before consuming another candidate,
so splitting them could lose the tail on that wait's turn timeout. This slice does
not implement progressive voice captions or speech chunking. Story/affect/pose/scene/
media candidates and uncuttable/short captions also retain complete-cue fallback.
No extra Google synthesis calls; speech permission stays in the existing Actor path.

### SEMANTICCHUNK01-002 Original text and bounded semantic choice
Given at most 4096 code points, JEV may choose only an application-enumerated partition
of the unissued tail at legal sentence/paragraph boundaries outside quotes/brackets.
At most four disjoint contiguous chunks reconstruct the exact original caption.
No rewrites, approval grades, controls, permissions or generated offsets are accepted.

### SEMANTICCHUNK01-003 Finite fallback and resources
Given UNKNOWN, malformed response, exhausted budget, unavailable backend or a hard
planning deadline, preserve the entire remaining tail. Make at most one JEV attempt
per eligible candidate, no retries. Cancellation-resistant work occupies one bounded
slot; its late result never rewrites or revives a chunk. Deadline is a configured
software bound, not a measured provider-latency promise.

### SEMANTICCHUNK01-004 Cancellation and current identity
Given Stop, new input, close or context/version changes, old pending ranges cannot
become new grants. Original reliable input and already receipted chunks survive.
Metadata is application-owned, immutable and digest-bound; no duplicated prefix or
fallback replay occurs.

### SEMANTICCHUNK01-005 Actual caption FIFO
Given multiple chunk grants, first display is immediate; later chunk displays use a
bounded local FIFO with a minimum dwell, never audio/character-ratio alignment.
Receipt and page-history observer fire only after the exact chunk applies. Stop,
revocation, new input and close cancel queued/timer work; repeated snapshots do not
replay chunks. Legacy unchunked and speech-dependent cues retain existing behavior.

### SEMANTICCHUNK01-006 Strict JEV protocol
Given injected fixed-origin JEV transport, require exact model, request-bound question,
answer shape, complete finite probabilities, maximum selected option, bounded usage
and response bytes. Invalid/foreign/replayed choices yield no semantic selection.
Default request allowance is zero; no environment, credential or client discovery.
