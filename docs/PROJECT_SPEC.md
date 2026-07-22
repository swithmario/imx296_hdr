# Project specification

## Objective

Build a reproducible Raspberry Pi 5 acquisition system that estimates a
time-varying scene-radiance field from sequential native RAW Bayer exposures
captured by the Arducam 261 global-shutter camera module.

The module is expected to use the Sony IMX296 sensor. The connected camera's
reported driver identity is authoritative; the project must fail closed if it
does not match the approved hardware profile.

The IMX477 rolling-shutter camera owned by the user is explicitly out of scope
for the first acquisition implementation.

## Measurement model

For photosite `(x, y)`, exposure `i`, and calibrated unity analogue gain:

```text
radiance_i(x, y) =
    response_scale(x, y)
    * (raw_i(x, y) - dark_i(x, y))
    / exposure_seconds_i
```

Only samples above the calibrated noise floor and below the calibrated
non-linear/saturation region are valid. The first merger selects the longest
valid exposure per photosite. A later merger may use variance-aware weighting.

The exposure images remain Bayer mosaics until after merging. Demosaicing,
colour correction, and display mapping are downstream operations.

## Exposure bracket

The user-facing controls are shutter angles relative to a 24 fps reference:

| Angle | Nominal exposure |
| ---: | ---: |
| 1 deg | 116 us |
| 10 deg | 1,157 us |
| 45 deg | 5,208 us |
| 90 deg | 10,417 us |
| 180 deg | 20,833 us |

These five integrations total about 37.731 ms, but that does **not** imply a
24 fps HDR output. Each exposure is a separate sensor frame, and readout,
blanking, control latency, and transition-frame rejection all contribute to
the cadence. Standard full-frame operation is expected to be limited by the
camera's reported mode; cropped experimental modes are a separate milestone.

## Acquisition invariants

Every accepted frame must record:

- run and HDR-group identifiers;
- requested shutter angle and derived exposure;
- actual `ExposureTime` metadata;
- actual analogue and digital gain metadata;
- sensor and host timestamps;
- request sequence number;
- sensor format, dimensions, stride, Bayer order, and packing;
- calibration-set identifiers;
- acceptance/rejection reason.

A requested exposure is never assumed to apply to the next frame. Transitional
frames are rejected until metadata confirms the requested exposure within a
measured tolerance.

## Outputs

1. **Acquisition master**: exact sensor integers plus synchronized metadata.
2. **Radiance master**: calibrated scene-linear Bayer and/or linear RGB data,
   initially in a relative scale and eventually in calibrated physical or
   colourimetric units.
3. **Display derivative**: an explicitly versioned view transform, such as an
   SDR preview or BT.2100/PQ HDR video. It is never the only retained output.

Absolute radiance cannot be claimed until the lens/sensor system is calibrated
against a traceable source. Until then, the correct term is stable relative
scene radiance.

## Milestones

### M0 — Host foundation (current)

- [x] Direct gigabit Ethernet and SSH-key access
- [x] Pi/OS/camera-stack baseline
- [x] Camera-independent project scaffold
- [ ] Persistent direct-link network configuration
- [ ] Resolve and mount/reformat the NVMe data volume with explicit approval

### M1 — Standard camera path

- [ ] Physically connect the camera while the Pi is powered off
- [ ] Record sensor identity, modes, controls, and media graph
- [ ] Capture one untouched RAW frame through supported Picamera2/libcamera
- [ ] Document meaningful bit depth, packing, stride, and Bayer order
- [ ] Prove manual exposure and unity-gain metadata

### M2 — Valid exposure groups

- [ ] Measure exposure-control latency
- [ ] Reject transitional frames by metadata
- [ ] Capture a valid five-exposure group
- [ ] Detect dropped/duplicated sequence numbers and timestamp discontinuities

### M3 — Calibration and single HDR reconstruction

- [ ] Dark/black and defective-pixel calibration
- [ ] Flat-field and vignetting calibration
- [ ] Exposure/gain linearity and saturation calibration
- [ ] Longest-valid-exposure Bayer merge
- [ ] Linear demosaiced preview

### M4 — Sustained radiance sequence

- [ ] Append-only chunked container with crash recovery
- [ ] NVMe throughput and thermal tests
- [ ] Ten-minute then one-hour endurance runs
- [ ] Measured HDR-group cadence and loss accounting

### M5 — High-speed sensor ROI research

- [ ] Reproduce a standard supported crop baseline
- [ ] Map kernel driver, media graph, and sensor crop controls
- [ ] Reproduce GScrop-compatible behaviour only in an isolated branch/system
- [ ] Verify unique-frame cadence rather than trusting requested FPS
- [ ] Quantify resolution, bit-depth, exposure, and stability trade-offs

Driver work is justified only by a documented limit in the supported user-space
path.

