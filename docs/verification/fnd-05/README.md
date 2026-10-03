# Browser/package fingerprint correction

This is a narrow correction to FND03-007, owned by the director's tooling lane.
Base remains ebb578dde665c9c7269e4a64b508182680b2fa66; no runtime behavior changed.

The old runner omitted public browser assets, index.html and setup.py from its before/after
fingerprints. Five real synthetic child mutations first returned an incorrect passed state.
The same five assertions passed after including those inputs. tsconfig.json is also now
fingerprinted because it controls the emitted application.

Actual immutable receipts:
- runs/001-red-public-source-fingerprints: five assertion failures, no collection error.
- runs/002-green-public-source-fingerprints: identical five tests passed.
- runs/003-green-runner-regressions: all54 quality runner/selection/spec tests passed.
All three receipts recorded zero concurrent covered-source changes.

The earlier11:04 integration suite remains valid for its frozen snapshot: the independent
1277-file capture manifest included these files and was rechecked byte-for-byte after that
run. This fix strengthens future in-place evidence; it does not retroactively add tests to
that earlier snapshot or claim real browser/device acceptance.

The directed record_check tool initially duplicated the older incomplete boundary.
A further actual RED→GREEN pair (004→005) now makes it use the aggregate runner's
single fingerprint function, including public assets, scripts and generated contracts.
Run006 reran all55 quality/recorder regressions successfully, with zero source drift.
