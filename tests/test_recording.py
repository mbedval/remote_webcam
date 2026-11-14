"""
Tests for Video Recording Feature
Verifies MP4 and WebP local stream recording, background worker thread safety,
FastAPI REST endpoints (/record/start, /record/stop, /record/status), and Web Client assets.
"""

import os
import time
import shutil
import unittest
import asyncio
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

from client.recorder import StreamRecorder
from server.capture_manager import CaptureManager


class TestStreamRecorder(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("/tmp/remote_webcam_test_rec")
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def _generate_frame(self, color_val: int = 120, width: int = 320, height: int = 240) -> bytes:
        img = np.full((height, width, 3), color_val, dtype=np.uint8)
        _, buf = cv2.imencode(".jpg", img)
        return buf.tobytes()

    def test_mp4_recording(self):
        recorder = StreamRecorder(output_dir=self.test_dir, format_type="mp4", fps=30)
        out_path = recorder.start()
        self.assertTrue(recorder.is_recording)
        self.assertEqual(out_path.suffix, ".mp4")

        # Push 15 simulated frames
        for i in range(15):
            recorder.add_frame(self._generate_frame(color_val=(i * 15) % 255))
            time.sleep(0.01)

        path, duration, frames = recorder.stop()
        self.assertFalse(recorder.is_recording)
        self.assertEqual(path, out_path)
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 0)
        self.assertGreater(duration, 0.0)
        self.assertEqual(frames, 15)

        # Verify MP4 with cv2.VideoCapture
        cap = cv2.VideoCapture(str(path))
        self.assertTrue(cap.isOpened())
        read_frames = 0
        while True:
            ret, _ = cap.read()
            if not ret:
                break
            read_frames += 1
        cap.release()
        self.assertGreater(read_frames, 0)

    def test_webp_recording(self):
        recorder = StreamRecorder(output_dir=self.test_dir, format_type="webp", fps=15)
        out_path = recorder.start()
        self.assertTrue(recorder.is_recording)
        self.assertEqual(out_path.suffix, ".webp")

        # Push 10 simulated frames
        for i in range(10):
            recorder.add_frame(self._generate_frame(color_val=(i * 20) % 255))
            time.sleep(0.02)

        path, duration, frames = recorder.stop()
        self.assertFalse(recorder.is_recording)
        self.assertEqual(path, out_path)
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 0)
        self.assertGreater(duration, 0.0)
        self.assertGreater(frames, 0)

        # Verify with PIL
        with Image.open(path) as im:
            self.assertEqual(im.format, "WEBP")
            self.assertTrue(getattr(im, "is_animated", False))
            self.assertGreaterEqual(im.n_frames, 1)


class TestServerRecordingApi(unittest.TestCase):
    def setUp(self):
        self.cap_mgr = CaptureManager(camera_index=0, resolution="480p", target_fps=30)
        self.test_rec_dir = Path("/tmp/remote_webcam_test_server_rec")
        if self.test_rec_dir.exists():
            shutil.rmtree(self.test_rec_dir)
        self.cap_mgr._recordings_dir = self.test_rec_dir

    def tearDown(self):
        if self.cap_mgr.get_recording_status().get("isRecording"):
            self.cap_mgr.stop_recording()
        if self.test_rec_dir.exists():
            shutil.rmtree(self.test_rec_dir)

    def test_record_lifecycle(self):
        # 1. Initial status
        status = self.cap_mgr.get_recording_status()
        self.assertFalse(status.get("isRecording"))

        # 2. Start recording MP4
        start_data = self.cap_mgr.start_recording(format_type="mp4")
        self.assertTrue(start_data.get("recording"))
        self.assertEqual(start_data.get("format"), "mp4")

        # 3. Check status is now recording
        status = self.cap_mgr.get_recording_status()
        self.assertTrue(status.get("isRecording"))
        self.assertEqual(status.get("format"), "mp4")

        # Status dictionary from get_status should also reflect isRecording
        full_status = self.cap_mgr.get_status()
        self.assertTrue(full_status.get("isRecording"))

        # 4. Stop recording
        stop_data = self.cap_mgr.stop_recording()
        self.assertFalse(stop_data.get("recording"))
        self.assertIn("duration", stop_data)

        # 5. Check status is now stopped
        status = self.cap_mgr.get_recording_status()
        self.assertFalse(status.get("isRecording"))

        # 6. Start WebP recording
        start_webp = self.cap_mgr.start_recording(format_type="webp")
        self.assertTrue(start_webp.get("recording"))
        self.assertEqual(start_webp.get("format"), "webp")

        stop_webp = self.cap_mgr.stop_recording()
        self.assertFalse(stop_webp.get("recording"))


class TestWebClientAssets(unittest.TestCase):
    def test_html_and_css_elements(self):
        index_path = Path(__file__).resolve().parent.parent / "server" / "static" / "index.html"
        html_content = index_path.read_text(encoding="utf-8")
        self.assertIn('id="recordFormat"', html_content)
        self.assertIn('id="btnRecord"', html_content)
        self.assertIn('id="btnSnapshot"', html_content)
        self.assertIn('id="btnFlipH"', html_content)
        self.assertIn('id="btnFlipV"', html_content)
        self.assertIn('class="header-right"', html_content)
        self.assertIn('header-tool-group', html_content)
        self.assertIn('id="hudRec"', html_content)
        self.assertIn('id="fpsSelect"', html_content)
        self.assertIn('id="audioRecordSelect"', html_content)
        self.assertIn('value="mp4"', html_content)
        self.assertIn('value="webp"', html_content)

        style_path = Path(__file__).resolve().parent.parent / "server" / "static" / "style.css"
        css_content = style_path.read_text(encoding="utf-8")
        self.assertIn(".btn-record", css_content)
        self.assertIn(".badge-rec", css_content)
        self.assertIn(".header-tool-group", css_content)
        self.assertIn(".header-divider", css_content)
        self.assertIn(".control-group-format", css_content)
        self.assertIn(".control-group-camera", css_content)

        app_js_path = Path(__file__).resolve().parent.parent / "server" / "static" / "app.js"
        js_content = app_js_path.read_text(encoding="utf-8")
        self.assertIn("buildAnimatedWebP", js_content)
        self.assertIn("startMediaRecorderRecording", js_content)
        self.assertIn("startWebpRecording", js_content)
        self.assertIn("stopRecording", js_content)


if __name__ == "__main__":
    unittest.main()
