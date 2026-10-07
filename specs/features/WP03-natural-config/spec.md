# WP03 自然聆听公开端点配置

Owner: providers lane; consumers: direct-provider application factory and public CLI.
Base: immutable1325 audio recovery; synthetic settings/ADC metadata only; no provider resources or calls.

### WP03CONFIG-001
Given explicit voice configuration, check reports finite grace/drain and genuine nullable per-lease substream/per-process STT limits; explicit finite values remain opt-in without opening authentication/provider resources. Invalid ranges, NaN and infinity fail with a fixed field name before private-file access.

### WP03CONFIG-002
Given valid explicit endpoint options, the real direct application factory passes them to the listening registry while preserving explicit STT request ceilings and per-RPC duration; default total lease/sample ceilings are None. Closing the synthetic app closes its existing voice bundle once.

### WP03CONFIG-003
Given the local captured-silence mode, `--listen-silence-ms` selects a strict integer between 250 and 2000 milliseconds (default 700). The same value is declared by `check`, passed through the direct application factory and announced in the listening ready contract. Boolean, floating-point and out-of-range factory values fail before resource construction. This option does not require a Google speech-activity END event, increase the shared STT budget, or gate individual output PCM packets.

The grace is a declared heuristic, not proof of human utterance completion. No inference, Google request or microphone is started by configuration checks.
