"""
Remote Webcam API Client & Auto-Discovery
Handles communication with the Remote Webcam server endpoints:
- GET /status
- GET /cameras
- GET /control / POST /control
- GET /snapshot
- Network auto-discovery scanner
"""

import time
import json
import socket
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List, Tuple


class RemoteWebcamApi:
    """Client for communicating with the Remote Webcam server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8080, timeout: float = 3.0):
        self.host = host.strip()
        self.port = port
        self.timeout = timeout

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def video_url(self) -> str:
        return f"{self.base_url}/video"

    @property
    def snapshot_url(self) -> str:
        return f"{self.base_url}/snapshot"

    @property
    def status_url(self) -> str:
        return f"{self.base_url}/status"

    @property
    def cameras_url(self) -> str:
        return f"{self.base_url}/cameras"

    def set_endpoint(self, host: str, port: int):
        self.host = host.strip()
        self.port = port

    def check_connection(self) -> Tuple[bool, str, float]:
        """
        Tests server reachability and measures latency in milliseconds.
        Returns: (success, message, latency_ms)
        """
        start_time = time.time()
        try:
            req = urllib.request.Request(self.status_url, headers={"User-Agent": "RemoteWebcamClient/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    latency = (time.time() - start_time) * 1000
                    return True, "Connected", latency
        except urllib.error.URLError as e:
            return False, f"Connection failed: {e.reason}", 0.0
        except Exception as e:
            return False, str(e), 0.0
        return False, "Non-200 status code", 0.0

    def get_status(self) -> Optional[Dict[str, Any]]:
        """Fetches server status dictionary."""
        try:
            req = urllib.request.Request(self.status_url, headers={"User-Agent": "RemoteWebcamClient/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None
        return None

    def get_cameras(self) -> List[Dict[str, Any]]:
        """Fetches list of available cameras on the server."""
        try:
            req = urllib.request.Request(self.cameras_url, headers={"User-Agent": "RemoteWebcamClient/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data.get("cameras", [])
        except Exception:
            return []
        return []

    def send_control(self, params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Sends control command to /control."""
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}/control?{query}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RemoteWebcamClient/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return True, data
        except Exception as e:
            return False, {"error": str(e)}
        return False, {"error": "Request failed"}

    def switch_camera(self, index: int) -> bool:
        ok, res = self.send_control({"action": "switch_camera", "index": index})
        return ok and res.get("success", False)

    def set_resolution(self, resolution: str) -> bool:
        ok, res = self.send_control({"action": "resolution", "value": resolution})
        return ok and res.get("success", False)

    def toggle_flip_h(self) -> bool:
        ok, res = self.send_control({"action": "flip_h"})
        return res.get("flipHorizontal", False)

    def toggle_flip_v(self) -> bool:
        ok, res = self.send_control({"action": "flip_v"})
        return res.get("flipVertical", False)

    def get_snapshot(self) -> Optional[bytes]:
        """Downloads current full-res snapshot."""
        try:
            req = urllib.request.Request(self.snapshot_url, headers={"User-Agent": "RemoteWebcamClient/1.0"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if resp.status == 200:
                    return resp.read()
        except Exception:
            return None
        return None

    @staticmethod
    def scan_local_network(port: int = 8080, timeout: float = 0.4) -> List[Dict[str, Any]]:
        """
        Scans the local subnet for active Remote Webcam servers.
        Returns list of found servers: [{'ip': '192.168.1.14', 'port': 8080, 'name': '...'}]
        """
        found = []
        try:
            # Determine local subnet base
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "127.0.0.1"

        if local_ip.startswith("127."):
            ips_to_check = ["127.0.0.1"]
        else:
            prefix = ".".join(local_ip.split(".")[:3])
            ips_to_check = [f"{prefix}.{i}" for i in range(1, 255)]

        def probe(ip: str):
            url = f"http://{ip}:{port}/health"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "RemoteWebcamScanner"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("service") == "remote-webcam":
                            return {"ip": ip, "port": port}
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(probe, ip) for ip in ips_to_check]
            for fut in as_completed(futures):
                res = fut.result()
                if res:
                    found.append(res)

        return found
