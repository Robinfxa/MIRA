# Continuous listening diagnostics

Owner: providers lane. Base: immutable manual-core capture ce3f05aa6a7a16f0fdf75902415ca91606e1386db0a60b56cebb336c14991109 integrated with1845 and the bounded application profile. Only synthetic recognition streams and injected diagnostic sinks are tested here. This does not establish live latency, microphone behavior or provider availability.

### CONTINUOUSDIAGNOSTICS-001: safe stage cause and correlation

Recognition retains the existing allowlisted authentication, permission, quota and timeout codes. Arbitrary exception text is discarded. A request-correlated existing STT span observes first revision, first final revision and stream end once, without transcript, PCM, credentials, headers or arbitrary provider metadata. Server elapsed time starts at the recognition consumer, not at a measured Google network dispatch. A broken diagnostic sink cannot break cancellation or the service outcome.

### CONTINUOUSDIAGNOSTICS-002: observed cancellation versus cleanup

Global user Stop, disconnect, replacement and session closure are distinct controlled cancellation causes. Local cancellation is diagnosed immediately even when provider cleanup is slow; stream-end is observed only when iteration/cleanup actually finishes. A finite declared duration/sample/utterance boundary is a limit outcome, not falsely labeled as a user click. No log assertion means real physical resources were released before the corresponding code observed that release.
