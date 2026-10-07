# Runtime dependency review — 2026-10-04

This is a bounded, source-aware review of locked runtime dependencies. It is not a security certification or a complete advisory-database scan. Development tools were outside this pass. Installation and real-socket evidence in this delivery come from Linux; macOS/user-device acceptance remains open.

## Narrow repairs in the next candidate

- **Uvicorn WebSocket support:** the0837 package had HTTP support but no installed WebSocket protocol implementation. A real allowed-Origin upgrade returned404. The exact official `wsproto==1.3.2` wheel is pinned; its sole dependency is `h11>=0.16.0,<1`, satisfied by the existing0.16.0 lock. Real TCP tests cover successful upgrade/authentication, rejected credentials/origins/query strings, oversized messages and disconnect cleanup. These tests inject a synthetic recognizer and do not establish real microphone or provider behavior.
- **PyJWT:** the optional local sign-in helper used2.13.0. The candidate moves only that package to2.15.1 with an exact official artifact hash and focused synthetic auth regression checks. Single `RS256`, fixed trusted JWKS endpoint, issuer/audience/nonce and redirect boundaries remain unchanged. No login or credential access is part of the update.

PyJWT's [2.14–2.15.1 changelog](https://github.com/jpadilla/pyjwt/blob/master/CHANGELOG.rst) documents key validation and malformed/deep-token handling, followed by a compatible trailing Base64URL padding correction. [GHSA-ffc3-869f-jxw9](https://github.com/advisories/GHSA-ffc3-869f-jxw9) affects2.13.0 and earlier; its mixed HMAC/asymmetric-key exploit conditions were not found in MIRA's single-RS256 path. The helper still parses the provider-returned header before signature validation, so keeping the old package merely because the most severe exploit prerequisites are absent would not be a complete maintenance response. Final acceptance is recorded in the matching delivery START-HERE; the existence of this note alone does not mark pending tests passed.

## Platform limitation retained

Locked Starlette0.50.0 is affected by [GHSA-wqp7-x3pw-xc5r](https://github.com/Kludex/starlette/security/advisories/GHSA-wqp7-x3pw-xc5r), concerning UNC paths in `StaticFiles` on Windows. MIRA mounts static files, but this review did not run Windows and did not establish a Windows mitigation. Do not treat Linux/HTTP tests or loopback binding as a Windows security proof. Windows is not an accepted target for this delivery; a cross-stack Starlette/FastAPI upgrade is deferred to a separately tested platform change.

Other reviewed Starlette findings depend on form parsing, `HTTPEndpoint` dispatch or security decisions from reconstructed URLs. Those paths were not found in the current application. This conclusion applies to the reviewed source, not future endpoints.

The pinned urllib3, h11 and xmldom versions are at or beyond the fixes for the concrete advisories examined. The scene renderer loads authored local PNG files; it does not accept remote/user-uploaded XML, SVG or GIF content. This constrained input path is not a claim that every transitive package has no vulnerabilities.
