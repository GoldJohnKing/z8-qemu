# Testing

```sh
python tests/run.py
python tools/audit_source.py
python tools/audit_privacy.py --history
```

The source suite checks Python syntax, CLI entry points, local imports,
synthetic ROM generation and sparse-card copying. It compiles the region,
serial, timed-single and lossless-encoding contracts with strict warnings and tests the actual
display scanout and overlay functions against bounded mock RAM with address
and undefined-behavior sanitizers.

Lossless checks cover a fixed known bitstream, every signed difference category,
Bayer predictor parity, padded input rows, unchanged inputs and output-capacity
rejection under address and undefined-behavior sanitizers. The audit regression
rejects the former 80,017,920-byte packed payload under the compressed RAW tag.

Renderer checks cover four framebuffer banks, valid-fetch active latching,
rejected addresses, region positioning and clipping, palette banks, partial
alpha, transparency and invalid DMA or stride rejection.

A complete macOS QEMU 11.1.1 build, native boot and menu navigation, and
single NEF capture have passed with fresh synthetic sensor and card inputs.
LibRaw and Adobe DNG Converter independently decoded all 45,705,600 RAW samples
with zero mismatches against the sensor input and guest producer buffer. All
three JPEG previews also decoded. LibRaw’s packed-size fallback is explicitly
excluded before accepting the Nikon lossless payload. The
read-only card audit passed. Source integration is repeatable. Linux runtime
qualification, repeated shooting and post-shot recovery remain separate work.

For runtime acceptance, record firmware, binary and input hashes. Check
preparation callbacks, ready notification, shutter consumption, full-frame
DMA, single completion, capture drain, initialized card files, independent
RAW and preview decoding, and process shutdown. Repeated or burst operation
and post-shot recovery require additional validation.

`source-manifest.json` records the source inventory and fingerprints.
`tools/audit_source.py` detects mismatches and unexpected files outside `.git`,
`.local`, Python cache directories and macOS `.DS_Store` metadata. Refresh the manifest when intentionally
editing source. Keep runtime inputs and outputs outside tracked files.

The [Z63 backport validation](z63-backport.md#validation-on-20-october-2026)
separates host contracts, actual-board MMIO and original Z8 guest acceptance.
The production timed-single test supersedes the older copied C timing model.
Run the complete host suite with `python -m unittest discover -s tests -p 'test_*.py' -v`.

Privacy tests check redacted pattern findings, removed historical content,
historical payload names, and manifest-only runtime packaging. The packager
excludes unlisted files, verifies source hashes before copying, and rejects
symlinks, path traversal and non-source payloads. These controls supplement
manual review of documentation, PR text, logs and published artifacts; they do
not guarantee that every private fact matches a pattern. History checking needs
a full clone; the source CI job fetches complete history for that check.

The optional [read-only tracing plugin](../plugins/README.md) has a separate
firmware-free runtime check against the actual QEMU plugin ABI:

```sh
python3 tests/check_trace_plugin.py --qemu /path/to/qemu-system-aarch64 \
  --plugin /path/to/libz8trace.dylib --output .local/new-trace-check
```

Its 48 checks cover synthetic A53/M4 execution, argument/store values, filtering,
bounds and rejected configurations. Host tests validate launcher profiles; source
CI does not load an external plugin binary. Native macOS checks separately cover
trace selection, restart, stopped-log retention and the unconfigured disabled state.

`tests/check_mcu_adc.py` separately executes synthetic M4 ADC conversions on the
actual board. Diagnostic ZIP host tests cover exact binary log copies, fixed
allowlist exclusion, limits, nonregular inputs, source changes, cancellation and
no-replace publication. Native Save-dialog/completion checks remain separate.

The syscon-semaphore fixture has its own firmware-free runtime check:

```sh
python3 tests/check_syscon_semaphore.py --qemu /path/to/qemu-system-aarch64 \
  --output .local/new-semaphore-check
```

Its 17 checks copy load instructions into the low service RAM so one load sits
exactly at the measured acquire pc 0x082013d4, then call it with controlled
registers: with `syscon-semaphore-model` on, the acquire-pc load of 0x0d151404
reads retained|1 and logs exactly one grant, while the same load at another pc,
the neighbor word at the acquire pc and a byte-wide read at the acquire pc do
not grant; with the property unset the acquire-pc load reads the retained word
unchanged and no grant appears. With `syscon-semaphore-trace` on, the fixture
enables the EL3 MMU with identity tables that leave two 4KiB translation holes,
so one `Z8_VDUMP` covers both failure shapes -- the module window fails
mid-dump after successful reads and the taskstack starts in a hole -- and no
FAIL line carries payload bytes (the check rejects the build that reprinted
stale chunk bytes under FAIL). These checks pin the grant's exact gate; they
do not model semaphore semantics beyond the single acquired load.

`tests/check_mcu_panel.py` executes synthetic PA1/EXTI1 and SPI2 transfers through
the actual board. Its 13 checks distinguish Z8's 144×168 geometry from the
reference model, including gates 1/168 and the eighteenth data byte, with
partial/invalid/unselected negatives. Host PNG/HTTP and production-JavaScript
checks cover display blanking, bounds, capability, image versions and retained
pixels on disconnection. Original EX drawing and native UI remain separate
runtime acceptance.

RTC alarm/wake delivery has a separate firmware-free runtime check:

```sh
python3 tests/check_mcu_rtc.py --qemu /path/to/qemu-system-aarch64 \
  --output .local/new-rtc-check
```

Its sixteen checks execute synthetic M4 handlers through RTC, EXTI and NVIC,
including timing, flag clearing with WPR locked and retention across a
guest-requested MCU-only reset. The locked-handler fixture rejects the earlier
binary that retained the event flag after its first interrupt. Native
power-on recovery remains a separate original-firmware acceptance gate.

STOP clock gating and the optional supply controller have separate actual-board
checks, each using independent synthetic programs:

```sh
python3 tests/check_mcu_stop.py --qemu /path/to/qemu-system-aarch64 \
  --output .local/new-stop-check
python3 tests/check_main_supply.py --qemu /path/to/qemu-system-aarch64 \
  --output .local/new-supply-check
```

The twelve STOP checks use guest-recorded timer/interrupt values rather than
host scheduling to establish clock isolation. The twenty-four supply checks
include two cycles and the default unconnected negative control. Neither suite
qualifies physical pin-to-rail wiring or original-firmware operation by itself.

The whitelisted switch-candidate pin alias has its own actual-board suite:

```sh
python3 tests/check_switch_candidate.py --qemu /path/to/qemu-system-aarch64 \
  --output .local/new-switch-candidate-check
```

The seventy-one checks configure the measured stock-EX pull pattern, then
drive every whitelisted candidate through `mcu-switch-candidate` /
`mcu-switch-candidate-pin` and read it back through the EX IDR: assert
and release-to-pull for all six candidates, the default-pin path, hand-
back on switch and deassert, spelling canonicalization, whitelist
rejection, default-off and the native-MCU-attachment requirement. A
second boot runs the same sequence against an existing generic
`mcu-pins` drive (B11=0:C5=1): selecting and switching while the alias
is off touch nothing, an un-listed candidate is released on deassert,
and a listed one has its generic level restored instead of the alias
idle level. The first boot also walks the incremental-update review
case: two separate runtime `mcu-pins` sets (B11=0, then C5=1) accumulate,
and a borrow cycle over PB11 hands back to the accumulated low drive,
not to the pull state the last spec string would suggest; repeated
assignments within one spec (B11=1,B11=0) leave the last value in
hardware and on hand-back; a runtime mcu-pins set re-takes a borrowed
pin and the hand-back keeps the newer drive; a rejected spec with a
valid prefix leaves the hand-back on what applied rather than the
retained string; and a creation-time borrow over a machine-time generic
drive deasserts back to that drive. The suite establishes the alias
wiring and its ownership rule only; which candidate carries which switch
meaning stays unresolved.


`tests/check_lpcm.py --qemu /path/to/qemu-system-aarch64 --output .local/new-lpcm-check`
uses only synthetic data on the actual board. Its 190 assertions cover the
explicit RAM aperture, all four PCM byte-width modes, original mailbox
ownership and IRQ wires, malformed/unmapped inputs and reset cancellation.
Run it again with a fresh output directory and `--disabled` for the three
checks of the default-off boot gate. These checks do not establish recording,
physical sample packing or native Movie playback.

Sparse-card tests compare complete cloned/derived partition bytes and reject
buffered extent scans. Extent queries change the underlying descriptor offset,
so all sparse source reads use unbuffered files. A filesystem audit and media
decoding are separate checks; neither implies the other.

The source suite also compiles `tests/verify_hevc_tier.c` against the installed
GLib, x264 and x265 development libraries. It checks actual VPS/SPS bytes for
both HEVC tiers at levels 5.1 and 5.2, including the emulation-prevention bytes, and
rejects invalid level/tier combinations. This covers encoder header signaling;
native Movie parser admission and decoded playback require separate runs.

`python3 tests/check_general_dma.py --qemu /path/to/qemu-system-aarch64 --output .local/new-general-dma-check`
loads only synthetic RAM. Its 17 checks cover an identity transfer, an exact
192,192-byte disjoint copy, canaries and status acknowledgement. Forward and
backward partial overlaps, unmapped endpoints, an oversized identity span and
an invalid source mode must leave memory unchanged and produce no completion.
An identity transfer uses the same checked memory reads/writes as an ordinary
copy. These checks do not establish native Movie playback or physical DMA timing.

The opt-in saved-Movie decoder uses installed FFmpeg development libraries
(`libavcodec` and `libavutil`). `tests/verify_video_decode.c` generates lossless
HEVC and AVC streams from declared pixels and checks every decoded sample,
parser drain and input bounds. It runs in the source suite.

The actual-board regression requires an installed `ffmpeg` with `libx265`:

```sh
python3 tests/check_video_decode.py --qemu /path/to/qemu-system-aarch64 \
  --output .local/new-video-decode-check
```

Its 457 checks generate their own 30-frame lossless stream. They verify actual
RAM CRCs against the original pixels, row padding/canaries, absent auxiliary
metadata, submission/completion timestamps, a programmed four-entry command
queue, genuine queue-full rejection, display/reference backpressure, real
stream end, replay and cancellation of all queued work by flush/reset. No
Nikon inputs or saved media are required. Native workflow acceptance remains
separate from these synthetic checks.

`tests/check_video_playback.py` additionally needs NumPy. Its 44 actual-board
checks generate a 4K lossless pattern, verify NV12 plane bytes and independent
resize coordinates, preserve destination canaries and invalidate stale leases.
Frame delivery reports input `0x11` plus the completed writer cause; only the
subsequent explicit STOP reports `0x10000`. Flush/reset cancel blocked decoder
work without a later DMA or interrupt. This keeps Movie frame and STOP
ownership separate from the existing JPEG/NV16 contract.

`tests/check_video_decode_disabled.py` needs no media generator. Its seven
checks verify encoder-only advertised capabilities, immutable default-off
decoding, rejected decoder creation, no instance, no DMA and no completion.

Diagnostic-export cancellation includes the staging-creation window. SIGTERM
sets a cancellation flag; the exporter checks it after entering the staging
cleanup scope and between copy chunks, before atomic publication. A test
requests cancellation immediately after the staging directory is created,
verifying that it is removed and neither the source log nor destination changes.


Audio output and repeated program loading have separate firmware-free actual-board checks:

```sh
python3 tests/check_audio_tx.py --qemu /path/to/qemu-system-aarch64 --output .local/new-audio-tx
python3 tests/check_host_audio_output.py --qemu /path/to/qemu-system-aarch64 --output .local/new-host-audio
python3 tests/check_backend_program.py --qemu /path/to/qemu-system-aarch64 --output .local/new-program-check
```

The 83 DMA assertions cover legacy and paired requests, actual source bytes,
phase order, precise prefill/sample deadlines, cancellation, invalid descriptors
and immutable boot mapping. The 22 host-output assertions check the paired
stereo route and single-lane mono duplication — every guest sample once per
channel, tone frequency preserved — with stereo 48-kHz WAV samples and file
closure; `--backend auto` instead performs seventeen backend
admission/ownership checks on the current host. The 53 program assertions
exercise eight reset/replacement epochs, retained opaque words, no invented
pixels/completions and strict default-off overflow. Native repeated workflows
remain a separate gate. Publication checks reject WAV and raw PCM captures in
tracked files and reachable history.
