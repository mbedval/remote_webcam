# Remote Webcam - Live Streaming Server & Remote Client

A high-performance streaming server and client ecosystem engineered to stream **laptop internal webcams** and **external USB webcams** across your local network to remote devices (phones, tablets, PCs, OBS Studio) with **ultra-low latency (< 50ms)**.

Designed to be fully compatible with the **Smart Mobile Cam** protocol and **SmartCam OBS Client** (`bs-obs-client`).

---

## 🌟 Key Features

### 1. Multi-Camera Hardware Engine
- **Automatic Camera Discovery**: Automatically detects all video capture devices via Linux V4L2 and sysfs (`/sys/class/video4linux`), as well as connected **Android phones** via USB ADB!
- **Hardware Type Classification**: Automatically differentiates between **Internal Laptop Webcams** (`EasyCamera`, `Integrated Camera`), **External USB Webcams** (`Logitech`, `Creative`), and **Android Smartphones** (e.g., `📱 Android Phone [RMX1801]`).
- **Dynamic Hot-Swapping**: Switch cameras on-the-fly (`switch_camera`) remotely from any client without disconnecting or interrupting the stream (including switching between laptop webcam and phone camera!).
- **Android ADB Bridge**: Seamlessly forwards video, audio, and torch/camera controls from `Smart Mobile Cam` running on the phone over high-speed USB.
- **Hardware Optimization**: Thread-safe background capture loop decoupled from HTTP clients—multiple viewers can watch simultaneously without frame drops or hardware contention.

### 2. Universal Remote Viewing (3 Ways to View)
1. **Interactive Web Client (`http://<server-ip>:8080`)**:
   - Zero installation required on the viewer side.
   - Works on any smartphone (iOS/Android), tablet, laptop, or smart TV browser.
   - Includes camera switcher dropdown, resolution picker, instant snapshot downloader, and fullscreen mode.
2. **Dedicated Desktop Client (`run_client.sh` / PyQt5)**:
   - Sleek dark-themed desktop companion.
   - **Auto-Discovery (LAN Scanner)**: 1-click scans your local subnet to find running Remote Webcam servers automatically.
   - Live HUD overlay with measured FPS, resolution, bitrate (Mbps), and ping latency.
   - Double-click or press <kbd>F</kbd> for distraction-free fullscreen.
3. **Lightweight CLI & OpenCV Viewer (`python3 client.py --cli`)**:
   - Terminal & OpenCV window with interactive keyboard hotkeys.

### 3. SmartCam OBS Client Ecosystem Compatibility
- Exposes standard REST & MJPEG endpoints (`/video`, `/status`, `/snapshot`, `/control`, `/audio`).
- You can directly ingest this stream into **OBS Studio** using your existing `bs-obs-client` (`/home/jmbx/apps/bs-obs-client/`).

---

## 📁 Project Architecture

```
remote_webcam/
├── server/
│   ├── camera_detector.py      # V4L2 & sysfs discovery (Internal vs External USB)
│   ├── capture_manager.py      # High-performance threaded OpenCV capture & MJPEG engine
│   ├── audio_streamer.py       # 16kHz 16-bit PCM microphone streaming
│   ├── web_app.py              # FastAPI REST API & routes
│   └── static/
│       ├── index.html          # Modern, responsive Web Client
│       ├── style.css           # Dark-mode styling
│       └── app.js              # Web player, controls & camera switching
├── client/
│   ├── api.py                  # API client & concurrent LAN network scanner
│   ├── mjpeg_receiver.py       # High-speed MJPEG stream receiver thread
│   ├── desktop_gui.py          # Modern PyQt5 Desktop GUI application
│   └── cli_viewer.py           # Lightweight OpenCV / CLI window player
├── server.py                   # Server CLI entrypoint
├── client.py                   # Client CLI entrypoint
├── run_server.sh               # One-click server launcher
├── run_client.sh               # One-click client launcher
├── requirements.txt            # Python dependencies
└── README.md                   # Documentation
```

---

## ⚡ Quick Start

### 1. Start the Streaming Server (on your Laptop / PC)

```bash
# Using the launcher script
./run_server.sh

# Or directly with custom options
./run_server.sh --port 8080 --resolution 720p --fps 30
```

Upon launching, the server prints the local network access points:
```text
==============================================================
      📹 REMOTE WEBCAM STREAMING SERVER v1.0.0
==============================================================
 Detected Cameras:
  ⭐ [ACTIVE] Index 0: [INTERNAL] EasyCamera: EasyCamera (/dev/video0)

 Network Access Points:
  • Web Client:    http://192.168.1.14:8080/
  • Video Stream:  http://192.168.1.14:8080/video
  • Snapshot:      http://192.168.1.14:8080/snapshot
  • Status API:    http://192.168.1.14:8080/status
==============================================================
```

To list all detected internal and external USB cameras:
```bash
./run_server.sh --list-cameras
```

---

### 2. Connect from a Remote Client

#### Option A: Web Browser (Any Device: Phone, Tablet, PC)
Simply open the LAN URL in any browser:
```text
http://192.168.1.14:8080/
```
You can view the video, switch between internal and external USB webcams, change resolution, take snapshots, or click "Connect Server" to specify another IP/port.

#### Option B: Desktop GUI Client (Remote PC / Laptop)
Launch the Desktop Client on another computer:
```bash
./run_client.sh
```
1. Enter the Server IP (`192.168.1.14`) and Port (`8080`) (or click **🔍 Scan LAN** to auto-discover).
2. Click **Connect**.
3. View the live video with real-time FPS and latency metrics.
4. Use the bottom toolbar to switch cameras, change resolution, or capture snapshots.

#### Option C: Lightweight CLI / OpenCV Window
```bash
python3 client.py --cli --host 192.168.1.14 --port 8080
```

#### Option D: OBS Studio Ingestion (`bs-obs-client`)
Open your `bs-obs-client` app (`/home/jmbx/apps/bs-obs-client/`), enter `192.168.1.14` and port `8080`, and ingest directly into OBS Studio!

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action | Where |
|---|---|---|
| <kbd>F</kbd> | Toggle Fullscreen | Web Client, Desktop GUI, CLI |
| <kbd>S</kbd> | Capture & Save High-Resolution Snapshot | Web Client, Desktop GUI, CLI |
| <kbd>C</kbd> | Cycle to Next Camera (Internal <-> USB) | CLI Viewer |
| <kbd>1</kbd> / <kbd>2</kbd> / <kbd>3</kbd> | Set Resolution (480p / 720p / 1080p) | CLI Viewer |
| <kbd>Q</kbd> / <kbd>Esc</kbd> | Exit / Quit | Desktop GUI & CLI Viewer |

---

## 📡 REST API & Streaming Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `GET /` | HTML | Interactive Web Client Viewer |
| `GET /video` | MJPEG | Multipart live video stream (`multipart/x-mixed-replace; boundary=frame`) |
| `GET /snapshot` | JPEG | Current uncompressed JPEG frame |
| `GET /audio` | PCM | Optional 16kHz 16-bit Mono PCM audio stream |
| `GET /status` | JSON | Server status (FPS, resolution, active viewers, active camera, cameras list) |
| `GET /cameras` | JSON | List of all detected internal and external USB cameras |
| `GET/POST /control` | JSON/Query | Remote control actions: `switch_camera`, `resolution`, `fps`, `flip_h`, `flip_v` |
| `GET /health` | JSON | Service health check |

### Example Control Requests
- **Switch to Camera Index 1**:
  `curl "http://192.168.1.14:8080/control?action=switch_camera&index=1"`
- **Switch Resolution to 1080p**:
  `curl "http://192.168.1.14:8080/control?action=resolution&value=1080p"`
- **Take Snapshot via curl**:
  `curl -o snapshot.jpg "http://192.168.1.14:8080/snapshot"`
