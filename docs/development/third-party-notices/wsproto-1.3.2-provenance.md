# wsproto 1.3.2 provenance

MIRA runtime now pins `wsproto==1.3.2` to give the pinned Uvicorn server an actual WebSocket implementation without installing the broader `uvicorn[standard]` set or the `websockets` package.

- Official release metadata: https://pypi.org/pypi/wsproto/1.3.2/json
- Official source: https://github.com/python-hyper/wsproto/tree/1.3.2
- Official wheel: https://files.pythonhosted.org/packages/a4/f5/10b68b7b1544245097b2a1b8238f66f2fc6dcaeb24ba5d917f52bd2eed4f/wsproto-1.3.2-py3-none-any.whl
- Wheel filename: `wsproto-1.3.2-py3-none-any.whl` (24,405 bytes)
- SHA-256 reported by PyPI and independently measured on the downloaded official wheel before installation: `61eea322cdf56e8cc904bd3ad7573359a242ba65688716b0710a5eb12beab584`
- PyPI metadata: `Requires-Python: >=3.10`; sole runtime requirement `h11<1,>=0.16.0`; `License-Expression: MIT`. The existing runtime lock already provides `h11==0.16.0`.
- The wheel is pure Python. Uvicorn's official WebSocket documentation says its `wsproto` protocol uses the `wsproto` package, and says it must be installed manually when selecting that implementation: https://www.uvicorn.org/concepts/websockets/ . Its `auto` implementation in the installed `uvicorn==0.48.0` source first tries `websockets`, then `wsproto`, and otherwise sets `AutoWebSocketsProtocol = None`. The corresponding `wsproto_impl.py` uses `config.ws_max_size` to bound text and binary WebSocket messages.
- The full MIT license shipped inside the SHA-verified wheel is copied to `licenses/python/wsproto/1.3.2/LICENSE`.

Verification evidence for this change: the real loopback Uvicorn microphone WebSocket test returned HTTP 404 at the WebSocket URL in the clean installed environment with no `wsproto` or `websockets`; after installing only this SHA-verified wheel into an isolated copy of that environment, Uvicorn auto selected `uvicorn.protocols.websockets.wsproto_impl.WSProtocol` and the live-socket suite passed. The suite uses an in-process synthetic ASR, fake generation/review adapters, and synthetic PCM; it makes no Google, Codex, JEV, microphone-device, or external-provider request. It exercises successful auth/start, invalid auth, origin rejection, a 32 KiB message limit close, normal close, and abrupt disconnect cleanup.
