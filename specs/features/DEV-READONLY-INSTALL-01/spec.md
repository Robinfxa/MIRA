# DEV-READONLY-INSTALL-01: explicitly approved managed executable

### DEVREADONLYINSTALL01-001 Verify the exact read-only installation without changing it

Given an explicitly approved managed context, an immutable optional ReadonlyInstallationApproval pins executable path, observed UID and mode. The process guard must verify the existing official executable SHA, reject symlinks and wrong owners/modes, ensure the current user cannot write any installation component, and require kernel read-only mounts for foreign-owned components. A missing read-only flag, writable ancestor, hash or path drift rejects execution. This does not copy the program/authentication, change operating-system permissions, trust arbitrary executable bytes, or admit model calls.

### DEVREADONLYINSTALL01-002 Public and default admission stay strict

Given no explicit managed installation approval, the prior root/current-user ownership rules remain. The public metadata preparer still rejects managed contexts. Existing managed runtime route, environment and config fingerprints remain separate admission requirements. A local guard pass or login-status message is not a successful native handshake or inference receipt.

Owner: codex_support/types.py and process.py. Offline metadata fixtures test the boundary; any actual initialize/config-read outcome is recorded separately.
