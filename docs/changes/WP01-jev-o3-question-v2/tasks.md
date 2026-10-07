# WP01 JEV o3 completion-claim question v2

1. [x] Specify a positive o3 criterion and version boundary, preserving the input in its original Chinese.
2. [x] Add a failing test for version, exact question, full request state and digest binding.
3. [x] Add synthetic parser/policy tests for a strong o3 reject and the explicit-ban negative control.
4. [x] Add explicit v2 selection while keeping historical v1 default / question bytes unchanged.
5. [x] Verify the focused output review, typed evidence mapping, v1 corpus, threshold-v2 policy and requirement links.
6. [x] Re-run request-bound ASGI binding and the combined scoped v1/v2 regression suite after updating its expected selected question revision.

Scope: `apps/api/src/mira/adapters/review/jev.py` only for the explicit v2 question revision and o3 wording, plus the mapped contract tests and this scoped spec/docs. No provider/network/model/UI/auth call.
