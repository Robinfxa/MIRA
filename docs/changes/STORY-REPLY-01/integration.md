# Required Actor integration (owned by image lifecycle worker)

In SessionActor.stop after the ordinary output Stop/cutoff has produced state:

- scope == 'all': character_runtime.stop(state.output_epoch), unchanged.
- scope == 'reply': character_runtime.reply_fence(state.output_epoch, state.presented_effects).

In _generation_candidates when computing role_reference:

- Keep question = character_runtime._native_role_question.
- Replace raw context.output_epoch == question[1]+1 plus receipt search with character_runtime.native_role_question_current(context.output_epoch, context.presented_effects, request_id).
- Keep role_reference = question[:2]; do not rewrite its source epoch.

The helper changes no Actor grants, request IDs or transport scope. The caller must already enforce its cutoff/epoch and prevent old output from returning. Helper clears chapter pending immediately without adding a fake input; presented role/offer and current suspension persist. Rain's unpresented pending branch is canceled as at ordinary begin_input. No persistent schema field is added: question frontier is bounded per-runtime metadata, absent from checkpoints and new sessions.

Actual API and compiled PTT integration must run against the owner's composed candidate. This branch's runtime tests do not substitute for that cross-layer acceptance.

The first actual begin_input binds (question_id,input_id,epoch); a different input consumes it even if an epoch were accidentally reused. Failed begin_input validation does not mutate eligibility. Background notification is not begin_input and must not consume the question: completion eligibility should defer while _native_role_question is non-None, including a question awaiting receipt, to avoid inserting an ambiguous subtitle before the real answer.

Observed isolated evidence: initial14 expected failures/1 prior global-Stop pass ->15pass; additional actual-input-ID RED1 ->GREEN16. Final directed runtime/native/chapter regression143passed. Full affected and real scope=reply API/compiled PTT results are separate, not implied by these runtime tests. Frozen d29 remains unchanged.
