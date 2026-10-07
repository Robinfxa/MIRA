# IMG-STARTUP-01: native image startup composition

Base: immutable MIRA1515 cohort, source mira-luna-tool-integration-20261006T1431Z.
Owner: bootstrap/container.py; test owner: providers via existing unique tests/contracts/test_*.py glob.
Consumers: actual tools/live_provider.py CLI, direct app, ASGI lifespan, SessionActor, native image tool,
image generation, canonical PNG, independent pixel review, resource and renderer receipt.
Subscription text requests may be unlimited under the current selected policy; image resources remain finite: one image job, one pixel review,
120second job deadline and original byte limits. No account calls or credentials are part of these tests.
This is a correction to the existing native authority contract, with no new side-effect authority.

### IMGSTARTUP01-001 Native image lifespan
Given the explicit native voice, story and image CLI flags with all existing consents,
when the real direct app enters and closes its lifespan, then validated native tool authority
satisfies the intent-authority composition requirement without creating JEV or fixture approval.
Both explicitly selected subscription and API routes work; legacy retains its conversation-first reviewer.

### IMGSTARTUP01-002 Exact pixel and presentation gates
Given a valid native image tool request, when generation and independent review run,
then only a matching canonical PNG with all required checks passing can receive a media grant.
A matching renderer receipt is still needed for a shown result; failure and unknown review do not show
an image, and tool continuation remains bounded at two model requests in the same existing budget.

### IMGSTARTUP01-003 Consent and unsupported composition
Given any absent data or spend consent, when startup is requested, then no provider is allocated.
Missing custom-brief consent keeps the native image tool unavailable. Non-native image composition
without optional intent review remains rejected. There is no subscription-to-API fallback.

The exact1515 reversible installer is a separately verified historical artifact; its source-cohort tests remain in the preserved hotfix evidence rather than this later application source.
