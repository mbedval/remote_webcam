"""
Capture Manager Module
High-performance, multi-client webcam streamer using OpenCV and Android ADB relay.
Decoupled background capture loop with thread-safe MJPEG generation,
dynamic camera switching (internal <-> USB <-> Android phone), resolution scaling, and HUD metrics.
"""

import time
import threading
import logging
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, Generator, Tuple
import cv2
import numpy as np

from .camera_detector import CameraDetector, CameraInfo

logger = logging.getLogger("CaptureManager")

JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


class CaptureManager:
    """Manages webcam & phone capture, dynamic switching, and multi-client frame dispatch."""

    RESOLUTIONS: Dict[str, Tuple[int, int]] = {
        "480p": (640, 480),
        "720p": (1280, 720),
        "1080p": (1920, 1080),
        "360p": (640, 360),
    }

    def __init__(
        self,
        camera_index: int = 0,
        resolution: str = "720p",
        target_fps: int = 30,
        jpeg_quality: int = 80,
    ):
        self.camera_index = camera_index
        self.resolution_name = resolution if resolution in self.RESOLUTIONS else "720p"
        self.target_width, self.target_height = self.RESOLUTIONS[self.resolution_name]
        self.target_fps = max(5, min(60, target_fps))
        self.jpeg_quality = max(10, min(100, jpeg_quality))

        self.flip_horizontal = False
        self.flip_vertical = False

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

        self._cap: Optional[cv2.VideoCapture] = None
        self._current_frame_bytes: Optional[bytes] = None
        self._current_raw_frame: Optional[np.ndarray] = None
        self._frame_count = 0
        self._last_frame_time = time.time()
        self._measured_fps = 0.0
        self._start_time = time.time()

        self._active_viewers = 0
        self._switching_camera = False

        # Detect initial camera info
        self.cameras = CameraDetector.detect_cameras()
        self.current_camera_info = self._find_camera_info(self.camera_index)

    def _find_camera_info(self, index: int) -> Optional[CameraInfo]:
        for cam in self.cameras:
            if cam.index == index:
                return cam
        return None

    @property
    def is_android_camera(self) -> bool:
        return self.camera_index >= 100 or (
            self.current_camera_info and self.current_camera_info.camera_type == "android_phone"
        )

    def start(self):
        """Starts the background capture thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._start_time = time.time()
            self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="WebcamCapture")
            self._thread.start()
        logger.info(f"CaptureManager started for camera index {self.camera_index}")

    def stop(self):
        """Stops capture and releases camera hardware."""
        with self._lock:
            self._running = False
            self._condition.notify_all()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        with self._lock:
            if self._cap:
                self._cap.release()
                self._cap = None
        logger.info("CaptureManager stopped")

    def _create_placeholder(self, lines: list[str]) -> bytes:
        """Generates a neat placeholder frame when camera is loading or disconnected."""
        img = np.zeros((self.target_height, self.target_width, 3), dtype=np.uint8)
        img[:] = (26, 29, 36)  # Dark slate background

        # Draw border
        cv2.rectangle(img, (10, 10), (self.target_width - 10, self.target_height - 10), (45, 52, 64), 2)

        font = cv2.FONT_HERSHEY_SIMPLEX
        y_start = self.target_height // 2 - (len(lines) * 25)
        for i, text in enumerate(lines):
            font_scale = 0.75 if i == 0 else 0.6
            thickness = 2 if i == 0 else 1
            color = (255, 255, 255) if i == 0 else (160, 175, 200)
            text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
            tx = (self.target_width - text_size[0]) // 2
            ty = y_start + (i * 45)
            cv2.putText(img, text, (tx, ty), font, font_scale, color, thickness, cv2.LINE_AA)

        _, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return enc.tobytes()

    def _open_camera(self, index: int) -> Optional[cv2.VideoCapture]:
        """Attempts to open a V4L2 camera by index and sets optimal properties."""
        if index >= 100:
            return None  # Android camera handled via HTTP/ADB stream

        logger.info(f"Opening camera /dev/video{index}...")
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap = cv2.VideoCapture(index)

        if not cap.isOpened():
            logger.error(f"Failed to open camera /dev/video{index}")
            return None

        try:
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        except Exception:
            pass

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.target_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.target_height)
        cap.set(cv2.CAP_PROP_FPS, self.target_fps)

        for _ in range(3):
            ret, _ = cap.read()
            if ret:
                break
            time.sleep(0.05)

        return cap

    def _capture_loop(self):
        """Dedicated background capture loop."""
        fps_timer = time.time()
        fps_frame_count = 0

        while self._running:
            if self._switching_camera:
                time.sleep(0.05)
                continue

            # Case A: Android Phone Stream (via ADB port forward http://127.0.0.1:8088/video)
            if self.is_android_camera:
                phone_port = 8088 + (self.camera_index - 100)
                phone_url = f"http://127.0.0.1:{phone_port}/video"
                try:
                    req = urllib.request.Request(phone_url, headers={"User-Agent": "RemoteWebcamServer"})
                    with urllib.request.urlopen(req, timeout=3.0) as stream:
                        buffer = bytearray()
                        while self._running and not self._switching_camera:
                            chunk = stream.read(8192)
                            if not chunk:
                                break
                            buffer.extend(chunk)

                            while True:
                                soi = buffer.find(JPEG_SOI)
                                if soi == -1:
                                    buffer = buffer[-1:]
                                    break
                                eoi = buffer.find(JPEG_EOI, soi + 2)
                                if eoi == -1:
                                    if soi > 0:
                                        del buffer[:soi]
                                    break

                                frame_jpeg = bytes(buffer[soi : eoi + 2])
                                del buffer[: eoi + 2]

                                with self._condition:
                                    self._current_frame_bytes = frame_jpeg
                                    self._frame_count += 1
                                    fps_frame_count += 1
                                    self._condition.notify_all()

                                now = time.time()
                                if now - fps_timer >= 1.0:
                                    self._measured_fps = fps_frame_count / (now - fps_timer)
                                    fps_frame_count = 0
                                    fps_timer = now

                except Exception as e:
                    # Phone stream not ready or app not broadcasting
                    card_name = self.current_camera_info.name if self.current_camera_info else "Android Phone"
                    placeholder = self._create_placeholder([
                        f"📱 {card_name} Connected",
                        "Open 'Smart Mobile Cam' on your phone",
                        "and tap 'Start Server' (Broadcaster Mode)",
                    ])
                    with self._condition:
                        self._current_frame_bytes = placeholder
                        self._condition.notify_all()
                    time.sleep(1.0)
                continue

            # Case B: Local V4L2 Webcam
            loop_start = time.time()

            if not self._cap or not self._cap.isOpened():
                placeholder = self._create_placeholder([f"Camera {self.camera_index} Disconnected. Retrying..."])
                with self._condition:
                    self._current_frame_bytes = placeholder
                    self._condition.notify_all()
                time.sleep(1.0)
                self._cap = self._open_camera(self.camera_index)
                continue

            ret, frame = self._cap.read()
            if not ret or frame is None:
                time.sleep(0.05)
                continue

            # Flips
            if self.flip_horizontal and self.flip_vertical:
                frame = cv2.flip(frame, -1)
            elif self.flip_horizontal:
                frame = cv2.flip(frame, 1)
            elif self.flip_vertical:
                frame = cv2.flip(frame, 0)

            # Resize if needed
            h, w = frame.shape[:2]
            if w != self.target_width or h != self.target_height:
                frame = cv2.resize(frame, (self.target_width, self.target_height), interpolation=cv2.INTER_AREA)

            # JPEG encode
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            success, enc_bytes = cv2.imencode(".jpg", frame, encode_params)
            if not success:
                continue

            raw_jpeg = enc_bytes.tobytes()

            with self._condition:
                self._current_raw_frame = frame
                self._current_frame_bytes = raw_jpeg
                self._frame_count += 1
                fps_frame_count += 1
                self._condition.notify_all()

            now = time.time()
            if now - fps_timer >= 1.0:
                self._measured_fps = fps_frame_count / (now - fps_timer)
                fps_frame_count = 0
                fps_timer = now

            elapsed = time.time() - loop_start
            sleep_duration = (1.0 / self.target_fps) - elapsed
            if sleep_duration > 0.001:
                time.sleep(sleep_duration)

    def switch_camera(self, target_index: Optional[int] = None) -> bool:
        """Dynamically switches camera between internal webcam, USB webcam, and Android phone."""
        self.cameras = CameraDetector.detect_cameras()
        if not self.cameras:
            logger.warning("No cameras available to switch to")
            return False

        if target_index is None:
            indices = [c.index for c in self.cameras]
            if self.camera_index in indices:
                next_idx = indices[(indices.index(self.camera_index) + 1) % len(indices)]
            else:
                next_idx = indices[0]
            target_index = next_idx

        if target_index == self.camera_index:
            return True

        logger.info(f"Switching from camera {self.camera_index} to {target_index}...")

        with self._condition:
            self._switching_camera = True
            placeholder = self._create_placeholder([f"Switching to Camera {target_index}..."])
            self._current_frame_bytes = placeholder
            self._condition.notify_all()

        try:
            if self._cap:
                self._cap.release()
                self._cap = None

            self.camera_index = target_index
            self.current_camera_info = self._find_camera_info(target_index)

            if not self.is_android_camera:
                self._cap = self._open_camera(target_index)
                success = self._cap is not None and self._cap.isOpened()
            else:
                success = True  # Handled in capture loop
        finally:
            with self._condition:
                self._switching_camera = False

        return success

    def set_resolution(self, resolution: str) -> bool:
        if resolution not in self.RESOLUTIONS:
            return False
        self.resolution_name = resolution
        w, h = self.RESOLUTIONS[resolution]
        self.target_width, self.target_height = w, h
        if self._cap and self._cap.isOpened():
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        return True

    def set_fps(self, fps: int):
        self.target_fps = max(5, min(60, fps))
        if self._cap and self._cap.isOpened():
            self._cap.set(cv2.CAP_PROP_FPS, self.target_fps)

    def set_quality(self, quality: int):
        self.jpeg_quality = max(10, min(100, quality))

    def toggle_flip_h(self) -> bool:
        self.flip_horizontal = not self.flip_horizontal
        return self.flip_horizontal

    def toggle_flip_v(self) -> bool:
        self.flip_vertical = not self.flip_vertical
        return self.flip_vertical

    def get_snapshot(self) -> Optional[bytes]:
        with self._lock:
            return self._current_frame_bytes

    def iter_mjpeg_frames(self) -> Generator[bytes, None, None]:
        with self._lock:
            self._active_viewers += 1

        try:
            last_sent_count = -1
            while self._running:
                with self._condition:
                    while self._running and self._frame_count == last_sent_count:
                        self._condition.wait(timeout=0.1)

                    if not self._running:
                        break

                    frame_bytes = self._current_frame_bytes
                    last_sent_count = self._frame_count

                if frame_bytes:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(frame_bytes)).encode("ascii") + b"\r\n\r\n"
                        + frame_bytes + b"\r\n"
                    )
        finally:
            with self._lock:
                self._active_viewers = max(0, self._active_viewers - 1)

    def get_status(self, host: str = "0.0.0.0", port: int = 8080) -> Dict[str, Any]:
        cam_info = self.current_camera_info or self._find_camera_info(self.camera_index)
        facing_label = "Internal Webcam"
        cam_name = f"Camera {self.camera_index}"
        if cam_info:
            cam_name = cam_info.name
            if cam_info.camera_type == "internal":
                facing_label = "Internal Webcam"
            elif cam_info.camera_type == "android_phone":
                facing_label = "Android Phone Camera"
            else:
                facing_label = "External USB Webcam"

        return {
            "isRunning": self._running,
            "ipAddress": host,
            "port": port,
            "activeViewers": self._active_viewers,
            "fps": round(self._measured_fps, 1),
            "targetFps": self.target_fps,
            "resolution": self.resolution_name,
            "width": self.target_width,
            "height": self.target_height,
            "facing": facing_label,
            "activeCameraIndex": self.camera_index,
            "activeCameraName": cam_name,
            "uptimeSeconds": int(time.time() - self._start_time),
            "flipHorizontal": self.flip_horizontal,
            "flipVertical": self.flip_vertical,
            "jpegQuality": self.jpeg_quality,
            "cameras": [c.to_dict() for c in CameraDetector.detect_cameras()],
        }
