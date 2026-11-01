"""
MJPEG Stream Receiver
High-speed multipart MJPEG client decoder with auto-reconnection and throughput calculation.
"""

import time
import threading
import urllib.request
import urllib.error
import logging
from typing import Optional, Callable

logger = logging.getLogger("MjpegReceiver")

JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


class MjpegReceiver:
    """Consumes multipart/x-mixed-replace MJPEG stream in a dedicated thread."""

    def __init__(
        self,
        video_url: str,
        on_frame: Callable[[bytes], None],
        on_status_change: Optional[Callable[[str], None]] = None,
        reconnect_delay: float = 2.0,
    ):
        self.video_url = video_url
        self.on_frame = on_frame
        self.on_status_change = on_status_change
        self.reconnect_delay = reconnect_delay

        self._running = False
        self._thread: Optional[threading.Thread] = None

        self.fps = 0.0
        self.bitrate_mbps = 0.0
        self.total_frames = 0

    def start(self):
        """Starts receiving stream in background."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="MjpegWorker")
        self._thread.start()

    def stop(self):
        """Stops stream receiver."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        if self.on_status_change:
            self.on_status_change("Disconnected")

    def update_url(self, new_url: str):
        """Updates target URL and restarts connection."""
        self.video_url = new_url
        if self._running:
            self.stop()
            self.start()

    def _run_loop(self):
        while self._running:
            try:
                if self.on_status_change:
                    self.on_status_change("Connecting...")

                req = urllib.request.Request(
                    self.video_url,
                    headers={
                        "User-Agent": "RemoteWebcamClient/1.0",
                        "Accept": "multipart/x-mixed-replace, image/jpeg",
                    },
                )

                with urllib.request.urlopen(req, timeout=5.0) as stream:
                    if self.on_status_change:
                        self.on_status_change("Connected")

                    buffer = bytearray()
                    fps_start = time.time()
                    fps_frames = 0
                    bytes_received = 0

                    while self._running:
                        chunk = stream.read(8192)
                        if not chunk:
                            break

                        buffer.extend(chunk)
                        bytes_received += len(chunk)

                        # Extract JPEG frames from buffer
                        while True:
                            soi_idx = buffer.find(JPEG_SOI)
                            if soi_idx == -1:
                                # Keep last byte in case SOI is split
                                buffer = buffer[-1:]
                                break

                            eoi_idx = buffer.find(JPEG_EOI, soi_idx + 2)
                            if eoi_idx == -1:
                                # Wait for more data to complete frame
                                if soi_idx > 0:
                                    del buffer[:soi_idx]
                                break

                            # Full JPEG frame extracted
                            jpeg_data = bytes(buffer[soi_idx : eoi_idx + 2])
                            del buffer[: eoi_idx + 2]

                            self.total_frames += 1
                            fps_frames += 1

                            # Dispatch frame callback
                            try:
                                self.on_frame(jpeg_data)
                            except Exception as e:
                                logger.error(f"Error in on_frame callback: {e}")

                        # Update metrics every second
                        now = time.time()
                        delta = now - fps_start
                        if delta >= 1.0:
                            self.fps = fps_frames / delta
                            self.bitrate_mbps = (bytes_received * 8) / (delta * 1_000_000)
                            fps_frames = 0
                            bytes_received = 0
                            fps_start = now

            except urllib.error.URLError as e:
                logger.warning(f"Connection error to {self.video_url}: {e.reason}")
                if self.on_status_change:
                    self.on_status_change(f"Connection lost: {e.reason}")
            except Exception as e:
                logger.warning(f"Stream exception: {e}")
                if self.on_status_change:
                    self.on_status_change(f"Error: {e}")

            if self._running:
                time.sleep(self.reconnect_delay)
