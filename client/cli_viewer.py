"""
CLI & OpenCV Stream Viewer
Lightweight remote client for viewing the webcam stream via OpenCV window or terminal.
"""

import sys
import time
import os
from pathlib import Path
import cv2
import numpy as np

from .api import RemoteWebcamApi
from .mjpeg_receiver import MjpegReceiver


def run_cli_viewer(host: str = "127.0.0.1", port: int = 8080):
    api = RemoteWebcamApi(host=host, port=port)
    print(f"\n[CLI Viewer] Connecting to Remote Webcam server at {api.base_url}...")

    ok, msg, latency = api.check_connection()
    if not ok:
        print(f"[Error] Could not connect to {api.base_url}: {msg}")
        sys.exit(1)

    print(f"[Success] Connected (Latency: {latency:.1f}ms)")
    cameras = api.get_cameras()
    print("Available Cameras:")
    for c in cameras:
        t = "Internal" if c.get("camera_type") == "internal" else "USB"
        print(f"  • Index {c.get('index')}: [{t}] {c.get('name')}")

    print("\nKeyboard Controls:")
    print("  • 'q': Quit viewer")
    print("  • 's': Save high-res snapshot")
    print("  • 'c': Cycle to next camera (Internal <-> External USB)")
    print("  • '1': 480p | '2': 720p | '3': 1080p")
    print("  • 'h': Flip horizontal | 'v': Flip vertical\n")

    latest_frame: list[np.ndarray] = [None]
    frame_ready = False

    def on_frame(jpeg_bytes: bytes):
        nonlocal frame_ready
        np_arr = np.frombuffer(jpeg_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img is not None:
            latest_frame[0] = img
            frame_ready = True

    receiver = MjpegReceiver(video_url=api.video_url, on_frame=on_frame)
    receiver.start()

    window_name = f"Remote Webcam - {host}:{port}"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    try:
        while True:
            if latest_frame[0] is not None:
                display_img = latest_frame[0].copy()

                # Draw HUD overlay
                hud_text = f"FPS: {receiver.fps:.1f} | Bitrate: {receiver.bitrate_mbps:.1f} Mbps"
                cv2.putText(
                    display_img,
                    hud_text,
                    (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 128),
                    2,
                    cv2.LINE_AA,
                )

                cv2.imshow(window_name, display_img)

            key = cv2.waitKey(20) & 0xFF
            if key == ord("q") or key == 27:  # 'q' or ESC
                break
            elif key == ord("s"):
                if latest_frame[0] is not None:
                    pic_dir = Path.home() / "Pictures" / "RemoteWebcam"
                    pic_dir.mkdir(parents=True, exist_ok=True)
                    target = pic_dir / f"cli_snapshot_{int(time.time())}.jpg"
                    cv2.imwrite(str(target), latest_frame[0])
                    print(f"📸 Snapshot saved to: {target}")
            elif key == ord("c"):
                print("Switching camera...")
                api.send_control({"action": "switch_camera"})
            elif key == ord("1"):
                print("Setting resolution to 480p...")
                api.set_resolution("480p")
            elif key == ord("2"):
                print("Setting resolution to 720p...")
                api.set_resolution("720p")
            elif key == ord("3"):
                print("Setting resolution to 1080p...")
                api.set_resolution("1080p")
            elif key == ord("h"):
                api.toggle_flip_h()
            elif key == ord("v"):
                api.toggle_flip_v()

    finally:
        receiver.stop()
        cv2.destroyAllWindows()
        print("[CLI Viewer] Stopped.")
