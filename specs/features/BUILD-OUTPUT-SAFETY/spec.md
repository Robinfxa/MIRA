# BUILD-OUTPUT-SAFETY — Guard web bundle output cleanup

## Requirement
The web bundle builder must never recursively remove a destination unless it can positively identify that directory as generated output. Build arguments and output-path safety must be checked before any destination write.

## Given / When / Then

### BUILDOUT-01: protected paths
- Given a synthetic project root, its ancestors, source trees, protected project directories, or an output path containing a symbolic link
- When the builder prepares its output
- Then it fails before writing or removing anything at the requested path.

### BUILDOUT-02: unknown existing directories
- Given a non-empty external output directory without the exact generated-output marker, or any nonempty unmarked tree at the default output, including legacy build-looking contents
- When the builder prepares its output
- Then it fails with instructions to inspect and move/remove the directory manually, leaving every entry unchanged.

### BUILDOUT-03: generated destinations
- Given a missing or empty fresh output, or a directory bearing the exact small generated-output marker
- When the builder prepares its output
- Then it creates a path-free marker; for marked generated output only, it may remove and recreate the old output before writing the new bundle.

### BUILDOUT-04: build options
- Given an unknown option or malformed --outdir argument
- When build arguments are parsed
- Then parsing fails before output preparation or any write.

## Scope and consumers
- Owner: `tools/build_web.mjs` and its narrow output safety helper
- Consumers: `npm run build`, `tools/check_web.py`, and the `web` quality lane
- Test block: `tests/web/build-output-safety.test.mjs`
- Output marker contains no absolute paths or private metadata and is an internal build sentinel, not a runtime/package resource. Package staging omits only the marker at the dist root; other bundle resources remain byte-for-byte.
