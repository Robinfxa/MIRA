# DEMO-02: finite original English offline rehearsal speech

## Scope and ownership

The explicitly selected offline rehearsal receives eight bounded, original-caption
speech fixtures through the existing speech pipeline. The finite manifest is the
single caption source. This change owns only audio fixture resources, its build
script, the corresponding asset tests, and this specification/documentation.
No live factory, shared protocol, playback controller, or Google/Codex gate changes.

- Base: `ebb578dde665c9c7269e4a64b508182680b2fa66`.
- Test owner: `providers`, via existing `tests/contracts/test_*.py` in `tests/quality.toml`.
- Consumers: DEMO-01 finite rehearsal generation/review/TTS; package-resource consumer.
- Resources: local Python stdlib; generation only requires already installed FFmpeg with Flite/slt.
- No provider calls, credentials, downloads, runtime TTS, added dependencies, or copied voice binaries.
- Unselected: real speakers, browser/device playback, intelligibility/listening, live providers,
  Chinese speech/quality and full 3–5 minute product acceptance are not validated here.

### DEMO02-001 Bounded explicit synthetic fixture inventory

Given an offline rehearsal installation, when the speech assets are inspected,
then exactly greeting/camera/photo/detail/absent/story/rain/warm ship with the
explicit synthetic English/no-listening disclosure. Every clip is under 30 seconds,
all clips total at most 90 seconds, and the story is long enough to exercise Stop.
The parent approved the larger total bound for the cohesive eight-scene script.

### DEMO02-002 Byte, sample, caption, and format integrity

Given each exact original English caption, when its generated asset is decoded,
then both raw PCM and WAV contain identical signed PCM16 little-endian mono samples
at 24 kHz. SHA-256 caption/audio hashes, frames, duration and signal statistics match;
the waveform is nonzero with no saturated samples. These checks do not establish
that the audio was heard or that pronunciation/intelligibility is acceptable.

### DEMO02-003 Reproducible and inspectable provenance

Given shipped assets, when provenance is inspected, then it records original script
authorship, installed local Flite/slt and FFmpeg version/library hashes, conversion,
license sources and a hash of the generator. No voice source/data/binary is copied.
The default verifier operates offline with Python alone; runtime speech never invokes it.

### DEMO02-004 Fail closed on asset or disclosure drift

Given damaged audio, changed captions, traversal filenames, or a false language claim,
when the verifier runs, then it returns nonzero instead of declaring asset integrity.
No corruption repair or missing tool can invoke cloud speech or a browser fallback.
