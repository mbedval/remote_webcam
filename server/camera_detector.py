"""
Camera Detector Module
Discovers all internal laptop webcams, external USB webcams via V4L2/sysfs,
and connected Android smartphones via USB ADB.
"""

import os
import glob
import fcntl
import struct
import shutil
import subprocess
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
    camera_type: str  # 'internal', 'external_usb', or 'android_phone'
    card_name: str
    display_name: str
    driver: str = ""
    bus_info: str = ""
    serial: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CameraDetector:
    """Discovers and classifies local video devices and connected Android devices."""

    COMMON_INTERNAL_KEYWORDS = [
        "integrated", "easycamera", "facetime", "internal",
        "built-in", "laptop", "truevision", "front camera"
    ]

    @staticmethod
    def _is_capture_device(device_path: str) -> tuple[bool, str, str, str]:
        """Queries V4L2 capability to check if the device supports video capture."""
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
        """Determines whether a device is an internal laptop webcam or external USB camera."""
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

        # Fallback heuristic
        card_lower = card_name.lower()
        for kw in CameraDetector.COMMON_INTERNAL_KEYWORDS:
            if kw in card_lower:
                return "internal"

        return "external_usb"

    @classmethod
    def get_adb_devices(cls) -> List[Dict[str, str]]:
        """Detects Android devices connected with ADB debugging enabled."""
        if not shutil.which("adb"):
            return []

        try:
            res = subprocess.check_output(["adb", "devices", "-l"], timeout=2).decode("utf-8", "ignore")
            devices = []
            for line in res.strip().split("\n")[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    serial = parts[0]
                    model = "Android Device"
                    for p in parts[2:]:
                        if p.startswith("model:"):
                            model = p.split(":", 1)[1]
                    devices.append({"serial": serial, "model": model})
            return devices
        except Exception as e:
            logger.debug(f"ADB device scan error: {e}")
            return []

    @classmethod
    def setup_adb_forward(cls, serial: str, local_port: int = 8088, phone_port: int = 8080) -> bool:
        """Sets up port forwarding over USB via ADB."""
        try:
            cmd = ["adb", "-s", serial, "forward", f"tcp:{local_port}", f"tcp:{phone_port}"]
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info(f"ADB port forward established: localhost:{local_port} -> phone:{phone_port} ({serial})")
            return True
        except Exception as e:
            logger.warning(f"Failed to set up ADB port forward for {serial}: {e}")
            return False

    @classmethod
    def detect_cameras(cls) -> List[CameraInfo]:
        """
        Scans all /dev/video* devices and connected ADB Android phones.
        """
        cameras: List[CameraInfo] = []
        device_paths = sorted(
            glob.glob("/dev/video*"),
            key=lambda x: int(os.path.basename(x).replace("video", ""))
            if os.path.basename(x).replace("video", "").isdigit()
            else 999,
        )

        # 1. Local V4L2 cameras (internal & USB webcams)
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

        # 2. Connected Android Phones via ADB
        adb_devices = cls.get_adb_devices()
        for idx, dev in enumerate(adb_devices):
            phone_index = 100 + idx
            serial = dev["serial"]
            model = dev["model"]
            cls.setup_adb_forward(serial, local_port=8088 + idx, phone_port=8080)

            cameras.append(
                CameraInfo(
                    index=phone_index,
                    path=f"adb://{serial}",
                    name=f"Android Cam ({model})",
                    camera_type="android_phone",
                    card_name=f"Android {model}",
                    display_name=f"📱 Android Phone [{model}] (USB: {serial})",
                    driver="adb_bridge",
                    bus_info=f"usb-adb-{serial}",
                    serial=serial,
                )
            )

        logger.info(f"Discovered {len(cameras)} total video sources: {[c.display_name for c in cameras]}")
        return cameras

    @classmethod
    def get_camera_by_index(cls, index: int) -> Optional[CameraInfo]:
        """Retrieves camera info for a specific camera index."""
        cameras = cls.detect_cameras()
        for cam in cameras:
            if cam.index == index:
                return cam
        return None
