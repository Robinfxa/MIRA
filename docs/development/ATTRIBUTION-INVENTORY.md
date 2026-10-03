# Attribution and asset inventory

Reviewed 2026-10-03. This is an evidence inventory for the frozen 12:56 candidate, not legal advice, legal clearance, a project license choice, or a redistribution bundle. It does not grant or infer rights in the MIRA project or AI-assisted outputs. Machine-readable detail: [`ATTRIBUTION-INVENTORY.json`](ATTRIBUTION-INVENTORY.json).

## Python distributions

The frozen `requirements/dev.lock` contains 46 exact name/version pins (35 runtime, 11 development/build-only). The existing isolated `.venv313` (Python 3.13.5) distribution metadata matched all 46 with no extras. License evidence below is the installed wheel metadata/license file (`.dist-info`); source links come from package `Project-URL`/`Home-page` metadata where present, otherwise the PyPI project page. The source locks are not wheel-hash locks.

| Distribution | Version | Use | Source | License declaration and installed evidence |
|---|---:|---|---|---|
| `annotated-doc` | `0.0.4` | runtime | [upstream/source](https://github.com/fastapi/annotated-doc) | MIT; METADATA License-Expression: MIT; `annotated_doc-0.0.4.dist-info/licenses/LICENSE` |
| `annotated-types` | `0.7.0` | runtime | [upstream/source](https://github.com/annotated-types/annotated-types) | MIT (license file and MIT classifier; no metadata License field); No License/License-Expression; MIT OSI classifier plus included LICENSE; `annotated_types-0.7.0.dist-info/licenses/LICENSE` |
| `anyio` | `4.13.0` | runtime | [upstream/source](https://github.com/agronholm/anyio) | MIT; METADATA License-Expression: MIT; `anyio-4.13.0.dist-info/licenses/LICENSE` |
| `certifi` | `2026.5.20` | runtime | [upstream/source](https://github.com/certifi/python-certifi) | MPL-2.0; METADATA License: MPL-2.0; `certifi-2026.5.20.dist-info/licenses/LICENSE` |
| `cffi` | `2.1.1` | runtime | [upstream/source](https://github.com/python-cffi/cffi) | MIT-0; METADATA License-Expression: MIT-0; `cffi-2.1.1.dist-info/licenses/LICENSE` |
| `charset-normalizer` | `3.5.2` | runtime | [upstream/source](https://github.com/jawah/charset_normalizer) | MIT; METADATA License: MIT; `charset_normalizer-3.5.2.dist-info/licenses/LICENSE` |
| `click` | `8.1.8` | runtime | [upstream/source](https://github.com/pallets/click/) | BSD 3-Clause terms (license file and generic BSD classifier; no metadata License field); No License/License-Expression; generic BSD OSI classifier plus included LICENSE.txt; `click-8.1.8.dist-info/LICENSE.txt` |
| `coverage` | `7.13.3` | dev/build | [upstream/source](https://coverage.readthedocs.io/en/7.13.3) | Apache-2.0; METADATA License: Apache-2.0; `coverage-7.13.3.dist-info/licenses/LICENSE.txt` |
| `cryptography` | `50.0.0` | runtime | [upstream/source](https://github.com/pyca/cryptography/) | Apache-2.0 OR BSD-3-Clause; METADATA License-Expression: Apache-2.0 OR BSD-3-Clause; `cryptography-50.0.0.dist-info/licenses/LICENSE, cryptography-50.0.0.dist-info/licenses/LICENSE.APACHE, cryptography-50.0.0.dist-info/licenses/LICENSE.BSD` |
| `fastapi` | `0.128.2` | runtime | [upstream/source](https://github.com/fastapi/fastapi) | MIT; METADATA License-Expression: MIT; `fastapi-0.128.2.dist-info/licenses/LICENSE` |
| `google-api-core` | `2.40.0` | runtime | [upstream/source](https://github.com/googleapis/google-cloud-python) | Apache 2.0; METADATA License: Apache 2.0; `google_api_core-2.40.0.dist-info/licenses/LICENSE` |
| `google-auth` | `2.59.1` | runtime | [upstream/source](https://github.com/googleapis/google-cloud-python/tree/main/packages/google-auth) | Apache 2.0; METADATA License: Apache 2.0; `google_auth-2.59.1.dist-info/licenses/LICENSE` |
| `google-cloud-speech` | `2.40.0` | runtime | [upstream/source](https://github.com/googleapis/google-cloud-python/tree/main/packages/google-cloud-speech) | Apache-2.0; METADATA License: Apache-2.0; `google_cloud_speech-2.40.0.dist-info/licenses/LICENSE` |
| `googleapis-common-protos` | `1.75.5` | runtime | [upstream/source](https://github.com/googleapis/google-cloud-python/tree/main/packages/googleapis-common-protos) | Apache-2.0; METADATA License-Expression: Apache-2.0; `googleapis_common_protos-1.75.5.dist-info/licenses/LICENSE` |
| `grpcio` | `1.84.0` | runtime | [upstream/source](https://github.com/grpc/grpc) | Apache-2.0; METADATA License-Expression: Apache-2.0; `grpcio-1.84.0.dist-info/licenses/LICENSE` |
| `grpcio-status` | `1.84.0` | runtime | [upstream/source](https://grpc.io) | Apache-2.0; METADATA License-Expression: Apache-2.0; `grpcio_status-1.84.0.dist-info/licenses/LICENSE` |
| `h11` | `0.16.0` | runtime | [upstream/source](https://github.com/python-hyper/h11) | MIT; METADATA License: MIT; `h11-0.16.0.dist-info/licenses/LICENSE.txt` |
| `httpcore` | `1.0.9` | runtime | [upstream/source](https://github.com/encode/httpcore) | BSD-3-Clause; METADATA License-Expression: BSD-3-Clause; `httpcore-1.0.9.dist-info/licenses/LICENSE.md` |
| `httpx` | `0.28.1` | runtime | [upstream/source](https://github.com/encode/httpx) | BSD-3-Clause; METADATA License: BSD-3-Clause; `httpx-0.28.1.dist-info/licenses/LICENSE.md` |
| `idna` | `3.17` | runtime | [upstream/source](https://github.com/kjd/idna) | BSD-3-Clause; METADATA License-Expression: BSD-3-Clause; `idna-3.17.dist-info/licenses/LICENSE.md` |
| `iniconfig` | `2.3.0` | dev/build | [upstream/source](https://github.com/pytest-dev/iniconfig) | MIT; METADATA License-Expression: MIT; `iniconfig-2.3.0.dist-info/licenses/LICENSE` |
| `opentelemetry-api` | `1.45.0` | runtime | [upstream/source](https://github.com/open-telemetry/opentelemetry-python) | Apache-2.0; METADATA License-Expression: Apache-2.0; `opentelemetry_api-1.45.0.dist-info/licenses/LICENSE` |
| `packaging` | `25.0` | dev/build | [upstream/source](https://github.com/pypa/packaging) | Either Apache-2.0 or BSD-2-Clause; included LICENSE says contributions are under both; No License/License-Expression; generic Apache/BSD classifiers; included LICENSE plus LICENSE.APACHE and LICENSE.BSD; `packaging-25.0.dist-info/licenses/LICENSE, packaging-25.0.dist-info/licenses/LICENSE.APACHE, packaging-25.0.dist-info/licenses/LICENSE.BSD` |
| `pip` | `26.2.1` | dev/build | [upstream/source](https://github.com/pypa/pip) | MIT; METADATA License-Expression: MIT; `pip-26.2.1.dist-info/licenses/LICENSE.txt` |
| `pluggy` | `1.6.0` | dev/build | [PyPI page](https://pypi.org/project/pluggy/) (upstream URL absent in wheel metadata) | MIT; METADATA License: MIT; `pluggy-1.6.0.dist-info/licenses/LICENSE` |
| `proto-plus` | `1.29.0` | runtime | [upstream/source](https://github.com/googleapis/google-cloud-python) | Apache 2.0; METADATA License: Apache 2.0; `proto_plus-1.29.0.dist-info/licenses/LICENSE` |
| `protobuf` | `7.36.2` | runtime | [upstream/source](https://developers.google.com/protocol-buffers/) | 3-Clause BSD License; METADATA License: 3-Clause BSD License; `protobuf-7.36.2.dist-info/LICENSE` |
| `pyasn1` | `0.6.4` | runtime | [upstream/source](https://github.com/pyasn1/pyasn1) | BSD-2-Clause; METADATA License: BSD-2-Clause; `pyasn1-0.6.4.dist-info/licenses/LICENSE.rst` |
| `pyasn1_modules` | `0.4.2` | runtime | [upstream/source](https://github.com/pyasn1/pyasn1-modules) | BSD (generic metadata label; included text contains the 3-clause non-endorsement condition); METADATA License: BSD; `pyasn1_modules-0.4.2.dist-info/licenses/LICENSE.txt` |
| `pycparser` | `3.0` | runtime | [upstream/source](https://github.com/eliben/pycparser) | BSD-3-Clause; METADATA License-Expression: BSD-3-Clause; `pycparser-3.0.dist-info/licenses/LICENSE` |
| `pydantic` | `2.13.4` | runtime | [upstream/source](https://github.com/pydantic/pydantic) | MIT; METADATA License-Expression: MIT; `pydantic-2.13.4.dist-info/licenses/LICENSE` |
| `pydantic_core` | `2.46.4` | runtime | [upstream/source](https://github.com/pydantic/pydantic/tree/main/pydantic-core) | MIT; METADATA License-Expression: MIT; `pydantic_core-2.46.4.dist-info/licenses/LICENSE` |
| `Pygments` | `2.20.0` | dev/build | [upstream/source](https://github.com/pygments/pygments) | BSD-2-Clause; METADATA License-Expression: BSD-2-Clause; `pygments-2.20.0.dist-info/licenses/LICENSE` |
| `PyJWT` | `2.13.0` | runtime | [upstream/source](https://github.com/jpadilla/pyjwt) | MIT; METADATA License-Expression: MIT; `pyjwt-2.13.0.dist-info/licenses/LICENSE` |
| `pytest` | `9.0.2` | dev/build | [upstream/source](https://github.com/pytest-dev/pytest) | MIT; METADATA License-Expression: MIT; `pytest-9.0.2.dist-info/licenses/LICENSE` |
| `pytest-asyncio` | `1.3.0` | dev/build | [upstream/source](https://github.com/pytest-dev/pytest-asyncio) | Apache-2.0; METADATA License-Expression: Apache-2.0; `pytest_asyncio-1.3.0.dist-info/licenses/LICENSE` |
| `pytest-cov` | `7.0.0` | dev/build | [upstream/source](https://github.com/pytest-dev/pytest-cov) | MIT; METADATA License-Expression: MIT; `pytest_cov-7.0.0.dist-info/licenses/LICENSE` |
| `python-dotenv` | `1.2.2` | runtime | [upstream/source](https://github.com/theskumar/python-dotenv) | BSD-3-Clause; METADATA License: BSD-3-Clause; `python_dotenv-1.2.2.dist-info/licenses/LICENSE` |
| `requests` | `2.34.2` | runtime | [upstream/source](https://github.com/psf/requests) | Apache-2.0; METADATA License: Apache-2.0; `requests-2.34.2.dist-info/licenses/LICENSE, requests-2.34.2.dist-info/licenses/NOTICE` |
| `setuptools` | `84.0.0` | dev/build | [upstream/source](https://github.com/pypa/setuptools) | MIT; METADATA License-Expression: MIT; `setuptools-84.0.0.dist-info/licenses/LICENSE` |
| `starlette` | `0.50.0` | runtime | [upstream/source](https://github.com/Kludex/starlette) | BSD-3-Clause; METADATA License-Expression: BSD-3-Clause; `starlette-0.50.0.dist-info/licenses/LICENSE.md` |
| `typing_extensions` | `4.16.0` | runtime | [upstream/source](https://github.com/python/typing_extensions) | PSF-2.0; METADATA License-Expression: PSF-2.0; `typing_extensions-4.16.0.dist-info/licenses/LICENSE` |
| `typing-inspection` | `0.4.2` | runtime | [upstream/source](https://github.com/pydantic/typing-inspection) | MIT; METADATA License-Expression: MIT; `typing_inspection-0.4.2.dist-info/licenses/LICENSE` |
| `urllib3` | `2.8.0` | runtime | [upstream/source](https://github.com/urllib3/urllib3) | MIT; METADATA License-Expression: MIT; `urllib3-2.8.0.dist-info/licenses/LICENSE.txt` |
| `uvicorn` | `0.48.0` | runtime | [upstream/source](https://github.com/Kludex/uvicorn) | BSD-3-Clause; METADATA License-Expression: BSD-3-Clause; `uvicorn-0.48.0.dist-info/licenses/LICENSE.md` |
| `wheel` | `0.48.0` | dev/build | [upstream/source](https://github.com/pypa/wheel) | MIT; METADATA License-Expression: MIT; `wheel-0.48.0.dist-info/licenses/LICENSE.txt` |

### Notes on Python license evidence

- `annotated-types` and `click` have no `License`/`License-Expression` metadata fields; the installed wheel supplies MIT and BSD license text respectively. `packaging` also has no SPDX expression: its included `LICENSE` allows either Apache or BSD-2-Clause (contributions under both); `pyasn1-modules` declares generic `BSD`, while the included text contains the non-endorsement third clause.
- `pip` and `setuptools` are dev/build-only pins. Their installed distributions include vendored-component license files in their installed metadata trees; some vendored components are not separate top-level requirements. Reassess/preserve those notices if shipping these tool distributions or the entire build environment.
- Exact package artifacts are not reproducibly identified by the Python locks: they pin versions but not wheel SHA-256 values. The present environment check does not establish the bytes of a future platform-specific wheel.

## TypeScript compiler

| Component | Version/source | License evidence |
|---|---|---|
| TypeScript (devDependency) | `5.8.3`; [npm tarball](https://registry.npmjs.org/typescript/-/typescript-5.8.3.tgz), [upstream repository](https://github.com/microsoft/TypeScript) | Apache-2.0 in `package-lock.json` and `node_modules/typescript/package.json`; `node_modules/typescript/LICENSE.txt`; bundled `ThirdPartyNoticeText.txt` |

`package-lock.json` records exact version and resolved tarball URL but has no npm `integrity` field. Preserve the TypeScript license and third-party notice if redistributing the compiler package.

## Original project SVG artwork

Project notes (`apps/web/public/scene/ORIGINAL-ASSETS.md` and `docs/changes/WP04-character-scene/design.md`) describe these as AI-assisted original, hand-authored SVG geometry; no third-party stock artwork, character model, font package or template rig is identified. The notes are provenance statements, not independent originality findings. No project-wide license is selected or inferred.

| File | Role | Evidence | SHA-256 |
|---|---|---|---|
| `apps/web/public/scene/cafe-night.svg` | runtime scene background | Project provenance notes; no external artwork/license identified | `3c3dcfb31b9126ab3ee511dd1e241fd2d714babcfd100651346fd162913cbf96` |
| `apps/web/public/scene/trip-memory.svg` | runtime illustrated travel artifact | Project provenance notes; no external artwork/license identified | `e6571c45bb27bcc010854ffed0077837a225959d8224437b2b6234a5b0d8745e` |
| `apps/web/index.html` | inline original adult MIRA character SVG (.mira-character) | Project provenance notes; no external artwork/license identified | `212c72a380dd9e16b44cbdc66feaa9bf4c22f383a3fe486250e528accf899c72` |
| `docs/changes/WP04-character-scene/previews/mira-character.svg` | review-only character-art preview; reproduces inline character artwork | Project provenance notes; no external artwork/license identified | `0c3a7f85a59cc829f5ee7ad48d52764c0a7731eb4304cf07a434748063aa3bbf` |
| `docs/changes/WP04-character-scene/previews/expressions-study.svg` | review-only expression contact-sheet SVG | Project provenance notes; no external artwork/license identified | `070af7d67f7d9a6df4107668570482be129ee3c5abc96b6708daa7c0dc11464b` |

The inline character artwork is the `<svg class="mira-character">` in `apps/web/index.html`; the review-only previews duplicate or arrange original character/expression artwork and are not runtime dependencies. Static-layout test snapshots are copies, not additional distinct assets.

## Generated offline speech assets

DEMO-02 evidence identifies eight original AI-assisted English captions synthesized locally through FFmpeg `flite` with the installed CMU Flite `slt` voice. The repository contains 8 PCM/8 WAV generated outputs only (24 kHz mono PCM16; 52.560 s total); it does not contain Flite software or the CMU voice binary. The manifest records individual hashes and the binary hashes of the local synthesis inputs.

| Clip | Files | Duration |
|---|---|---:|
| `greeting` | `greeting.pcm`, `greeting.wav` | 6135 ms |
| `camera` | `camera.pcm`, `camera.wav` | 5185 ms |
| `photo` | `photo.pcm`, `photo.wav` | 6720 ms |
| `detail` | `detail.pcm`, `detail.wav` | 6075 ms |
| `absent` | `absent.pcm`, `absent.wav` | 4450 ms |
| `story` | `story.pcm`, `story.wav` | 14715 ms |
| `rain` | `rain.pcm`, `rain.wav` | 4660 ms |
| `warm` | `warm.pcm`, `warm.wav` | 4620 ms |

Reviewed speech provenance sources: [Flite upstream COPYING](https://github.com/festvox/flite/blob/master/COPYING), [CMU `slt` voice source](https://github.com/festvox/flite/blob/master/lang/cmu_us_slt/cmu_us_slt.c), and the installed `/usr/share/doc/libflite1/copyright` recorded in the fixture manifest by SHA-256. The existing review found a permissive CMU software/voice license and no separate restriction on newly synthesized output in those reviewed sources; this is a scoped assessment only, not legal advice or an exclusivity claim. The installed package-manager version metadata was unavailable, so exact Flite package release/build is not established. FFmpeg 7.1.5-0+deb13u1 was used locally and is not distributed; its build/license configuration is not part of the evidence. If binaries are ever distributed, review their exact package/build notices then.

## Release/attribution follow-ups

- Determine and document the project’s intended distribution model and chosen project license separately; this inventory does not make that choice.
- If a release bundles Python dependencies, prepare a release-specific license/NOTICE bundle from the exact artifacts shipped. Current license evidence was read from the isolated installed distributions, not copied into a redistributable notice folder.
- Add wheel and npm artifact integrity hashes if exact package bytes/reproducibility are required.
- Keep the distinction between generated speech output and redistribution of the Flite/`slt` binaries; binary redistribution has not been cleared here.
