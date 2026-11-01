"""
Remote Webcam Desktop Client
Modern PyQt5 desktop viewer and controller for Remote Webcam streaming server.
Features IP/Port connection, LAN auto-discovery, camera switching, resolution selection,
instant snapshots, and low-latency MJPEG playback.
"""

import os
import sys
import json
import time
from typing import Optional, List, Dict, Any
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QFrame, QFileDialog,
    QMessageBox, QStatusBar, QShortcut, QSizePolicy, QDialog,
    QListWidget, QListWidgetItem, QProgressDialog
)
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QKeySequence, QIcon
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize

from .api import RemoteWebcamApi
from .mjpeg_receiver import MjpegReceiver

CONFIG_PATH = Path.home() / ".config" / "remote_webcam" / "client_config.json"


DARK_STYLESHEET = """
QMainWindow, QDialog {
    background-color: #0f1117;
    color: #f3f4f6;
}
QWidget {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #f3f4f6;
}
QFrame#topBar, QFrame#controlsBar {
    background-color: #1a1d27;
    border: 1px solid #2e3446;
    border-radius: 8px;
    padding: 6px;
}
QLabel {
    font-size: 13px;
    color: #9ca3af;
}
QLineEdit, QComboBox {
    background-color: #252936;
    border: 1px solid #2e3446;
    border-radius: 6px;
    padding: 6px 10px;
    color: #ffffff;
    font-size: 13px;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
}
QPushButton {
    background-color: #252936;
    border: 1px solid #2e3446;
    border-radius: 6px;
    padding: 7px 14px;
    color: #ffffff;
    font-size: 13px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #303546;
    border-color: #3b82f6;
}
QPushButton#btnConnect {
    background-color: #3b82f6;
    border-color: #2563eb;
    color: white;
}
QPushButton#btnConnect:hover {
    background-color: #2563eb;
}
QPushButton#btnDisconnect {
    background-color: #ef4444;
    border-color: #dc2626;
    color: white;
}
QPushButton#btnDisconnect:hover {
    background-color: #dc2626;
}
QStatusBar {
    background-color: #1a1d27;
    color: #9ca3af;
    border-top: 1px solid #2e3446;
}
"""


class VideoWidget(QWidget):
    """Custom widget for rendering video frames with aspect ratio fitting and HUD overlay."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(480, 270)
        self.pixmap: Optional[QPixmap] = None
        self.hud_text = "Disconnected"
        self.fps_text = ""
        self.res_text = ""
        self.status_color = QColor(239, 68, 68)  # Red

    def update_frame(self, pixmap: QPixmap):
        self.pixmap = pixmap
        self.update()

    def update_hud(self, hud_text: str, fps: float, res: str, is_connected: bool):
        self.hud_text = hud_text
        self.fps_text = f"{fps:.1f} FPS" if is_connected and fps > 0 else ""
        self.res_text = res if is_connected else ""
        self.status_color = QColor(16, 185, 129) if is_connected else QColor(239, 68, 68)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(10, 11, 15))

        if self.pixmap and not self.pixmap.isNull():
            # Scale maintaining aspect ratio
            scaled = self.pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            # Standby screen
            painter.setPen(QColor(156, 163, 175))
            font = QFont("sans-serif", 14)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "📹 No Video Stream Connected")

        # Draw HUD badges
        painter.setFont(QFont("sans-serif", 10, QFont.Bold))

        # Status badge top-left
        badge_text = f"● {self.hud_text}"
        if self.fps_text:
            badge_text += f" | {self.fps_text}"
        if self.res_text:
            badge_text += f" | {self.res_text}"

        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(badge_text) + 20
        badge_rect = QFrame()

        painter.setBrush(QColor(15, 17, 23, 190))
        painter.setPen(QColor(46, 52, 70))
        painter.drawRoundedRect(16, 16, text_width, 28, 4, 4)

        painter.setPen(self.status_color)
        painter.drawText(26, 35, badge_text)


class LanScanWorker(QThread):
    """Background worker for LAN subnet server discovery."""
    scan_complete = pyqtSignal(list)

    def __init__(self, port: int = 8080):
        super().__init__()
        self.port = port

    def run(self):
        found = RemoteWebcamApi.scan_local_network(port=self.port)
        self.scan_complete.emit(found)


class DesktopClientWindow(QMainWindow):
    """Main window for Remote Webcam Client."""

    frame_signal = pyqtSignal(bytes)
    status_signal = pyqtSignal(str)

    def __init__(self, default_host: str = "127.0.0.1", default_port: int = 8080):
        super().__init__()
        self.setWindowTitle("Remote Webcam Client")
        self.resize(1024, 680)
        self.setStyleSheet(DARK_STYLESHEET)

        self.host = default_host
        self.port = default_port
        self.api = RemoteWebcamApi(host=self.host, port=self.port)
        self.receiver: Optional[MjpegReceiver] = None
        self.is_connected = False
        self.current_fps = 0.0
        self.current_res = ""
        self.active_camera_name = "Camera"

        self.last_frame_bytes: Optional[bytes] = None

        self._load_config()
        self._init_ui()
        self._setup_signals()

        # Polling timer for status and latency
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_status)

        # Auto-connect if configured
        if self.host and self.port:
            QTimer.singleShot(300, self._on_connect_clicked)

    def _load_config(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r") as f:
                    cfg = json.load(f)
                    self.host = cfg.get("last_host", self.host)
                    self.port = cfg.get("last_port", self.port)
            except Exception:
                pass

    def _save_config(self):
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump({"last_host": self.host, "last_port": self.port}, f, indent=2)
        except Exception:
            pass

    def _init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 1. Top Bar: Server IP, Port, Connect, Scan LAN
        top_bar = QFrame(self)
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(8, 4, 8, 4)
        top_layout.setSpacing(8)

        lbl_host = QLabel("Server IP:")
        self.input_host = QLineEdit(self.host)
        self.input_host.setPlaceholderText("192.168.1.14")
        self.input_host.setMinimumWidth(150)

        lbl_port = QLabel("Port:")
        self.input_port = QLineEdit(str(self.port))
        self.input_port.setFixedWidth(70)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_connect.clicked.connect(self._on_connect_clicked)

        self.btn_scan = QPushButton("🔍 Scan LAN")
        self.btn_scan.setToolTip("Scan local network for running Remote Webcam servers")
        self.btn_scan.clicked.connect(self._on_scan_lan_clicked)

        self.lbl_status = QLabel("● Disconnected")
        self.lbl_status.setStyleSheet("color: #ef4444; font-weight: bold;")

        top_layout.addWidget(lbl_host)
        top_layout.addWidget(self.input_host)
        top_layout.addWidget(lbl_port)
        top_layout.addWidget(self.input_port)
        top_layout.addWidget(self.btn_connect)
        top_layout.addWidget(self.btn_scan)
        top_layout.addStretch()
        top_layout.addWidget(self.lbl_status)

        main_layout.addWidget(top_bar)

        # 2. Video Player Viewport
        self.video_widget = VideoWidget(self)
        main_layout.addWidget(self.video_widget, 1)

        # 3. Controls Toolbar
        controls_bar = QFrame(self)
        controls_bar.setObjectName("controlsBar")
        controls_layout = QHBoxLayout(controls_bar)
        controls_layout.setContentsMargins(8, 6, 8, 6)
        controls_layout.setSpacing(10)

        lbl_cam = QLabel("📷 Camera:")
        self.combo_cameras = QComboBox()
        self.combo_cameras.setMinimumWidth(220)
        self.combo_cameras.currentIndexChanged.connect(self._on_camera_selected)

        self.btn_refresh_cams = QPushButton("🔄")
        self.btn_refresh_cams.setToolTip("Refresh camera list")
        self.btn_refresh_cams.setFixedWidth(36)
        self.btn_refresh_cams.clicked.connect(self._refresh_cameras)

        lbl_res = QLabel("📐 Resolution:")
        self.combo_res = QComboBox()
        self.combo_res.addItems(["480p", "720p", "1080p"])
        self.combo_res.setCurrentText("720p")
        self.combo_res.currentIndexChanged.connect(self._on_resolution_selected)

        self.btn_snapshot = QPushButton("📸 Snapshot")
        self.btn_snapshot.setToolTip("Save snapshot image (Shortcut: S)")
        self.btn_snapshot.clicked.connect(self._take_snapshot)

        self.btn_flip_h = QPushButton("↔️ Flip H")
        self.btn_flip_h.clicked.connect(self._toggle_flip_h)

        self.btn_flip_v = QPushButton("↕️ Flip V")
        self.btn_flip_v.clicked.connect(self._toggle_flip_v)

        self.btn_fullscreen = QPushButton("⛶ Fullscreen")
        self.btn_fullscreen.setToolTip("Toggle fullscreen (Shortcut: F)")
        self.btn_fullscreen.clicked.connect(self._toggle_fullscreen)

        controls_layout.addWidget(lbl_cam)
        controls_layout.addWidget(self.combo_cameras)
        controls_layout.addWidget(self.btn_refresh_cams)
        controls_layout.addWidget(lbl_res)
        controls_layout.addWidget(self.combo_res)
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_snapshot)
        controls_layout.addWidget(self.btn_flip_h)
        controls_layout.addWidget(self.btn_flip_v)
        controls_layout.addWidget(self.btn_fullscreen)

        main_layout.addWidget(controls_bar)

        # Status Bar
        self.statusBar = QStatusBar(self)
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready. Enter server IP and click Connect.")

        # Keyboard shortcuts
        QShortcut(QKeySequence("F"), self, self._toggle_fullscreen)
        QShortcut(QKeySequence("S"), self, self._take_snapshot)
        QShortcut(QKeySequence("Escape"), self, self._exit_fullscreen)

    def _setup_signals(self):
        self.frame_signal.connect(self._handle_frame)
        self.status_signal.connect(self._handle_status_change)

    def _on_connect_clicked(self):
        if self.is_connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        host = self.input_host.text().strip()
        port_text = self.input_port.text().strip()
        if not host or not port_text.isdigit():
            QMessageBox.warning(self, "Invalid Endpoint", "Please enter a valid IP and Port.")
            return

        self.host = host
        self.port = int(port_text)
        self.api.set_endpoint(self.host, self.port)
        self._save_config()

        self.lbl_status.setText("● Connecting...")
        self.lbl_status.setStyleSheet("color: #f59e0b; font-weight: bold;")

        # Health check
        ok, msg, latency = self.api.check_connection()
        if not ok:
            self.lbl_status.setText(f"● {msg}")
            self.lbl_status.setStyleSheet("color: #ef4444; font-weight: bold;")
            self.statusBar.showMessage(f"Connection failed: {msg}")
            return

        self.is_connected = True
        self.btn_connect.setText("Disconnect")
        self.btn_connect.setObjectName("btnDisconnect")
        self.btn_connect.setStyleSheet("")

        # Start MJPEG Receiver
        self.receiver = MjpegReceiver(
            video_url=self.api.video_url,
            on_frame=lambda b: self.frame_signal.emit(b),
            on_status_change=lambda s: self.status_signal.emit(s),
        )
        self.receiver.start()

        self._refresh_cameras()
        self.poll_timer.start(1000)
        self.statusBar.showMessage(f"Connected to {self.api.base_url} (Latency: {latency:.1f}ms)")

    def _disconnect(self):
        self.is_connected = False
        self.poll_timer.stop()
        if self.receiver:
            self.receiver.stop()
            self.receiver = None

        self.btn_connect.setText("Connect")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_connect.setStyleSheet("")
        self.lbl_status.setText("● Disconnected")
        self.lbl_status.setStyleSheet("color: #ef4444; font-weight: bold;")
        self.video_widget.update_hud("Disconnected", 0.0, "", False)
        self.statusBar.showMessage("Disconnected.")

    def _handle_frame(self, frame_bytes: bytes):
        self.last_frame_bytes = frame_bytes
        img = QImage.fromData(frame_bytes)
        if not img.isNull():
            pix = QPixmap.fromImage(img)
            self.video_widget.update_frame(pix)

    def _handle_status_change(self, status_text: str):
        if "Connected" in status_text:
            self.lbl_status.setText("● LIVE")
            self.lbl_status.setStyleSheet("color: #10b981; font-weight: bold;")
        else:
            self.lbl_status.setText(f"● {status_text}")
            self.lbl_status.setStyleSheet("color: #ef4444; font-weight: bold;")

    def _poll_status(self):
        if not self.is_connected:
            return
        status = self.api.get_status()
        if status:
            self.current_fps = status.get("fps", 0.0)
            self.current_res = f"{status.get('width', 0)}x{status.get('height', 0)}"
            self.active_camera_name = status.get("facing", "Webcam")
            self.video_widget.update_hud(
                hud_text=f"LIVE [{self.active_camera_name}]",
                fps=self.current_fps,
                res=self.current_res,
                is_connected=True,
            )
            # Sync resolution combo box if changed remotely
            res_name = status.get("resolution", "")
            if res_name and self.combo_res.currentText() != res_name:
                self.combo_res.blockSignals(True)
                self.combo_res.setCurrentText(res_name)
                self.combo_res.blockSignals(False)

    def _refresh_cameras(self):
        cams = self.api.get_cameras()
        self.combo_cameras.blockSignals(True)
        self.combo_cameras.clear()
        status = self.api.get_status()
        active_idx = status.get("activeCameraIndex", 0) if status else 0

        for cam in cams:
            idx = cam.get("index", 0)
            cam_type = "💻 [Internal]" if cam.get("camera_type") == "internal" else "🔌 [USB]"
            name = cam.get("name", f"Camera {idx}")
            path = cam.get("path", "")
            label = f"{cam_type} {name} ({path})"
            self.combo_cameras.addItem(label, idx)
            if idx == active_idx:
                self.combo_cameras.setCurrentIndex(self.combo_cameras.count() - 1)

        self.combo_cameras.blockSignals(False)

    def _on_camera_selected(self, index: int):
        if not self.is_connected or index < 0:
            return
        cam_idx = self.combo_cameras.itemData(index)
        if cam_idx is not None:
            self.api.switch_camera(cam_idx)
            self.statusBar.showMessage(f"Switching to camera index {cam_idx}...")

    def _on_resolution_selected(self, index: int):
        if not self.is_connected:
            return
        res = self.combo_res.currentText()
        self.api.set_resolution(res)
        self.statusBar.showMessage(f"Resolution set to {res}")

    def _take_snapshot(self):
        if not self.last_frame_bytes:
            self.statusBar.showMessage("No frame available for snapshot.")
            return

        pic_dir = Path.home() / "Pictures" / "RemoteWebcam"
        pic_dir.mkdir(parents=True, exist_ok=True)
        filename = f"webcam_snapshot_{int(time.time())}.jpg"
        target_path = pic_dir / filename

        try:
            with open(target_path, "wb") as f:
                f.write(self.last_frame_bytes)
            self.statusBar.showMessage(f"📸 Snapshot saved to: {target_path}")
        except Exception as e:
            QMessageBox.critical(self, "Snapshot Error", f"Failed to save snapshot: {e}")

    def _toggle_flip_h(self):
        if self.is_connected:
            self.api.toggle_flip_h()

    def _toggle_flip_v(self):
        if self.is_connected:
            self.api.toggle_flip_v()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _exit_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()

    def _on_scan_lan_clicked(self):
        self.statusBar.showMessage("Scanning local network for Remote Webcam servers...")
        progress = QProgressDialog("Scanning LAN subnet for Remote Webcam servers...", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        worker = LanScanWorker(port=self.port)

        def on_done(results: List[Dict[str, Any]]):
            progress.close()
            if not results:
                QMessageBox.information(
                    self, "LAN Scan Results", "No Remote Webcam servers found on the local subnet."
                )
                self.statusBar.showMessage("Scan complete: No servers found.")
                return

            if len(results) == 1:
                item = results[0]
                self.input_host.setText(item["ip"])
                self.input_port.setText(str(item["port"]))
                self.statusBar.showMessage(f"Found server at {item['ip']}:{item['port']} (Auto-filled)")
                self._connect()
            else:
                dialog = QDialog(self)
                dialog.setWindowTitle("Select Discovered Server")
                d_layout = QVBoxLayout(dialog)
                list_widget = QListWidget()
                for r in results:
                    list_widget.addItem(f"{r['ip']}:{r['port']}")
                d_layout.addWidget(QLabel("Multiple servers discovered on LAN:"))
                d_layout.addWidget(list_widget)
                btn_select = QPushButton("Connect Selected")
                d_layout.addWidget(btn_select)

                def choose():
                    selected = list_widget.currentItem()
                    if selected:
                        parts = selected.text().split(":")
                        self.input_host.setText(parts[0])
                        self.input_port.setText(parts[1])
                        dialog.accept()
                        self._connect()

                btn_select.clicked.connect(choose)
                dialog.exec_()

        worker.scan_complete.connect(on_done)
        worker.start()
        # Keep reference
        self._scan_worker = worker

    def closeEvent(self, event):
        self._disconnect()
        event.accept()


def run_desktop_client(host: str = "127.0.0.1", port: int = 8080):
    app = QApplication(sys.argv)
    window = DesktopClientWindow(default_host=host, default_port=port)
    window.show()
    sys.exit(app.exec_())
