# Unicode session token correction

Independent audit reproduced TypeError from compare_digest on valid non-ASCII WebSocket strings. The registry now rejects non-ASCII token text before constant-time comparison, returning the same safe session-not-found code as other incorrect tokens.

001 retained: two real errors plus one initially incorrect surrogate expectation. Surrogate input was already safely rejected as invalid_input by the DTO boundary.
002 RED corrects only that expectation:2failed/1passed.
003 GREEN uses identical tests:3passed, no source changes. Valid session authorization still works after each bad token.
004 records wider synthetic HTTP/media regression separately. No real credentials, network providers, browser or device test.
