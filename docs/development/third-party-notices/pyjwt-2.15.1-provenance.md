# PyJWT 2.15.1 provenance and compatibility

Current runtime and development pins are `PyJWT[crypto]==2.15.1` in `pyproject.toml` and `pyjwt==2.15.1` in both Python lock files. PyJWT is used only by the optional local sign-in helper (`tools/mira_auth/oauth.py`); it does not broaden the MIRA server's login or API permissions.

## Official artifact

- PyPI release metadata: https://pypi.org/pypi/PyJWT/2.15.1/json
- Upstream source: https://github.com/jpadilla/pyjwt/tree/2.15.1
- Official wheel: `pyjwt-2.15.1-py3-none-any.whl` (33,860 bytes), https://files.pythonhosted.org/packages/50/ca/44de4e75f8aadc457f0634be3b542815078ded46dca30efb960edeecad6e/pyjwt-2.15.1-py3-none-any.whl
- PyPI SHA-256 and locally measured downloaded-wheel SHA-256 before installation: `42d59d631f7768a1028a64c7ff581a9bf7519804daf91fc5b6c56e30eec5e193`
- PyPI metadata: `Version: 2.15.1`; `Requires-Python: >=3.9`; `License-Expression: MIT`; extra `crypto` requires `cryptography>=3.4.0`.
- PyPI reports Trusted Publishing and a verified GitHub Actions attestation for `github.com/jpadilla/pyjwt`, commit `7d5ef55e42ce42221f58dc49943e92ccad1fa66a`.

The requirement files intentionally remain version-pinned rather than hash-enforced: they contain unhashed dependency lines. The artifact digest is retained here as provenance and was checked before the isolated install; this note does not claim that pip enforces the digest during ordinary lock installs.

## Security and compatibility scope

PyJWT's upstream changelog records security hardening in 2.14.0, recursion-error wrapping and related parsing fixes in 2.15.0, and compatibility with legal trailing Base64URL `=` padding in 2.15.1. Non-alphabet junk remains invalid. See the [upstream changelog](https://github.com/jpadilla/pyjwt/blob/master/CHANGELOG.rst).

The critical [GHSA-ffc3-869f-jxw9](https://github.com/advisories/GHSA-ffc3-869f-jxw9) marks versions through 2.13.0 affected and 2.14.0 patched. Its reported signature-forgery prerequisites are a mixed HMAC/asymmetric decode allow-list and a raw PEM key whose formatting evades PyJWT's asymmetric-key guard. MIRA's helper instead selects exactly one `RS256` JWK from its fixed JWKS object and calls `jwt.decode` with `algorithms=["RS256"]`; those reported prerequisites are not present in this code path. The pin update removes the affected version while keeping those existing controls unchanged.

No application auth implementation changed in this slice. The helper still verifies the fixed issuer, audience, nonce, required `iss`/`aud`/`sub`/`iat`/`exp` claims and granted OAuth scopes; it still rejects redirects and accepts only its fixed token/JWKS endpoints. Verification tokens and keys are synthetic; no live sign-in, network auth, provider call or secret was used.

## License

The full MIT license copied from the SHA-verified wheel is preserved at `licenses/python/pyjwt/2.15.1/licenses/LICENSE`; SHA-256: `797a7a20231d4c433e9f1911db1731d06b5828b98f499819a034f7c0f56f5ce5`. The identical 2.13.0 license remains at its historical versioned path. The 2026-10-03 installed attribution inventory and notice manifest are historical records and were not rewritten to claim that they described this later wheel.
