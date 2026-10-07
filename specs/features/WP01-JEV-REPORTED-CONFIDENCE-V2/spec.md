# WP01 JEV reported-confidence wire policy v2

Status: a separately versioned wire-admission policy for the explicitly assembled
development product path. This does not revise TypeSafe's published claim that
Choice confidence is derived by an exact formula, and does not claim that the
provider generated its fields independently. The observed rounded vector may still
be formula-inconsistent; in v2 that cross-field inconsistency is a bounded diagnostic
warning rather than an additional schema hard-stop.

Legacy adapter constructors and replay retain strict `jev-choice-cent-interval-v1`.
The existing exact-math helper remains unchanged. Development product composition
explicitly selects `jev-reported-confidence-v2` for output review and input referents.

## Given / When / Then

### WP01JEVREPORTEDCONFIDENCEV2-001 Versioned reported-confidence admission

Given a Choice answer using the explicit v2 wire policy, when its probability map has
the exact expected keys and finite non-boolean values in [0, 1], has a feasible sum
under the existing cent-interval/full-precision validator, and names a maximal choice,
then formula-inconsistent reported confidence is retained as sent and produces a
traceable bounded warning rather than a schema failure. Under default legacy strict
mode the same answer remains invalid. Neither mode normalizes, recomputes, rounds, or
overwrites provider fields.

### WP01JEVREPORTEDCONFIDENCEV2-002 Admission and semantic gates remain hard

Given either wire policy, when keys, types, finiteness, ranges, sum feasibility,
selected maximum, or other response structure is invalid, then parsing fails closed.
For an otherwise valid output Choice, semantic policy still requires the original
selected probability and original confidence to each meet their configured threshold;
REJECT remains REJECT when sufficiently strong. Explicit constraints, permissions,
bindings, and every non-confidence review dimension remain in force.

### WP01JEVREPORTEDCONFIDENCEV2-003 Product composition, input referents, and v3

Given the actual development product composition, when input and output JEV adapters
are assembled, then both use the versioned v2 wire policy while direct constructor
defaults remain legacy strict. Input `NOUL` directions and thresholding are unchanged.
Output question set v3 remains semantically unchanged: clear NO skips only O3; other
answers, including explicit constraint rejection, still determine the result. An
ASGI synthetic observed response may pass the existing policy only when every other
hard gate permits it, with a safely bounded warning linked to the v2 policy marker.
This mechanics test is not evidence of provider correctness or live quality.
