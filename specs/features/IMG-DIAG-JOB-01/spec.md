# IMG-DIAG-JOB-01: retain closed image operation diagnostics by job

Baseline: frozen 2012 public capture ecec9b56465f249f90d71103c1f2ab21d82d80a8611a2da62337be870031366d, source commit 355609fe43149a902eb1e5ace53a1e3879826a1d. This slice owns only image_readiness.py and image_operation_diagnostics.py. No provider calls, new authorization, image review relaxation, or presentation authority changes.

### IMGDIAGJOB01-001
A current background image job keeps its exact closed operation stage, failure class and bounded PNG observations across ordinary reply epochs, including its terminal failure. The event retains both current reply epoch/activity and immutable job origin epoch/activity.

### IMGDIAGJOB01-002
The producer's diagnostic request ID owns the observation. A replacement reservation resets the observation before new provider IO; duplicate or late callbacks from an old request cannot overwrite the replacement. A failed job's terminal observation cannot be erased by late success. Existing cancellation and scope fences remain authoritative.

### IMGDIAGJOB01-003
Only fixed local subscription pixel-review codes are exported, including separate event, output, wire, decoded and line limits. Unknown exception text remains unknown; no prompt, provider body, credentials or pixels enter diagnostics. This cannot recover the exact cause omitted by an earlier export.

### IMGDIAGJOB01-004
A synthetic production Actor may review one image while accepting another ordinary input, retain a failed review through the next reply, and preserve one generation/one review, no media grant and no retry on failure. This is offline evidence, not live provider or device acceptance.

