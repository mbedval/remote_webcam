"""
Web Application & REST API Module
FastAPI server serving MJPEG stream, snapshot, camera controls, and Web Client UI.
"""

import os
import socket
import logging
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, Query, Response, status
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .capture_manager import CaptureManager
from .camera_detector import CameraDetector
from .audio_streamer import AudioStreamer

logger = logging.getLogger("WebApp")


def get_local_ip() -> str:
    """Discovers the best outward-facing LAN IP address of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def create_app(capture_mgr: CaptureManager, host: str = "0.0.0.0", port: int = 8080) -> FastAPI:
    """Factory creating and configuring the FastAPI application."""

    app = FastAPI(title="Remote Webcam Streaming Server", version="1.0.0")

    # Enable CORS for all remote clients
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    actual_ip = get_local_ip()

    @app.get("/")
    async def index():
        """Serves the interactive web client viewer."""
        index_file = os.path.join(static_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return JSONResponse({"message": "Remote Webcam Server Running. Access /video for stream."})

    @app.get("/video")
    async def video_feed():
        """MJPEG video stream endpoint."""
        return StreamingResponse(
            capture_mgr.iter_mjpeg_frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @app.get("/snapshot")
    async def snapshot():
        """Current high-resolution JPEG snapshot."""
        data = capture_mgr.get_snapshot()
        if not data:
            return Response(content=b"", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(
            content=data,
            media_type="image/jpeg",
            headers={"Content-Disposition": "inline; filename=webcam_snapshot.jpg"},
        )

    @app.get("/audio")
    async def audio_feed():
        """16kHz 16-bit Mono PCM audio stream."""
        return StreamingResponse(
            AudioStreamer.iter_audio_pcm(),
            media_type="audio/L16;rate=16000;channels=1",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/status")
    async def server_status():
        """JSON status endpoint compatible with SmartCam ecosystem."""
        stat = capture_mgr.get_status(host=actual_ip, port=port)
        return JSONResponse(stat)

    @app.get("/cameras")
    async def list_cameras():
        """Returns verified list of internal and external USB cameras."""
        cams = CameraDetector.detect_cameras()
        return JSONResponse({
            "count": len(cams),
            "activeCameraIndex": capture_mgr.camera_index,
            "cameras": [c.to_dict() for c in cams],
        })

    @app.api_route("/control", methods=["GET", "POST"])
    async def control(
        request: Request,
        action: Optional[str] = Query(None),
        index: Optional[int] = Query(None),
        value: Optional[str] = Query(None),
        state: Optional[str] = Query(None),
    ):
        """
        Unified remote control endpoint accepting query params or JSON body.
        Supports:
          - action=switch_camera [& index=X]
          - action=resolution & value=480p|720p|1080p
          - action=fps & value=30
          - action=quality & value=85
          - action=flip_h
          - action=flip_v
        """
        # If POST with JSON body, merge parameters
        if request.method == "POST":
            try:
                body = await request.json()
                action = body.get("action", action)
                index = body.get("index", index)
                value = body.get("value", value)
                state = body.get("state", state)
            except Exception:
                pass

        if not action:
            return JSONResponse({"status": "error", "message": "Missing action parameter"}, status_code=400)

        action = action.lower()
        result: Dict[str, Any] = {"action": action, "success": True}

        if action == "switch_camera":
            target_idx = index
            if target_idx is None and value and value.isdigit():
                target_idx = int(value)
            ok = capture_mgr.switch_camera(target_idx)
            result["success"] = ok
            result["activeCameraIndex"] = capture_mgr.camera_index
            result["facing"] = (
                "Internal Webcam"
                if capture_mgr.current_camera_info
                and capture_mgr.current_camera_info.camera_type == "internal"
                else "External USB Webcam"
            )

        elif action == "resolution":
            res = (value or "720p").lower()
            ok = capture_mgr.set_resolution(res)
            result["success"] = ok
            result["resolution"] = capture_mgr.resolution_name
            result["width"] = capture_mgr.target_width
            result["height"] = capture_mgr.target_height

        elif action == "fps":
            if value and value.isdigit():
                capture_mgr.set_fps(int(value))
                result["fps"] = capture_mgr.target_fps
            else:
                result["success"] = False

        elif action == "quality":
            if value and value.isdigit():
                capture_mgr.set_quality(int(value))
                result["quality"] = capture_mgr.jpeg_quality
            else:
                result["success"] = False

        elif action == "flip_h":
            flipped = capture_mgr.toggle_flip_h()
            result["flipHorizontal"] = flipped

        elif action == "flip_v":
            flipped = capture_mgr.toggle_flip_v()
            result["flipVertical"] = flipped

        elif action == "torch":
            # Protocol compatibility with mobile SmartCam
            result["torch"] = False
            result["message"] = "Torch not applicable for desktop webcam"

        else:
            result["success"] = False
            result["message"] = f"Unknown action: {action}"

        return JSONResponse(result)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "remote-webcam"}

    return app
