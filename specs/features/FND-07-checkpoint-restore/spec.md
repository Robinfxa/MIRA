# FND-07 Explicit checkpoint restore validation

Block: tooling. Consumers: public source checkpoint recovery. Base: the prepared 12:56 helper and frozen source snapshot. Resources: tiny synthetic local archives and the already verified prepared archive; no network or credentials.

### FND07-001
Given a checkpoint archive, manifest and a nonexistent destination, integrity, size, member identity, regular-file mode and safe canonical path checks must execute under ordinary Python, `-O` and `PYTHONOPTIMIZE`. Explicit exceptions enforce validation; assertions do not protect restore behavior. Reject duplicate/case-ambiguous members, traversal, dot-only, drive/backslash paths, Windows device/forbidden names, excessive path depth, and file/directory collisions. Before ZipFile allocates entries, preflight the actual ZIP32 central-directory records with an8MiB directory and10000-entry bound. ZIP64, multidisk and self-extracting layouts are unsupported and rejected. The file must start with a local ZIP header at byte zero, the first central-directory record must point there, and every central-directory disk-start marker must be zero.

### FND07-002
Given invalid metadata or member data, do not commit a partial final destination or modify an existing destination. Validate staged contents and Unix modes before renaming the owned staging directory. Staging cleanup is best effort after failure; use a private output parent without competing writers.

### FND07-003
Given a valid supported checkpoint, restore its bytes and stored regular-file modes. Hash consistency is not manifest source authentication. Windows filename checks are conservative source-level protections; Windows executable/mode behavior is not asserted as tested.

The historical generated helpers remain immutable evidence and are superseded by the explicit-check replacement. Python optimization must never remove any production validation.
