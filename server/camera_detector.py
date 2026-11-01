"""
Camera Detector Module
Discovers all internal laptop webcams and external USB webcams on Linux via V4L2 and sysfs.
"""

import os
import glob
import fcntl
import struct
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger("CameraDetector")

# V4L2 ioctl definitions
VIDIOC_QUERYCAP = 0x80685600
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_DEVICE_CAPS = 0x80000000


@dataclass
class CameraInfo:
    index: int
    path: str
    name: str
    camera_type: str  # 'internal' or 'external_usb'
    card_name: str
    display_name: str
    driver: str = ""
    bus_info: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CameraDetector:
    """Discovers and classifies video capture devices on Linux."""

    COMMON_INTERNAL_KEYWORDS = [
        "integrated", "easycamera", "facetime", "internal",
        "built-in", "laptop", "truevision", "front camera"
    ]

    @staticmethod
    def _is_capture_device(device_path: str) -> tuple[bool, str, str, str]:
        """
        Queries V4L2 capability to check if the device actually supports video capture.
        Returns: (is_capture, driver_name, card_name, bus_info)
        """
        try:
            fd = os.open(device_path, os.O_RDWR | os.O_NONBLOCK)
            buf = bytearray(104)
            fcntl.ioctl(fd, VIDIOC_QUERYCAP, buf)
            os.close(fd)

            driver_raw, card_raw, bus_raw, version, caps, dev_caps, _ = struct.unpack(
                "16s32s32sIII12s", buf
            )

            driver = driver_raw.split(b"\x00")[0].decode("utf-8", "ignore").strip()
            card = card_raw.split(b"\x00")[0].decode("utf-8", "ignore").strip()
            bus = bus_raw.split(b"\x00")[0].decode("utf-8", "ignore").strip()

            effective_caps = dev_caps if (caps & V4L2_CAP_DEVICE_CAPS) else caps
            is_capture = bool(effective_caps & V4L2_CAP_VIDEO_CAPTURE)

            return is_capture, driver, card, bus
        except Exception as e:
            logger.debug(f"Could not query {device_path}: {e}")
            return False, "", "", ""

    @staticmethod
    def _determine_type(device_name: str, card_name: str) -> str:
        """
        Determines whether a device is an internal laptop webcam or external USB camera.
        Uses sysfs 'removable' attribute and device tree inspection.
        """
        sysfs_dev = f"/sys/class/video4linux/{device_name}/device"
        if os.path.exists(sysfs_dev):
            real_path = os.path.realpath(sysfs_dev)
            curr = real_path
            while curr and curr != "/":
                removable_path = os.path.join(curr, "removable")
                if os.path.exists(removable_path):
                    try:
                        val = open(removable_path, "r").read().strip().lower()
                        if val == "fixed":
                            return "internal"
                        elif val == "removable":
                            return "external_usb"
                    except Exception:
                        pass
                curr = os.path.dirname(curr)

        # Fallback to card name heuristic
        card_lower = card_name.lower()
        for kw in CameraDetector.COMMON_INTERNAL_KEYWORDS:
            if kw in card_lower:
                return "internal"

        return "external_usb"

    @classmethod
    def detect_cameras(cls) -> List[CameraInfo]:
        """
        Scans all /dev/video* devices and returns verified video capture cameras.
        """
        cameras: List[CameraInfo] = []
        device_paths = sorted(
            glob.glob("/dev/video*"),
            key=lambda x: int(os.path.basename(x).replace("video", ""))
            if os.path.basename(x).replace("video", "").isdigit()
            else 999,
        )

        for dev_path in device_paths:
            dev_name = os.path.basename(dev_path)
            if not dev_name.replace("video", "").isdigit():
                continue

            index = int(dev_name.replace("video", ""))
            is_capture, driver, card, bus = cls._is_capture_device(dev_path)

            if not is_capture:
                continue

            card_clean = card or f"Camera {index}"
            cam_type = cls._determine_type(dev_name, card_clean)

            type_label = "Internal Webcam" if cam_type == "internal" else "External USB Webcam"
            display_name = f"{type_label} [{card_clean}] ({dev_path})"

            cameras.append(
                CameraInfo(
                    index=index,
                    path=dev_path,
                    name=card_clean,
                    camera_type=cam_type,
                    card_name=card_clean,
                    display_name=display_name,
                    driver=driver,
                    bus_info=bus,
                )
            )

        logger.info(f"Discovered {len(cameras)} capture cameras: {[c.display_name for c in cameras]}")
        return cameras

    @classmethod
    def get_camera_by_index(cls, index: int) -> Optional[CameraInfo]:
        """Retrieves camera info for a specific camera index."""
        cameras = cls.detect_cameras()
        for cam in cameras:
            if cam.index == index:
                return cam
        return None
