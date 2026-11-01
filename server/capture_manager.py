"""
Capture Manager Module
High-performance, multi-client webcam streamer using OpenCV.
Decoupled background capture loop with thread-safe MJPEG generation,
dynamic camera switching (internal <-> USB), resolution scaling, and HUD metrics.
"""

import time
import threading
import logging
from typing import Optional, Dict, Any, Generator, Tuple
import cv2
import numpy as np

from .camera_detector import CameraDetector, CameraInfo

logger = logging.getLogger("CaptureManager")


class CaptureManager:
    """Manages webcam capture, dynamic switching, and multi-client frame dispatch."""

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

    def _create_placeholder(self, text: str) -> bytes:
        """Generates a neat placeholder frame when camera is loading or disconnected."""
        img = np.zeros((self.target_height, self.target_width, 3), dtype=np.uint8)
        img[:] = (26, 29, 36)  # Dark slate background

        # Draw border
        cv2.rectangle(img, (10, 10), (self.target_width - 10, self.target_height - 10), (45, 52, 64), 2)

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.8
        thickness = 2
        text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
        tx = (self.target_width - text_size[0]) // 2
        ty = (self.target_height + text_size[1]) // 2

        cv2.putText(img, text, (tx, ty), font, font_scale, (220, 220, 230), thickness, cv2.LINE_AA)
        _, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return enc.tobytes()

    def _open_camera(self, index: int) -> Optional[cv2.VideoCapture]:
        """Attempts to open a V4L2 camera by index and sets optimal properties."""
        logger.info(f"Opening camera /dev/video{index}...")
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if not cap.isOpened():
            # Fallback without CAP_V4L2 flag
            cap = cv2.VideoCapture(index)

        if not cap.isOpened():
            logger.error(f"Failed to open camera /dev/video{index}")
            return None

        # Request MJPG fourcc for USB webcams to allow higher resolutions and frame rates
        try:
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        except Exception:
            pass

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.target_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.target_height)
        cap.set(cv2.CAP_PROP_FPS, self.target_fps)

        # Warm up: read one frame
        for _ in range(3):
            ret, _ = cap.read()
            if ret:
                break
            time.sleep(0.05)

        return cap

    def _capture_loop(self):
        """Dedicated background capture loop."""
        self._cap = self._open_camera(self.camera_index)
        fps_timer = time.time()
        fps_frame_count = 0

        while self._running:
            loop_start = time.time()

            if self._switching_camera:
                time.sleep(0.05)
                continue

            if not self._cap or not self._cap.isOpened():
                placeholder = self._create_placeholder(f"Camera {self.camera_index} Disconnected. Retrying...")
                with self._condition:
                    self._current_frame_bytes = placeholder
                    self._condition.notify_all()
                time.sleep(1.0)
                self._cap = self._open_camera(self.camera_index)
                continue

            ret, frame = self._cap.read()
            if not ret or frame is None:
                logger.warning(f"Failed to grab frame from camera {self.camera_index}")
                time.sleep(0.1)
                continue

            # Apply flips if configured
            if self.flip_horizontal and self.flip_vertical:
                frame = cv2.flip(frame, -1)
            elif self.flip_horizontal:
                frame = cv2.flip(frame, 1)
            elif self.flip_vertical:
                frame = cv2.flip(frame, 0)

            # Resize if camera hardware output doesn't match requested resolution
            h, w = frame.shape[:2]
            if w != self.target_width or h != self.target_height:
                frame = cv2.resize(frame, (self.target_width, self.target_height), interpolation=cv2.INTER_AREA)

            # Encode to JPEG
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

            # Calculate FPS window
            now = time.time()
            if now - fps_timer >= 1.0:
                self._measured_fps = fps_frame_count / (now - fps_timer)
                fps_frame_count = 0
                fps_timer = now

            # Throttle to target FPS
            elapsed = time.time() - loop_start
            sleep_duration = (1.0 / self.target_fps) - elapsed
            if sleep_duration > 0.001:
                time.sleep(sleep_duration)

    def switch_camera(self, target_index: Optional[int] = None) -> bool:
        """
        Dynamically switches to another internal or external USB camera.
        If target_index is None, cycles to the next available camera.
        """
        self.cameras = CameraDetector.detect_cameras()
        if not self.cameras:
            logger.warning("No cameras available to switch to")
            return False

        if target_index is None:
            # Cycle next
            indices = [c.index for c in self.cameras]
            if self.camera_index in indices:
                next_idx = indices[(indices.index(self.camera_index) + 1) % len(indices)]
            else:
                next_idx = indices[0]
            target_index = next_idx

        if target_index == self.camera_index and self._cap and self._cap.isOpened():
            return True

        logger.info(f"Switching from camera {self.camera_index} to {target_index}...")

        with self._condition:
            self._switching_camera = True
            # Show temporary transition placeholder
            placeholder = self._create_placeholder(f"Switching to Camera {target_index}...")
            self._current_frame_bytes = placeholder
            self._condition.notify_all()

        try:
            if self._cap:
                self._cap.release()
                self._cap = None

            self.camera_index = target_index
            self.current_camera_info = self._find_camera_info(target_index)
            self._cap = self._open_camera(target_index)
            success = self._cap is not None and self._cap.isOpened()
        finally:
            with self._condition:
                self._switching_camera = False

        return success

    def set_resolution(self, resolution: str) -> bool:
        """Dynamically updates resolution (e.g. '480p', '720p', '1080p')."""
        if resolution not in self.RESOLUTIONS:
            return False

        self.resolution_name = resolution
        w, h = self.RESOLUTIONS[resolution]
        self.target_width, self.target_height = w, h

        if self._cap and self._cap.isOpened():
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

        logger.info(f"Resolution set to {resolution} ({w}x{h})")
        return True

    def set_fps(self, fps: int):
        """Sets target streaming FPS."""
        self.target_fps = max(5, min(60, fps))
        if self._cap and self._cap.isOpened():
            self._cap.set(cv2.CAP_PROP_FPS, self.target_fps)

    def set_quality(self, quality: int):
        """Sets JPEG compression quality (1-100)."""
        self.jpeg_quality = max(10, min(100, quality))

    def toggle_flip_h(self) -> bool:
        self.flip_horizontal = not self.flip_horizontal
        return self.flip_horizontal

    def toggle_flip_v(self) -> bool:
        self.flip_vertical = not self.flip_vertical
        return self.flip_vertical

    def get_snapshot(self) -> Optional[bytes]:
        """Returns the latest full-resolution JPEG frame."""
        with self._lock:
            return self._current_frame_bytes

    def iter_mjpeg_frames(self) -> Generator[bytes, None, None]:
        """
        Yields multipart MJPEG frames for HTTP StreamingResponse.
        Multiple clients can consume this generator concurrently.
        """
        with self._lock:
            self._active_viewers += 1

        try:
            last_sent_count = -1
            while self._running:
                with self._condition:
                    # Wait for a new frame
                    while self._running and self._frame_count == last_sent_count:
                        self._condition.wait(timeout=0.1)

                    if not self._running:
                        break

                    frame_bytes = self._current_frame_bytes
                    last_sent_count = self._frame_count

                if frame_bytes:
                    # Yield multipart JPEG chunk
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
        """Returns server status dictionary formatted for SmartCam compatibility."""
        cam_info = self.current_camera_info or self._find_camera_info(self.camera_index)
        facing_label = "Internal Webcam"
        cam_name = f"Camera {self.camera_index}"
        if cam_info:
            cam_name = cam_info.name
            facing_label = "Internal Webcam" if cam_info.camera_type == "internal" else "External USB Webcam"

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
