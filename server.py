#!/usr/bin/env python3
"""
Remote Webcam Server Entrypoint
Streams laptop internal and external USB webcams to remote clients over HTTP/MJPEG.
"""

import sys
import argparse
import logging
import signal
import uvicorn

from server.camera_detector import CameraDetector
from server.capture_manager import CaptureManager
from server.web_app import create_app, get_local_ip

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("RemoteWebcamServer")


def print_banner(host: str, port: int, capture_mgr: CaptureManager):
    local_ip = get_local_ip()
    cams = CameraDetector.detect_cameras()

    print("\n" + "=" * 62)
    print("      📹 REMOTE WEBCAM STREAMING SERVER v1.0.0")
    print("=" * 62)
    print(" Detected Cameras:")
    if not cams:
        print("   ⚠️  No video capture devices found in /dev/video*")
    else:
        for cam in cams:
            marker = "⭐ [ACTIVE]" if cam.index == capture_mgr.camera_index else "  "
            type_tag = "[INTERNAL]" if cam.camera_type == "internal" else "[USB/EXT]"
            print(f"  {marker} Index {cam.index}: {type_tag} {cam.name} ({cam.path})")

    print("\n Network Access Points:")
    print(f"  • Web Client:    http://{local_ip}:{port}/")
    print(f"  • Video Stream:  http://{local_ip}:{port}/video")
    print(f"  • Snapshot:      http://{local_ip}:{port}/snapshot")
    print(f"  • Status API:    http://{local_ip}:{port}/status")
    print(f"  • Localhost:     http://127.0.0.1:{port}/")
    print("=" * 62)
    print(" Connect remote clients to the above LAN IP. Press Ctrl+C to stop.\n")


def main():
    parser = argparse.ArgumentParser(
        description="Stream laptop internal and external USB webcams to remote clients."
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host address to bind the server to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port number to listen on (default: 8080)",
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=None,
        help="Camera device index (default: first detected camera)",
    )
    parser.add_argument(
        "--resolution",
        choices=["360p", "480p", "720p", "1080p"],
        default="720p",
        help="Streaming resolution (default: 720p)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="Streaming target FPS (default: 30)",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=80,
        help="JPEG compression quality 1-100 (default: 80)",
    )
    parser.add_argument(
        "--list-cameras",
        action="store_true",
        help="List all detected internal and USB webcams and exit",
    )

    args = parser.parse_args()

    # List cameras and exit if requested
    if args.list_cameras:
        print("\nScanning for video capture devices...")
        cameras = CameraDetector.detect_cameras()
        if not cameras:
            print("No video capture devices found.")
        else:
            for c in cameras:
                print(f" • Index {c.index}: {c.display_name}")
        sys.exit(0)

    # Determine default camera index
    cams = CameraDetector.detect_cameras()
    cam_index = args.camera
    if cam_index is None:
        cam_index = cams[0].index if cams else 0

    # Initialize Capture Manager
    capture_mgr = CaptureManager(
        camera_index=cam_index,
        resolution=args.resolution,
        target_fps=args.fps,
        jpeg_quality=args.quality,
    )
    capture_mgr.start()

    # Setup Graceful Shutdown
    def handle_shutdown(signum, frame):
        logger.info("Shutdown signal received, releasing camera hardware...")
        capture_mgr.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Create FastAPI app
    app = create_app(capture_mgr=capture_mgr, host=args.host, port=args.port)

    # Print startup banner
    print_banner(args.host, args.port, capture_mgr)

    # Start Uvicorn
    config = uvicorn.Config(app=app, host=args.host, port=args.port, log_level="warning", ws="none")
    server = uvicorn.Server(config)
    try:
        server.run()
    finally:
        capture_mgr.stop()


if __name__ == "__main__":
    main()
