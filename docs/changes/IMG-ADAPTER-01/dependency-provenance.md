# Pillow dependency provenance

Selected pin: Pillow==12.3.0. Existing HTTPX stays at 0.28.1; no OpenAI SDK dependency was introduced. The director approved this dependency before lock changes and owns environment provisioning. This adapter slice performs no package installation.

Official release: https://pillow.readthedocs.io/en/stable/releasenotes/12.3.0.html (2026-07-01).
Official package and checksums: https://pypi.org/project/pillow/12.3.0/#files (checked 2026-10-05).
Official license description: https://pillow.readthedocs.io/en/stable/about.html#license identifies MIT-CMU. Source license: https://github.com/python-pillow/Pillow/blob/12.3.0/LICENSE . Bundled dependency licenses must remain with any redistributed binary wheel; normal Python package installation retains its dist-info license files.

Proposed environment artifact: pillow-12.3.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.
Published SHA-256: 78cb2c6865a35ab8ff8b75fd122f6033b92a62c82801110e48ddd6c936a45d91.
Source archive pillow-12.3.0.tar.gz published SHA-256: 3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce.

The repository lock policy uses exact version pins, not per-platform hash sets. The Linux wheel hash is evidence for the current test environment only, not a verification of macOS/Windows wheels or runtime behavior. No other platform artifact was installed or executed in this slice.

The decoder bounds bytes and 1024x1024 dimensions before full raster loading; verifies PNG structure/CRCs, rejects APNG, fully verifies and loads with Pillow, and re-encodes new RGB pixel storage without metadata. Public documentation: https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#png .

Provider contract sources (public reads, zero model calls):
- https://developers.openai.com/api/reference/resources/images/methods/generate
- https://developers.openai.com/api/docs/guides/images-vision
- https://developers.openai.com/api/docs/guides/structured-outputs

Model and quality choices remain injected. The dependency pin and resource bounds grant no live route/data/spending consent and enforce no hard-dollar billing cap.

Strict IDAT envelope/compression reference: https://www.w3.org/TR/png-3/ sections 7, 8, 10 and 11.2. The v2 repair adds bounded zlib stream/checksum/length validation; no dependency or installation change. Pillow remains the pixel decoder.
