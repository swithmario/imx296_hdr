# libcamera patch

Apply `imx296-hdr-alt.patch` to Raspberry Pi libcamera tag
`v0.7.0+rpt20260205`, configure a separate Meson build directory, and run that
build through process-local library and IPA search paths.

The patch is deliberately gated by `LIBCAMERA_RPI_IMX296_HDR_ALT` and the
sensor model string `imx296`. Without both conditions, normal behaviour is
unchanged.

For fixed-exposure calibration frames, `LIBCAMERA_RPI_IMX296_RAW16=1` enables
only the lossless unpacked RAW transport. It does not override the requested
exposure or alternate sensor controls.

The current exposure-line constants are 66 and 1000. With the IMX296 helper's
timing model these produce metadata exposures of about 992 µs and 14,829 µs.
Requested microseconds remain in the capture manifest, while actual metadata
values are authoritative.

`LIBCAMERA_RPI_IMX296_HDR5=1` selects a separate monotonic five-exposure
scheduler using 12, 53, 269, 1079, and 4386 sensor lines. The verified metadata
exposures are 192, 799, 3,999, 15,999, and 64,992 µs. It requires a sensor frame
duration of at least 67 ms and therefore yields about 2.985 merged frames per
second when every five sequential measurements form one HDR frame.
