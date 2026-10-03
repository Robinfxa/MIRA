# MIRA offline rehearsal speech assets

Eight original English captions were synthesized locally with installed CMU
Flite's `slt` voice through FFmpeg. They are finite demo assets, not a live or
Chinese voice. The exact English captions and their hashes live only in
`apps/api/src/mira/adapters/generation/rehearsal/fixtures/audio/manifest.json`.
The rehearsal UI should show those captions and a visible synthetic-English label.

## What is included

- greeting, camera boundary, coast/lighthouse illustration, visible-picture detail,
  not-yet-visible picture, longer story, rain, and warm-light scenes.
- Each clip has raw signed little-endian PCM16 and a matching uncompressed WAV.
- Mono, 24,000 Hz; 52.560 seconds total. The story is 14.715 seconds for interruption.
- Total raw PCM: 2,522,880 bytes; matching WAVs: 2,523,232 bytes.
- Frame counts, rounded durations, signal statistics, caption hashes, file hashes,
  tool version, source library hashes, and provenance are in the single manifest.
- The exact illustration descriptions were reconciled to the existing coast and
  lighthouse scene. The script does not describe nonexistent mountains or cabins.

The parent accepted the cohesive eight-scene script with a total bound of 90 seconds,
replacing the initial 45-second planning limit. It does not imply a 3–5 minute
free-form conversation or satisfy the complete interactive product acceptance.
Stop itself does not trigger an extra spoken acknowledgement. Runtime selection
and playback are owned by the rehearsal adapter and the existing audio pipeline.

## Verify or reproduce

From the repository root, with a Python 3.11–3.13 interpreter:

```sh
python tools/generate_rehearsal_audio.py --check
python -m pytest tests/contracts/test_rehearsal_audio_assets.py -q
```

Checking only requires Python's standard library and the shipped assets. It does
not invoke FFmpeg, read `.env`, instantiate providers, or use credentials/network.
The application never invokes this build script at runtime.

To deliberately regenerate, the already installed Linux tools/libraries recorded
in the manifest must be present:

```sh
python tools/generate_rehearsal_audio.py --regenerate
```

The script reads the finite manifest's eight captions and runs `/usr/bin/ffmpeg`
with `flite=textfile=caption.txt:voice=slt`, gain 0.75, mono output and 24 kHz PCM16.
It applies no pitch or speech-rate manipulation. Caption text is passed through a
local temporary file, not a shell command or network request. No installation or
voice download occurs. Regeneration verifies staged output before writing assets,
then replaces the manifest last; interrupted writes therefore fail hash checks.
There is no fallback to browser TTS, silence, Google, or another provider.

The checked build used FFmpeg `7.1.5-0+deb13u1` and the installed `libflite.so.2.2`
and `libflite_cmu_us_slt.so.2.2`. The Flite version is supported by the library
SONAME; package-manager metadata was unavailable. See recorded SHA-256 values for
exact local binaries, not an assertion that every 2.2 build is byte-identical.
Two independent synthesis runs with those installed files produced identical
PCM/WAV bytes. Timestamps in regenerated manifests can differ; other tool builds
may produce different hashes and require deliberate fixture review.

## Provenance and license review

The captions were newly written for MIRA with AI assistance on 2026-10-03. Only
newly synthesized output is included; no external recording, Flite source, voice
model, or binary has been copied into this repository. The underlying synthetic
voice is CMU's installed `slt`, not an original voice recording or imitation of an
identified real person requested for this project.

Reviewed on 2026-10-03:

- Installed `/usr/share/doc/libflite1/copyright` (its hash is in the manifest).
- [Upstream Flite license](https://github.com/festvox/flite/blob/master/COPYING).
- [Upstream CMU slt voice definition and notice](https://github.com/festvox/flite/blob/master/lang/cmu_us_slt/cmu_us_slt.c).

The installed copyright notice and upstream voice source describe permissive CMU
software licensing, including use and distribution, with attribution/notice and
non-endorsement conditions on redistributed code. This package redistributes no
Flite software or voice data. No separate restriction on newly synthesized output
was found in these reviewed sources. That is a scoped provenance assessment, not
legal advice or an assertion of exclusive rights in the generated waveform.
CMU and the original authors do not endorse MIRA. No Flite or FFmpeg code was modified.

## Verified limits

Decoded sample/format integrity, nonzero signal, bounds, hashes, matching WAV/PCM,
and absence of saturated samples were checked. Positive and negative tests cover
silent/corrupted PCM, caption drift, traversal filenames and false Chinese-language
claims. Automated checks cannot prove audibility on a device, listening quality,
pronunciation, comprehension, synchronization, or Stop latency. No physical listening,
Chinese-voice evaluation, microphone use, or Google/Codex availability is claimed.

See [verification](verification.md) for exact run receipts and unexecuted checks.
