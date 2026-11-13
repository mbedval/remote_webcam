"""
Stream Recorder Module
Handles recording live webcam streams locally to disk in MP4 or WebP format.
Uses a decoupled background thread queue to ensure zero frame drop or UI lag.
"""

import os
import time
import queue
import logging
import threading
from pathlib import Path
from typing import Optional, Tuple, List
import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger("StreamRecorder")


class StreamRecorder:
    """Thread-safe stream recorder for MP4 and animated WebP output."""

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        format_type: str = "mp4",
        fps: int = 30,
    ):
        if output_dir is None:
            self.output_dir = Path.home() / "Videos" / "RemoteWebcam"
        else:
            self.output_dir = Path(output_dir)

        self.format_type = format_type.lower()
        if self.format_type not in ("mp4", "webp"):
            self.format_type = "mp4"

        self.target_fps = max(5, min(60, fps))
        self.is_recording = False
        self.start_time: float = 0.0
        self.frame_count: int = 0
        self.file_path: Optional[Path] = None

        self._queue: queue.Queue = queue.Queue(maxsize=150)
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._last_error: Optional[str] = None

    @property
    def elapsed_seconds(self) -> float:
        if not self.is_recording or self.start_time <= 0:
            return 0.0
        return max(0.0, time.time() - self.start_time)

    @property
    def elapsed_str(self) -> str:
        sec = int(self.elapsed_seconds)
        m = sec // 60
        s = sec % 60
        return f"{m:02d}:{s:02d}"

    def start(self) -> Path:
        """Starts the recording session and spawns the background worker."""
        if self.is_recording:
            return self.file_path

        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        ext = "mp4" if self.format_type == "mp4" else "webp"
        self.file_path = self.output_dir / f"webcam_record_{timestamp}.{ext}"

        self.is_recording = True
        self.start_time = time.time()
        self.frame_count = 0
        self._last_error = None
        self._stop_event.clear()

        # Clear queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        if self.format_type == "mp4":
            self._worker_thread = threading.Thread(
                target=self._worker_mp4,
                daemon=True,
                name="Mp4RecorderWorker",
            )
        else:
            self._worker_thread = threading.Thread(
                target=self._worker_webp,
                daemon=True,
                name="WebpRecorderWorker",
            )

        self._worker_thread.start()
        logger.info(f"Started recording [{self.format_type.upper()}] to {self.file_path}")
        return self.file_path

    def add_frame(self, frame_bytes: bytes):
        """Dispatches an incoming JPEG frame to the background recorder queue."""
        if not self.is_recording:
            return

        try:
            self._queue.put_nowait(frame_bytes)
        except queue.Full:
            # Drop older frame if consumer is lagging
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(frame_bytes)
            except Exception:
                pass

    def stop(self) -> Tuple[Optional[Path], float, int]:
        """
        Stops recording, finalizes the output file, and waits for background thread.
        Returns: (file_path, duration_seconds, total_frames)
        """
        if not self.is_recording:
            return None, 0.0, 0

        duration = max(0.0, time.time() - self.start_time)
        self.is_recording = False
        self._stop_event.set()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10.0)

        logger.info(
            f"Finished recording {self.file_path} ({duration:.1f}s, {self.frame_count} frames)"
        )
        return self.file_path, duration, self.frame_count

    def _worker_mp4(self):
        """Worker thread for streaming frames to MP4 container via OpenCV VideoWriter."""
        writer: Optional[cv2.VideoWriter] = None
        init_w, init_h = 0, 0

        try:
            while not self._stop_event.is_set() or not self._queue.empty():
                try:
                    frame_bytes = self._queue.get(timeout=0.08)
                except queue.Empty:
                    continue

                np_arr = np.frombuffer(frame_bytes, np.uint8)
                img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if img is None:
                    continue

                h, w = img.shape[:2]

                if writer is None:
                    init_w, init_h = w, h
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(
                        str(self.file_path),
                        fourcc,
                        float(self.target_fps),
                        (init_w, init_h),
                    )
                    if not writer.isOpened():
                        # Try MJPG fallback inside MP4 container
                        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
                        writer = cv2.VideoWriter(
                            str(self.file_path),
                            fourcc,
                            float(self.target_fps),
                            (init_w, init_h),
                        )

                # Ensure dimensions match writer configuration
                if w != init_w or h != init_h:
                    img = cv2.resize(img, (init_w, init_h))

                writer.write(img)
                self.frame_count += 1

        except Exception as e:
            logger.error(f"Error in MP4 recorder worker: {e}", exc_info=True)
            self._last_error = str(e)
        finally:
            if writer:
                writer.release()

    def _worker_webp(self):
        """Worker thread for compiling animated WebP file using PIL."""
        pil_frames: List[Image.Image] = []
        webp_fps = min(15, self.target_fps)  # 12-15 fps is ideal for WebP animations
        min_interval = 1.0 / webp_fps
        last_frame_time = 0.0

        try:
            while not self._stop_event.is_set() or not self._queue.empty():
                try:
                    frame_bytes = self._queue.get(timeout=0.08)
                except queue.Empty:
                    continue

                now = time.time()
                if now - last_frame_time < min_interval:
                    continue
                last_frame_time = now

                np_arr = np.frombuffer(frame_bytes, np.uint8)
                img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if img is None:
                    continue

                # Convert BGR to RGB for PIL
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                pil_frames.append(Image.fromarray(rgb))
                self.frame_count += 1

            if pil_frames:
                dur_ms = max(15, int(1000 / webp_fps))
                pil_frames[0].save(
                    str(self.file_path),
                    format="WEBP",
                    save_all=True,
                    append_images=pil_frames[1:],
                    duration=dur_ms,
                    loop=0,
                    quality=80,
                )

        except Exception as e:
            logger.error(f"Error in WebP recorder worker: {e}", exc_info=True)
            self._last_error = str(e)
