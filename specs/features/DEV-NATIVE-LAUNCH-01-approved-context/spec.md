# DEV-NATIVE-LAUNCH-01 Approved native Codex launch binding

Block: providers. Consumer: private approved development Codex launch only. This narrow contract does not change public Codex defaults, installation approval, tool isolation, model rules, or credential handling.

### DEVNATIVELAUNCH01-001
Given an explicitly approved managed development context, when the fixed app-server process is launched, then the global `--no-daemon` option precedes `app-server`; the fixed listen, disabled-capability, and development configuration arguments remain in force. The public profile retains its existing argv.

### DEVNATIVELAUNCH01-002
Given an explicitly approved managed development context, when binding the Codex home, then a nonempty explicit `CODEX_HOME` must be an absolute canonical safe path equal to the runtime home; only when that key is absent may canonical `HOME/.codex` provide the binding. Missing/relative/mismatched or symlinked paths fail closed. The original approved environment is passed unchanged: the helper never inserts `CODEX_HOME`, consults another environment source, discovers an alternate home, or reads credentials.

All checks use synthetic paths and transports. They do not launch a native process or call a provider.
