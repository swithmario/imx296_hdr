# Architecture

```text
IMX296-compatible sensor
        |
        | native RAW Bayer + request metadata
        v
capture process ----> bounded buffer pool ----> append-only acquisition writer
        |                                           |
        |                                           v
        +----> acceptance state machine        NVMe acquisition master
                  |                                  |
                  | metadata confirms exposure      v
                  v                           offline calibration/merge
             HDR group index                          |
                                                     v
                                            scene-linear radiance master
                                                     |
                                      +--------------+--------------+
                                      |                             |
                                      v                             v
                               scientific analysis          display transform
                                                                    |
                                                                    v
                                                          SDR or BT.2100/PQ
```

## Process boundaries

The capture callback performs no image processing and no per-frame allocation.
It transfers ownership of a request/buffer descriptor into a bounded queue. If
the writer cannot keep up, the run records an explicit loss condition rather
than silently blocking camera delivery.

The exposure controller is a metadata-driven state machine:

```text
request exposure -> observe frames -> metadata matches -> accept one frame
       ^                    |                                |
       |                    +-- mismatch: reject ------------+
       +------------- advance to next bracket entry <--------+
```

The acquisition path preserves sensor values exactly. Dark subtraction,
unpacking into `uint16`, floating-point normalization, alignment, HDR merging,
and demosaicing are offline stages until sustained capture is proven.

## Container direction

The prototype may save one RAW payload plus one JSON record per frame because
that is easy to inspect. Continuous capture should use an append-only,
chunked container or binary data stream with a separate recoverable index.
HDF5/Zarr are candidates, but the selection will be benchmarked on the Pi/NVMe
with representative RAW10 payloads before being fixed.

## High-frame-rate work

The supported full-frame path and experimental crop path remain separate:

- Standard path: current Raspberry Pi kernel, libcamera, Picamera2, RAW stream.
- Experimental path: sensor-level vertical crop/register work, potentially
  derived from GScrop, isolated so kernel/driver changes cannot invalidate the
  scientific baseline.

Every FPS claim requires sensor timestamps, sequence continuity, adjacent-frame
uniqueness checks, and a sustained-duration result.

