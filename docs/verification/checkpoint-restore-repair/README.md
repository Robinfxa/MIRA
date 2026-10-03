# Explicit-check restore correction

The original generated helper used assertions for security and integrity validation. The same 25-case regression suite produced **15 failures / 10 passes** against that unchanged helper, then **25 passes** against `tools/restore_checkpoint.py`. Tests cover ordinary Python, `-O`, `PYTHONOPTIMIZE=1`, hashes/sizes, traversal, ambiguous/colliding paths, existing destination and partial member failure. All traversal tests target only a synthetic sibling sentinel inside their own temporary root.

The correction uses explicit `RestoreError` checks, bounded archive/manifest/member sizes, canonical portable path screening, regular-file modes, collision checks and an owned staging directory. It verifies data before final commit, retains existing destinations, and never executes archive code. Hashes provide consistency with the supplied manifest; the user must obtain that manifest from a trusted source. A private output parent without competing writers is required; this is not a sandbox against hostile same-user filesystem processes.

The already prepared 12:56 archive was restored under Python `-O`: all492 members passed, with stored and actual Unix file modes checked. The source archive bytes were not changed. This verifies the Linux/Python environment used here, not Windows/macOS behavior or a full product release.

Original RED/GREEN stdout and prepared-archive output are retained beside this file. The independent audit will rerun its original scenarios against the replacement. Subsequent checkpoint delivery must include the hardened helper and a clear notice superseding the assertion-based helpers, without rewriting earlier archives.

## Independent-review refinements

The reviewer found omitted Windows device names and central-directory allocation before entry-count enforcement. Both are addressed. Ten additional cases were actually RED against a byte-identical reconstruction of the earlier replacement (SHA-256 b3ee4cfdb6ea78041826c3ed6a76ce32126846bd4c7e2a609b79a8246b0447d0, matching its prior receipt), then the full35-case suite passed. The original25-case RED/GREEN remains unchanged evidence.

The format is now explicitly bounded ZIP32: a streamed central-directory preflight checks count and byte size before ZipFile constructs entry objects, and rejects unsupported ZIP64/multidisk/self-extracting layouts. Windows reserved-name checks were tested as path validation on Linux, not by executing Windows filesystem operations.
