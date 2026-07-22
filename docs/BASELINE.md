# Baseline — 2026-07-22

The camera was intentionally disconnected during this inventory. `No cameras
available` is therefore expected and is not a fault diagnosis.

## Raspberry Pi

- Raspberry Pi 5 Model B Rev 1.0
- Debian GNU/Linux 13 (trixie), arm64
- Kernel `6.12.75+rpt-rpi-2712`
- `rpicam-apps` 1.11.1
- `libcamera` 0.7.0 Raspberry Pi build
- Picamera2 installed
- NumPy installed
- OpenCV not installed
- Temperature during inventory: 62 C
- Throttling flags: `0x0`

## Storage

- System boots from a 32 GB microSD card.
- Samsung SSD 980 1 TB NVMe is detected.
- The NVMe is not mounted.
- Its visible partitions are only 512 MB and 5.5 GB.
- The NVMe partitions duplicate the SD card's labels and filesystem UUIDs,
  indicating a partial/old clone. Do not auto-mount or write to it until its
  intended contents are established and repartitioning is explicitly approved.

## Network

- Direct Ethernet carrier: 1 Gbit/s full duplex
- Mac address during setup: `169.254.114.22/16`
- Pi address during setup: `169.254.114.23/16`
- SSH public-key authentication works for `user@169.254.114.23`
- The Pi address was assigned with `ip address add` and is not persistent

## Firmware configuration

`camera_auto_detect=1` is enabled. No sensor-specific overlay or custom camera
driver has been configured.

