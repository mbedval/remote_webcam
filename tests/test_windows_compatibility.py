"""
Windows & Cross-Platform Compatibility Test Suite
Validates that Remote Webcam runs seamlessly on both Linux and Windows.
Tests fcntl fallback, DirectShow camera backend selection, Windows device enumeration,
cross-platform audio streaming, and Windows launcher scripts.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import cv2

from server.camera_detector import CameraDetector, CameraInfo
from server.capture_manager import CaptureManager
from server.audio_streamer import AudioStreamer
from client.recorder import StreamRecorder


class TestWindowsCompatibility(unittest.TestCase):
    def setUp(self):
        CameraDetector.clear_cache()

    def test_camera_detector_without_fcntl(self):
        """Verifies CameraDetector operates safely without Unix-only fcntl module."""
        with patch("server.camera_detector.fcntl", None):
            is_cap, drv, card, bus = CameraDetector._is_capture_device("/dev/video0")
            self.assertFalse(is_cap)
            self.assertEqual(drv, "")
            self.assertEqual(card, "")
            self.assertEqual(bus, "")

    def test_windows_camera_detection_dispatch(self):
        """Verifies that on Windows, detect_cameras routes to _detect_windows_cameras."""
        mock_cameras = [
            CameraInfo(
                index=0,
                path="video0",
                name="HD Web Camera",
                camera_type="external_usb",
                card_name="HD Web Camera",
                display_name="External USB Webcam [HD Web Camera] (Device 0)",
                driver="DirectShow",
            )
        ]

        with patch("sys.platform", "win32"):
            with patch.object(CameraDetector, "_detect_windows_cameras", return_value=mock_cameras) as mock_win:
                with patch.object(CameraDetector, "get_adb_devices", return_value=[]):
                    cams = CameraDetector.detect_cameras()
                    mock_win.assert_called_once()
                    self.assertEqual(len(cams), 1)
                    self.assertEqual(cams[0].name, "HD Web Camera")
                    self.assertEqual(cams[0].driver, "DirectShow")

    def test_windows_directshow_open_camera(self):
        """Verifies that CaptureManager uses DirectShow (cv2.CAP_DSHOW) on Windows."""
        mgr = CaptureManager(camera_index=0, resolution="480p", target_fps=30)

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, None)

        with patch("sys.platform", "win32"):
            with patch("cv2.VideoCapture", return_value=mock_cap) as mock_vc:
                cap = mgr._open_camera(0)
                self.assertIsNotNone(cap)
                # Verify cv2.VideoCapture was called with cv2.CAP_DSHOW (700)
                mock_vc.assert_any_call(0, cv2.CAP_DSHOW)

    def test_windows_audio_streamer(self):
        """Verifies that AudioStreamer adapts to Windows without ALSA arecord dependency."""
        with patch("sys.platform", "win32"):
            with patch("shutil.which", return_value=None):
                # When ffmpeg is not installed, it should gracefully report unavailable
                self.assertFalse(AudioStreamer.is_available())
                # Should not raise exception
                chunks = list(AudioStreamer.iter_audio_pcm())
                self.assertEqual(len(chunks), 0)

            with patch("shutil.which", return_value="C:\\ffmpeg\\bin\\ffmpeg.exe"):
                self.assertTrue(AudioStreamer.is_available())

    def test_windows_launchers_exist(self):
        """Verifies that Windows .bat and .ps1 launchers exist and contain correct commands."""
        root_dir = Path(__file__).resolve().parent.parent

        bat_server = root_dir / "run_server.bat"
        bat_client = root_dir / "run_client.bat"
        ps_server = root_dir / "run_server.ps1"
        ps_client = root_dir / "run_client.ps1"

        self.assertTrue(bat_server.exists(), "run_server.bat must exist")
        self.assertTrue(bat_client.exists(), "run_client.bat must exist")
        self.assertTrue(ps_server.exists(), "run_server.ps1 must exist")
        self.assertTrue(ps_client.exists(), "run_client.ps1 must exist")

        bat_server_content = bat_server.read_text(encoding="utf-8")
        self.assertIn("python server.py", bat_server_content)

        bat_client_content = bat_client.read_text(encoding="utf-8")
        self.assertIn("python client.py", bat_client_content)


if __name__ == "__main__":
    unittest.main()
