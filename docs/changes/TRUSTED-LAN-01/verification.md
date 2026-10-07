# TRUSTED-LAN-01 verification

Base ZIP: `761323180bd4b0cba8d34ebe12c7f04c7901f0f4ef8bb153203d357423a2d500`; restored 1698 manifest-listed public files only into a separate source directory. No private runtime state, private inputs, prior caches or dependencies were copied. Dependencies were recreated from the unchanged lockfiles.

Evidence under `docs/verification/trusted-lan-01/runs/`:

- `001-web-red`: two real assertions failed because compiled main had no trusted gate; no collection error.
- `002-web-green`: same two compiled gate/controller lifecycle tests passed, including activation order, refresh, explicit close, late bootstrap and capacity failure.
- `003-cli-red`: ten behavior tests failed on the missing CLI flag, after successful collection.
- `004-cli-green`: identical ten CLI/direct-factory/ASGI/lifespan tests passed.
- `005-cli-regression`: 48 tests passed across new trusted-mode and existing private access, launcher, ownership and socket contracts. Added actual default CLI pair-file flow and expiry slot recovery.

The aggregate affected check and independent review are recorded separately at freeze. These are synthetic software checks with injected providers; no private authentication reads or external model, voice or image calls. Actual Mac/phone, browser microphone, certificate trust, sound, model quality and service billing remain unverified for this new mode.

The first aggregate run (`var/quality/4ab37f92c4fa4145bcc4550c59454429`) failed: its default pytest temporary directory was inside the checkout, correctly rejected by existing private-store and pairing-directory guards (config 2, tooling 4, providers 27 failures). No guard was relaxed. The same selected lanes are rerun with an explicitly external output directory.
