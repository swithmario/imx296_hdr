# IMX296 full-resolution alternating-exposure RAW HDR

This repository records a working software-only HDR experiment on a Raspberry
Pi 5 and an Arducam 261 camera enumerating as Sony IMX296. It captures two
sequential full-resolution native Bayer measurements for each output frame:

- 1456×1088 at approximately 60 sensor frames/s;
- alternating approximately 1 ms and 14.8 ms exposures;
- 30 exposure pairs/s;
- RAW10 sensor codes retained losslessly in little-endian 16-bit containers;
- actual exposure and sensor timestamp verified from per-frame metadata;
- separate short- and long-exposure source arrays, plus an optional merged
  30 fps preview.

The MP4 is only a viewable derivative. The interleaved RAW master and its two
split source arrays are the measurement deliverables.

## Why a small libcamera patch is required

On `libcamera 0.7.0+rpt20260205`, ordinary Picamera2 and request-level
libcamera controls did not sustain per-frame exposure alternation. Controls
passed through shared AGC state before the delayed sensor-control queue and
eventually collapsed to one exposure. The opt-in IMX296-only patch applies the
two exposures at that delayed-control boundary, keyed by frame context. It also
selects uncompressed `SBGGR16` transport instead of PiSP's usual proprietary
8-bit compressed RAW transport.

The experiment is enabled only when:

```bash
export LIBCAMERA_RPI_IMX296_HDR_ALT=1
```

Build the patch against Raspberry Pi's exact
`v0.7.0+rpt20260205` libcamera tag and run the resulting libraries through
process-local `LD_LIBRARY_PATH`/IPA paths. Do not replace the system camera
stack. The patch and build notes are in `patches/`.

## Capture

`experiments/libcamera_raw_sequence.py` captures into RAM first and flushes to
disk after the camera stops, so storage and network traffic cannot stall the
sensor. A typical two-second run retains 120 frames after startup:

```bash
python3 experiments/libcamera_raw_sequence.py \
  --frames 128 --discard 8 --short-us 1000 --long-us 15000 \
  --frame-us 16667 --buffers 4 --output-dir RUN_DIR
```

The patch quantizes those requests to the sensor's actual 992 µs and 14,829 µs
exposures. Trust `frames.csv`, not the requested values. A valid 120-frame run
has 60 frames at each exposure, no repeated adjacent exposure, and sensor
timestamp intervals close to 16,667 µs.

Split the interleaved master into untouched short and long arrays:

```bash
python3 tools/split_raw_sequence.py RUN_DIR
```

## HDR merge and tone mapping

`tools/merge_hdr_sequence.py` works in the Bayer domain. It subtracts RAW10
black code 60 and divides each measurement by its metadata exposure time to
form linear radiance estimates. It prefers the cleaner long exposure, then
cross-fades from long to short as the long RAW code rises from 820 to 980.

The preview then uses a bilinear BGGR demosaic, fixed white balance, a fixed
3×3 colour-correction matrix, and a global white point taken from the first
merged frame's 99.5th percentile. Exposure is scaled to that white point, a
Reinhard curve `x / (1 + x)` compresses highlights, and the result is encoded
to sRGB and H.264. There is no local tone mapping or temporal adaptation.
This MP4 is a viewing convenience only, not the scientific output.

```bash
python3 tools/merge_hdr_sequence.py RUN_DIR
```

## Linear radiance output

The measurement product follows the radiometric order explicitly:

1. interpolate a per-pixel virtual dark at the frame's actual metadata exposure;
2. subtract it from the measurement in native Bayer space;
3. divide the result by actual exposure time in seconds;
4. retain float32 Bayer samples, including negative noise excursions.

No demosaic, clamp, white balance, colour matrix, gamma, tone curve, or video
encoding is applied. Alternating exposure pairs may be fused with a saturation
cross-fade after both sources have independently reached linear radiance units.

```bash
python3 tools/calibrate_linear_radiance.py RUN_DIR DARK_LIBRARY_DIR
```

The output is little-endian float32 BGGR Bayer radiance in RAW10 counts per
second. Untouched calibrated sources, optional fused pairs, hashes, and exact
processing metadata are recorded under `linear_radiance/`.

For independent stills rather than a stream, `scripts/capture_still_bracket.sh`
captures one retained RAW image per 1–2–5 exposure point from 1 ms through
10 seconds. Each point has its own metadata and hash and can be passed to the
same calibration tool independently.

Stack calibrated stills into one linear HDR Bayer radiance mosaic with an
explicit clipped-sample mask:

```bash
python3 tools/stack_linear_radiance.py STILL_BRACKET_DIR
```

Every native RAW10 value at code 1023 is replaced by `NaN` before merging. The
output is an exposure-squared weighted mean of finite radiance samples only;
clipped samples have exactly zero influence. This favours cleaner long samples
where they remain valid and lets short samples take over clipped highlights.
Pass `--weighting uniform` when an unweighted finite mean is specifically
required. The stack remains float32 BGGR counts/second and
is written both as a self-describing float32 TIFF and as a headerless `.raw32f`
computational array. A 16-bit TIFF contributor map records the finite sample
count at every Bayer pixel.

Export every bracket RAW and calibrated still to TIFF, plus a merged 48-bit
linear RGB TIFF, with:

```bash
python3 tools/export_still_bracket_tiffs.py STILL_BRACKET_DIR
```

The exporter also creates commonly scaled 16-bit linear Bayer viewing copies.
Those copies use one global multiplicative white scale only—no gamma or tone
curve—while the float32 physical-units TIFFs remain unchanged.

It additionally writes demosaiced 48-bit colour previews for every calibrated
still and the merged stack. Preview mapping uses one shared RGB interval from
the 0.01st to 99.99th percentile, discarding the bottom and top 0.01% so hot
pixels cannot consume the display range. Values inside that interval are mapped
strictly affinely across all three channels. It performs no per-channel
normalization, gamma, or tone curve.

Apply the project's measured IMX296 RGB gains and 3x3 colour-response matrix to
an existing NaN-masked stack with:

```bash
python3 tools/render_colour_response.py STILL_BRACKET_DIR
```

This creates both an exact full-range affine preview and a more useful shared
0.1–99.9% linear-window preview. They are explicitly viewing derivatives; the
underlying Bayer radiance master is not changed. Neither uses gamma, a tone
curve, or per-channel normalization. It also creates a display-only tone-mapped
TIFF using positive-value exposure scaling, Reinhard highlight compression,
and the sRGB display transfer function; all tone-map parameters are recorded in
`colour_response_preview.json`. Reinhard is applied to luminance once, not to
the three channels independently. Chroma remains a Cartesian direction from
the neutral axis and is contracted only enough to intersect the valid
constant-luminance section of the display RGB cube. This removes highlight
colour coordinate singularities without changing the scene-radiance geometry.

## Dark-frame calibration library

Dark signal depends on pixel, exposure, analogue gain, and sensor temperature.
Keep gain fixed at 1.0 and record temperature with each set. A useful initial
grid is a 1–2–5 sequence per decade:

```text
1, 2, 5, 10, 20, 50, 100, 200, 500, 1000 ms
```

Capture at least 10 RAW frames per point with the lens cap fitted, preserving
individual frames as well as their average. For a target such as 55 ms,
interpolate each pixel between the bracketing 50 ms and 100 ms masters. With a
larger library, fitting each pixel as offset plus dark-current slope versus
exposure is generally more stable than unconstrained extrapolation. Hot pixels
may need a separate mask or robust mean.

Long dark exposures require a sensor frame duration longer than the exposure;
they cannot be collected in the fixed 60 fps HDR stream. Calibration capture
therefore runs as a separate still/slow-sequence mode.

Capture the full grid on the Pi with `scripts/capture_dark_library.sh`. After
mirroring the run, build float32 mean masters and synthesize a virtual dark:

```bash
python3 tools/build_dark_library.py DARK_RUN_DIR
python3 tools/synthesize_dark.py DARK_RUN_DIR 55000 virtual_55000us.raw32f
```

Interpolation uses actual metadata exposure times rather than nominal folder
names and refuses extrapolation beyond the calibrated range.

## Hardware and safety

Verified target: Raspberry Pi 5, IMX296, 1456×1088 RAW10. No external trigger,
GPIO, soldering, wiring, boot changes, kernel changes, or system-wide libcamera
installation is required or used.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Capture files are intentionally excluded by `.gitignore`; publish hashes and
small metadata manifests separately if a run needs to be cited.
