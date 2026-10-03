# MIRA third-party notices

This directory preserves installed license and notice text for the exact Python distributions in `docs/development/ATTRIBUTION-INVENTORY.json` and TypeScript 5.8.3. `manifest.json` records each installed source path, the notice-bundle path, SHA-256, pinned version, and whether the item is a runtime or development/build dependency. It also records nested notices from the locally installed pip and setuptools distributions separately.

The copied Python texts came from the existing `.venv313` installation after verifying each installed distribution's name/version against the frozen pins. TypeScript texts came from `node_modules/typescript` after matching installed and lockfile version 5.8.3. This copies license/notice texts only. The source checkout does not include the installed package implementations. Development/build-only items and nested pip/setuptools vendor notices apply if those tools or their vendored contents are included in a future release.

The manifest also references project-authored SVGs and generated offline speech files already present in the source tree, with links to the existing SVG and speech provenance notes. It records their provenance and source hashes without copying or inventing a project license. The Flite/CMU `slt` sources and installed local notice are cited as provenance references; neither the Flite software nor voice binary is in the project tree. FFmpeg was a local generation tool and is not included. The current `apps/web/index.html` hash differs from the inventory's whole-file hash, so that artwork provenance reference needs a fresh review against the modified file.

The Python locks pin versions but not wheel hashes, and `package-lock.json` does not record the TypeScript tarball integrity. Some installed packages use generic/legacy license metadata; the manifest keeps those descriptions as observed rather than normalizing them. See `evidence_gaps` and `source_tree_drift` in the manifest.

This is distribution evidence, not legal advice, legal clearance, or a choice of MIRA's project license. Determine the actual release contents and project license separately before distribution.
