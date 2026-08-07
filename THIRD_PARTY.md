# Third-party material

## Raspberry Pi libcamera patch

`patches/imx296-hdr-alt.patch` modifies these files from Raspberry Pi
libcamera tag `v0.7.0+rpt20260205`:

- `src/libcamera/pipeline/rpi/common/pipeline_base.cpp`
- `src/libcamera/pipeline/rpi/pisp/pisp.cpp`

Both upstream files contain the SPDX identifier `LGPL-2.1-or-later` and a
Raspberry Pi Ltd copyright notice. The patch remains under
LGPL-2.1-or-later. A copy of that licence is in
`patches/LICENSE-LGPL-2.1-or-later.txt`.

Upstream source: https://github.com/raspberrypi/libcamera/tree/v0.7.0%2Brpt20260205

The original project code outside the patch has no open-source licence. See
`COPYRIGHT.md`.
