"""
Web Application & REST API Module
FastAPI server serving MJPEG stream, snapshot, camera controls, audio, and Web Client UI.
Supports proxying audio and controls to connected Android phone when selected.
"""

import os
import socket
import logging
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any, Generator
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


def iter_phone_audio(url: str = "http://127.0.0.1:8088/audio") -> Generator[bytes, None, None]:
    """Streams live microphone audio from connected Android phone."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RemoteWebcamServer"})
        with urllib.request.urlopen(req, timeout=3.0) as stream:
            while True:
                chunk = stream.read(2048)
                if not chunk:
                    break
                yield chunk
    except Exception as e:
        logger.debug(f"Phone audio stream ended/unavailable: {e}")


def create_app(capture_mgr: CaptureManager, host: str = "0.0.0.0", port: int = 8080) -> FastAPI:
    """Factory creating and configuring the FastAPI application."""

    app = FastAPI(title="Remote Webcam Streaming Server", version="1.0.0")

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
        index_file = os.path.join(static_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return JSONResponse({"message": "Remote Webcam Server Running. Access /video for stream."})

    @app.get("/video")
    async def video_feed():
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
        if capture_mgr.is_android_camera:
            phone_port = 8088 + (capture_mgr.camera_index - 100)
            phone_audio_url = f"http://127.0.0.1:{phone_port}/audio"
            return StreamingResponse(
                iter_phone_audio(phone_audio_url),
                media_type="audio/L16;rate=16000;channels=1",
                headers={"Cache-Control": "no-cache"},
            )
        else:
            return StreamingResponse(
                AudioStreamer.iter_audio_pcm(),
                media_type="audio/L16;rate=16000;channels=1",
                headers={"Cache-Control": "no-cache"},
            )

    @app.get("/status")
    async def server_status():
        stat = capture_mgr.get_status(host=actual_ip, port=port)
        return JSONResponse(stat)

    @app.get("/cameras")
    async def list_cameras():
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
                "Android Phone Camera"
                if capture_mgr.is_android_camera
                else (
                    "Internal Webcam"
                    if capture_mgr.current_camera_info
                    and capture_mgr.current_camera_info.camera_type == "internal"
                    else "External USB Webcam"
                )
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
            # If Android phone is active, forward torch control
            if capture_mgr.is_android_camera:
                phone_port = 8088 + (capture_mgr.camera_index - 100)
                try:
                    q = f"action=torch"
                    if state:
                        q += f"&state={state}"
                    url = f"http://127.0.0.1:{phone_port}/control?{q}"
                    with urllib.request.urlopen(url, timeout=2.0) as resp:
                        import json
                        res_data = json.loads(resp.read().decode())
                        return JSONResponse(res_data)
                except Exception as e:
                    return JSONResponse({"torch": False, "error": str(e)})
            result["torch"] = False
            result["message"] = "Torch not supported for local webcam"

        else:
            result["success"] = False
            result["message"] = f"Unknown action: {action}"

        return JSONResponse(result)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "remote-webcam"}

    return app
