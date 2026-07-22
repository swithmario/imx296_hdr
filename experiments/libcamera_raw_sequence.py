#!/usr/bin/python3
"""Capture a short full-resolution RAW10 sequence into RAM, then flush to disk."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mmap
import time
from pathlib import Path

import libcamera as libcam


class MappedPlane:
    """Map the single-plane RAW framebuffer exported by libcamera."""

    def __init__(self, buffer) -> None:
        plane = buffer.planes[0]
        self._map = mmap.mmap(
            plane.fd,
            plane.offset + plane.length,
            flags=mmap.MAP_SHARED,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
        )
        self.plane = memoryview(self._map)[
            plane.offset : plane.offset + plane.length
        ]

    def close(self) -> None:
        self.plane.release()
        self._map.close()


def set_manual_controls(request, exposure_us: int, frame_duration_us: int) -> None:
    request.set_control(libcam.controls.ExposureTimeMode, 1)
    request.set_control(libcam.controls.AnalogueGainMode, 1)
    request.set_control(libcam.controls.ExposureTime, exposure_us)
    request.set_control(libcam.controls.AnalogueGain, 1.0)
    request.set_control(
        libcam.controls.FrameDurationLimits,
        (frame_duration_us, frame_duration_us),
    )


def metadata_by_name(request) -> dict[str, object]:
    return {control.name: value for control, value in request.metadata.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=128)
    parser.add_argument("--discard", type=int, default=8)
    parser.add_argument("--short-us", type=int, default=93)
    parser.add_argument("--long-us", type=int, default=15_741)
    parser.add_argument("--frame-us", type=int, default=16_667)
    parser.add_argument("--buffers", type=int, default=4)
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    args = parser.parse_args()

    if args.frames <= args.discard:
        raise ValueError("frames must be greater than discard")
    retained = args.frames - args.discard
    if retained % 2:
        raise ValueError("the retained frame count must be even")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manager = libcam.CameraManager.singleton()
    if not manager.cameras:
        raise RuntimeError("no cameras detected")
    camera = manager.cameras[0]
    camera.acquire()

    allocator = None
    mapped = []
    captured: list[bytes] = []
    rows: list[dict[str, object]] = []
    stream_details: dict[str, object] = {}

    try:
        configuration = camera.generate_configuration([libcam.StreamRole.Raw])
        stream_configuration = configuration.at(0)
        stream_configuration.size = libcam.Size(1456, 1088)
        # Keep the generated sensor-native SRGGB10_CSI2P PixelFormat object.
        # Reconstructing it from its display string in the Python binding loses
        # format information and makes the PiSP validator choose compression.
        stream_configuration.buffer_count = args.buffers
        status = configuration.validate()
        if status == libcam.CameraConfiguration.Status.Invalid:
            raise RuntimeError("camera rejected RAW configuration")
        actual_pixel_format = str(stream_configuration.pixel_format)
        if "PISP_COMP" in actual_pixel_format or not actual_pixel_format.endswith("16"):
            raise RuntimeError(
                "RAW configuration is not uncompressed 16-bit Bayer: "
                f"{actual_pixel_format}"
            )
        if camera.configure(configuration) not in (None, 0):
            raise RuntimeError("camera configuration failed")

        stream_details = {
            "width": stream_configuration.size.width,
            "height": stream_configuration.size.height,
            "pixel_format": str(stream_configuration.pixel_format),
            "stride": stream_configuration.stride,
            "frame_size": stream_configuration.frame_size,
            "buffer_count": stream_configuration.buffer_count,
        }

        stream = stream_configuration.stream
        allocator = libcam.FrameBufferAllocator(camera)
        if allocator.allocate(stream) < 0:
            raise RuntimeError("buffer allocation failed")
        buffers = allocator.buffers(stream)
        if len(buffers) < args.buffers:
            raise RuntimeError("camera allocated fewer buffers than requested")

        requests = []
        exposures = (args.short_us, args.long_us)
        mapped_by_buffer = {}
        for index, buffer in enumerate(buffers[: args.buffers]):
            request = camera.create_request(index)
            if request is None:
                raise RuntimeError("request creation failed")
            if request.add_buffer(stream, buffer) not in (None, 0):
                raise RuntimeError("request buffer attachment failed")
            set_manual_controls(request, exposures[index % 2], args.frame_us)
            requests.append(request)
            mfb = MappedPlane(buffer)
            mapped.append(mfb)
            mapped_by_buffer[buffer] = mfb

        if camera.start() not in (None, 0):
            raise RuntimeError("camera start failed")

        capture_started = time.monotonic()
        try:
            for request in requests:
                if camera.queue_request(request) not in (None, 0):
                    raise RuntimeError("initial request queue failed")

            completed = 0
            previous_timestamp = None
            while completed < args.frames:
                deadline = time.monotonic() + 2.0
                ready_requests = []
                while not ready_requests and time.monotonic() < deadline:
                    ready_requests = manager.get_ready_requests()
                    if not ready_requests:
                        time.sleep(0.001)
                if not ready_requests:
                    raise TimeoutError("camera request timed out")

                for request in ready_requests:
                    if completed >= args.frames:
                        break
                    if request.status != libcam.Request.Status.Complete:
                        raise RuntimeError(f"request failed: {request.status}")

                    metadata = metadata_by_name(request)
                    timestamp = int(metadata.get("SensorTimestamp", 0))
                    buffer = request.buffers[stream]
                    bytes_used = int(buffer.metadata.planes[0].bytes_used)
                    plane = mapped_by_buffer[buffer].plane
                    frame = bytes(plane[:bytes_used])

                    if completed >= args.discard:
                        retained_index = completed - args.discard
                        captured.append(frame)
                        rows.append(
                            {
                                "index": retained_index,
                                "sensor_sequence": request.sequence,
                                "cookie": request.cookie,
                                "requested_us": exposures[request.cookie % 2],
                                "actual_us": metadata.get("ExposureTime"),
                                "frame_us": metadata.get("FrameDuration"),
                                "sensor_timestamp_ns": timestamp,
                                "delta_us": ""
                                if previous_timestamp is None
                                else round((timestamp - previous_timestamp) / 1000),
                                "bytes_used": bytes_used,
                            }
                        )
                        previous_timestamp = timestamp

                    completed += 1
                    if completed >= args.frames:
                        continue

                    request.reuse()
                    requested = exposures[request.cookie % 2]
                    set_manual_controls(request, requested, args.frame_us)
                    if camera.queue_request(request) not in (None, 0):
                        raise RuntimeError("request requeue failed")
        finally:
            camera.stop()
        capture_elapsed = time.monotonic() - capture_started
    finally:
        for mfb in mapped:
            mfb.close()
        allocator = None
        camera.release()

    raw_path = args.output_dir / "frames.raw10"
    digest = hashlib.sha256()
    offsets = []
    offset = 0
    with raw_path.open("wb") as output:
        for frame in captured:
            offsets.append(offset)
            output.write(frame)
            digest.update(frame)
            offset += len(frame)

    for row, frame_offset in zip(rows, offsets):
        row["byte_offset"] = frame_offset

    csv_path = args.output_dir / "frames.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "camera_id": camera.id,
        "stream": stream_details,
        "capture": {
            "captured_frames": args.frames,
            "discarded_startup_frames": args.discard,
            "retained_frames": len(captured),
            "hdr_pairs": len(captured) // 2,
            "requested_short_us": args.short_us,
            "requested_long_us": args.long_us,
            "requested_sensor_frame_us": args.frame_us,
            "capture_elapsed_s": capture_elapsed,
        },
        "raw_file": {
            "name": raw_path.name,
            "bytes": offset,
            "sha256": digest.hexdigest(),
        },
        "metadata_file": csv_path.name,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
