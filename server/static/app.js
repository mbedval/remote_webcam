/**
 * Remote Webcam Web Client Logic
 */

(function () {
  // Elements
  const videoStream = document.getElementById("videoStream");
  const videoWrapper = document.getElementById("videoWrapper");
  const serverEndpoint = document.getElementById("serverEndpoint");
  const statusDot = document.getElementById("statusDot");
  const viewersCount = document.getElementById("viewersCount");
  const fpsDisplay = document.getElementById("fpsDisplay");
  const hudRes = document.getElementById("hudRes");
  const hudCamera = document.getElementById("hudCamera");

  const cameraSelect = document.getElementById("cameraSelect");
  const btnRescan = document.getElementById("btnRescan");
  const resSelect = document.getElementById("resSelect");
  const recordFormat = document.getElementById("recordFormat");
  const btnRecord = document.getElementById("btnRecord");
  const recordBtnText = document.getElementById("recordBtnText");
  const hudRec = document.getElementById("hudRec");
  const btnSnapshot = document.getElementById("btnSnapshot");
  const btnFlipH = document.getElementById("btnFlipH");
  const btnFlipV = document.getElementById("btnFlipV");
  const btnFullscreen = document.getElementById("btnFullscreen");

  const btnSettings = document.getElementById("btnSettings");
  const settingsModal = document.getElementById("settingsModal");
  const btnCloseModal = document.getElementById("btnCloseModal");
  const btnCancelModal = document.getElementById("btnCancelModal");
  const btnSaveServer = document.getElementById("btnSaveServer");
  const inputHost = document.getElementById("inputHost");
  const inputPort = document.getElementById("inputPort");

  // State
  let serverBaseUrl = localStorage.getItem("remoteWebcamServer") || window.location.origin;
  if (!serverBaseUrl.startsWith("http")) {
    serverBaseUrl = `http://${serverBaseUrl}`;
  }

  let statusInterval = null;

  function updateServerDisplay() {
    serverEndpoint.textContent = serverBaseUrl;
    videoStream.src = `${serverBaseUrl}/video?t=${Date.now()}`;
  }

  videoStream.addEventListener("error", () => {
    console.warn("Video stream connection interrupted, retrying in 2 seconds...");
    setTimeout(() => {
      videoStream.src = `${serverBaseUrl}/video?t=${Date.now()}`;
    }, 2000);
  });

  async function apiFetch(endpoint, options = {}) {
    try {
      const res = await fetch(`${serverBaseUrl}${endpoint}`, {
        ...options,
        cache: "no-store",
      });
      return await res.json();
    } catch (e) {
      console.warn(`API call failed for ${endpoint}:`, e);
      return null;
    }
  }

  // Load available cameras
  async function loadCameras() {
    const data = await apiFetch("/cameras");
    if (!data || !data.cameras) return;

    cameraSelect.innerHTML = "";
    data.cameras.forEach((cam) => {
      const opt = document.createElement("option");
      opt.value = cam.index;
      const typeIcon = cam.camera_type === "internal" ? "💻" : (cam.camera_type === "android_phone" ? "📱" : "🔌");
      opt.textContent = `${typeIcon} ${cam.name} (${cam.path})`;
      if (cam.index === data.activeCameraIndex) {
        opt.selected = true;
      }
      cameraSelect.appendChild(opt);
    });
  }

  // Poll status periodically
  async function pollStatus() {
    const data = await apiFetch("/status");
    if (data && data.isRunning) {
      statusDot.className = "status-dot connected";
      viewersCount.textContent = data.activeViewers || 1;
      fpsDisplay.textContent = (data.fps || 0).toFixed(1);
      hudRes.textContent = `${data.resolution} (${data.width}x${data.height})`;
      hudCamera.textContent = data.facing || data.activeCameraName || "Webcam";

      if (resSelect.value !== data.resolution) {
        resSelect.value = data.resolution;
      }
    } else {
      statusDot.className = "status-dot disconnected";
      fpsDisplay.textContent = "--";
    }
  }

  // Control handlers
  cameraSelect.addEventListener("change", async () => {
    const idx = cameraSelect.value;
    await apiFetch(`/control?action=switch_camera&index=${idx}`);
    setTimeout(pollStatus, 500);
  });

  btnRescan.addEventListener("click", async () => {
    btnRescan.style.transform = "rotate(180deg)";
    await loadCameras();
    setTimeout(() => (btnRescan.style.transform = "none"), 400);
  });

  resSelect.addEventListener("change", async () => {
    const res = resSelect.value;
    await apiFetch(`/control?action=resolution&value=${res}`);
    setTimeout(pollStatus, 400);
  });

  btnSnapshot.addEventListener("click", () => {
    const a = document.createElement("a");
    a.href = `${serverBaseUrl}/snapshot?t=${Date.now()}`;
    a.download = `snapshot_${Date.now()}.jpg`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  });

  // Recording State & Engine
  let isRecording = false;
  let recordStartTime = 0;
  let recordTimerInterval = null;
  let mediaRecorder = null;
  let recordedChunks = [];
  let webpFrames = [];
  let webpCaptureInterval = null;
  const recordCanvas = document.createElement("canvas");
  const recordCtx = recordCanvas.getContext("2d");
  let recordAnimFrameId = null;

  function formatRecordTime(ms) {
    const totalSec = Math.floor(ms / 1000);
    const m = Math.floor(totalSec / 60).toString().padStart(2, "0");
    const s = (totalSec % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  }

  function updateRecordTimer() {
    if (!isRecording) return;
    const elapsed = Date.now() - recordStartTime;
    const timeStr = formatRecordTime(elapsed);
    recordBtnText.textContent = `Stop (${timeStr})`;
    hudRec.textContent = `🔴 REC ${timeStr}`;
  }

  function getTimestampString() {
    const d = new Date();
    const Y = d.getFullYear();
    const M = String(d.getMonth() + 1).padStart(2, "0");
    const D = String(d.getDate()).padStart(2, "0");
    const h = String(d.getHours()).padStart(2, "0");
    const m = String(d.getMinutes()).padStart(2, "0");
    const s = String(d.getSeconds()).padStart(2, "0");
    return `${Y}${M}${D}_${h}${m}${s}`;
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 1000);
  }

  async function parseWebpFrame(blob, durationMs) {
    const arrayBuffer = await blob.arrayBuffer();
    const dataView = new DataView(arrayBuffer);
    if (arrayBuffer.byteLength < 16) return null;

    let offset = 12;
    while (offset + 8 <= arrayBuffer.byteLength) {
      const chunkTag = String.fromCharCode(
        dataView.getUint8(offset),
        dataView.getUint8(offset + 1),
        dataView.getUint8(offset + 2),
        dataView.getUint8(offset + 3)
      );
      const chunkSize = dataView.getUint32(offset + 4, true);
      if (chunkTag === "VP8 " || chunkTag === "VP8L") {
        const pad = chunkSize % 2 === 1 ? 1 : 0;
        const totalLen = 8 + chunkSize + pad;
        const chunkBytes = new Uint8Array(arrayBuffer, offset, totalLen);
        return { chunkBytes, durationMs };
      }
      offset += 8 + chunkSize + (chunkSize % 2 === 1 ? 1 : 0);
    }
    return null;
  }

  function buildAnimatedWebP(frames, width, height) {
    const parts = [];
    const wMinus1 = Math.max(0, width - 1);
    const hMinus1 = Math.max(0, height - 1);

    // 1. VP8X chunk (18 bytes total)
    const vp8x = new Uint8Array(18);
    const vView = new DataView(vp8x.buffer);
    vp8x.set([0x56, 0x50, 0x38, 0x58], 0); // 'VP8X'
    vView.setUint32(4, 10, true);
    vView.setUint32(8, 0x02, true); // animation flag
    vp8x[12] = wMinus1 & 0xff;
    vp8x[13] = (wMinus1 >> 8) & 0xff;
    vp8x[14] = (wMinus1 >> 16) & 0xff;
    vp8x[15] = hMinus1 & 0xff;
    vp8x[16] = (hMinus1 >> 8) & 0xff;
    vp8x[17] = (hMinus1 >> 16) & 0xff;
    parts.push(vp8x);

    // 2. ANIM chunk (14 bytes total)
    const anim = new Uint8Array(14);
    const aView = new DataView(anim.buffer);
    anim.set([0x41, 0x4e, 0x49, 0x4d], 0); // 'ANIM'
    aView.setUint32(4, 6, true);
    aView.setUint32(8, 0, true); // background: transparent/black
    aView.setUint16(12, 0, true); // loop count: 0 (infinite)
    parts.push(anim);

    // 3. ANMF chunks
    for (const f of frames) {
      const payloadSize = 16 + f.chunkBytes.byteLength;
      const pad = payloadSize % 2 === 1 ? 1 : 0;
      const anmfHeader = new Uint8Array(24);
      const anmfView = new DataView(anmfHeader.buffer);
      anmfHeader.set([0x41, 0x4e, 0x4d, 0x46], 0); // 'ANMF'
      anmfView.setUint32(4, payloadSize, true);

      // Frame X, Y = 0
      anmfHeader[8] = 0; anmfHeader[9] = 0; anmfHeader[10] = 0;
      anmfHeader[11] = 0; anmfHeader[12] = 0; anmfHeader[13] = 0;
      // Frame Width - 1
      anmfHeader[14] = wMinus1 & 0xff;
      anmfHeader[15] = (wMinus1 >> 8) & 0xff;
      anmfHeader[16] = (wMinus1 >> 16) & 0xff;
      // Frame Height - 1
      anmfHeader[17] = hMinus1 & 0xff;
      anmfHeader[18] = (hMinus1 >> 8) & 0xff;
      anmfHeader[19] = (hMinus1 >> 16) & 0xff;
      // Duration in ms
      const dur = Math.max(10, Math.round(f.durationMs || 100));
      anmfHeader[20] = dur & 0xff;
      anmfHeader[21] = (dur >> 8) & 0xff;
      anmfHeader[22] = (dur >> 16) & 0xff;
      // Flags: 0x02 = do not blend (overwrite previous frame)
      anmfHeader[23] = 0x02;

      parts.push(anmfHeader);
      parts.push(f.chunkBytes);
      if (pad) {
        parts.push(new Uint8Array(1));
      }
    }

    // RIFF Header
    let totalPayload = 4; // 'WEBP'
    for (const p of parts) {
      totalPayload += p.byteLength;
    }
    const riff = new Uint8Array(12);
    const rView = new DataView(riff.buffer);
    riff.set([0x52, 0x49, 0x46, 0x46], 0); // 'RIFF'
    rView.setUint32(4, totalPayload, true);
    riff.set([0x57, 0x45, 0x42, 0x50], 8); // 'WEBP'

    return new Blob([riff, ...parts], { type: "image/webp" });
  }

  function startRecording() {
    const format = recordFormat.value; // "mp4", "webp", or "webm"
    const width = videoStream.naturalWidth || 1280;
    const height = videoStream.naturalHeight || 720;
    recordCanvas.width = width;
    recordCanvas.height = height;

    isRecording = true;
    recordStartTime = Date.now();
    btnRecord.classList.add("recording");
    hudRec.style.display = "block";
    updateRecordTimer();
    recordTimerInterval = setInterval(updateRecordTimer, 500);

    if (format === "webp") {
      startWebpRecording(width, height);
    } else {
      startMediaRecorderRecording(format, width, height);
    }
  }

  function startWebpRecording(width, height) {
    webpFrames = [];
    const captureFps = 12; // 12 fps provides fluid motion with compact webp files
    const frameIntervalMs = Math.round(1000 / captureFps);
    let lastCapture = Date.now();

    webpCaptureInterval = setInterval(() => {
      if (!isRecording) return;
      const now = Date.now();
      const dur = now - lastCapture;
      lastCapture = now;

      const w = videoStream.naturalWidth || width;
      const h = videoStream.naturalHeight || height;
      if (recordCanvas.width !== w || recordCanvas.height !== h) {
        recordCanvas.width = w;
        recordCanvas.height = h;
      }

      try {
        recordCtx.drawImage(videoStream, 0, 0, recordCanvas.width, recordCanvas.height);
        recordCanvas.toBlob(
          (blob) => {
            if (blob && isRecording) {
              webpFrames.push({ blob, durationMs: dur });
            }
          },
          "image/webp",
          0.8
        );
      } catch (e) {
        console.warn("WebP frame capture error:", e);
      }
    }, frameIntervalMs);
  }

  function startMediaRecorderRecording(format, width, height) {
    recordedChunks = [];

    function drawCanvasLoop() {
      if (!isRecording) return;
      const w = videoStream.naturalWidth || width;
      const h = videoStream.naturalHeight || height;
      if (recordCanvas.width !== w || recordCanvas.height !== h) {
        recordCanvas.width = w;
        recordCanvas.height = h;
      }
      try {
        recordCtx.drawImage(videoStream, 0, 0, recordCanvas.width, recordCanvas.height);
      } catch (e) {
        console.warn("Draw image failed:", e);
      }
      recordAnimFrameId = requestAnimationFrame(drawCanvasLoop);
    }
    drawCanvasLoop();

    const stream = recordCanvas.captureStream(30);

    let mimeType = "";
    if (format === "mp4") {
      const candidates = [
        "video/mp4;codecs=avc1",
        "video/mp4;codecs=h264",
        "video/mp4",
        "video/webm;codecs=h264",
        "video/webm;codecs=vp9",
        "video/webm"
      ];
      for (const c of candidates) {
        if (typeof MediaRecorder.isTypeSupported === "function" && MediaRecorder.isTypeSupported(c)) {
          mimeType = c;
          break;
        }
      }
      if (!mimeType) mimeType = "video/mp4";
    } else {
      const candidates = [
        "video/webm;codecs=vp9",
        "video/webm;codecs=vp8",
        "video/webm"
      ];
      for (const c of candidates) {
        if (typeof MediaRecorder.isTypeSupported === "function" && MediaRecorder.isTypeSupported(c)) {
          mimeType = c;
          break;
        }
      }
      if (!mimeType) mimeType = "video/webm";
    }

    try {
      mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    } catch (err) {
      console.warn("MediaRecorder init with mimeType", mimeType, "failed, falling back:", err);
      mediaRecorder = new MediaRecorder(stream);
    }

    mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        recordedChunks.push(e.data);
      }
    };

    mediaRecorder.onstop = () => {
      if (recordAnimFrameId) cancelAnimationFrame(recordAnimFrameId);
      if (recordedChunks.length > 0) {
        const actualMime = mediaRecorder.mimeType || mimeType || "video/mp4";
        const isMp4 = actualMime.includes("mp4") || format === "mp4";
        const ext = isMp4 ? "mp4" : "webm";
        const blob = new Blob(recordedChunks, { type: actualMime });
        downloadBlob(blob, `webcam_record_${getTimestampString()}.${ext}`);
      }
    };

    mediaRecorder.start(100);
  }

  async function stopRecording() {
    if (!isRecording) return;
    isRecording = false;
    clearInterval(recordTimerInterval);
    btnRecord.classList.remove("recording");
    recordBtnText.textContent = "Processing...";
    hudRec.style.display = "none";

    const format = recordFormat.value;

    if (format === "webp") {
      clearInterval(webpCaptureInterval);
      if (webpFrames.length > 0) {
        try {
          const parsedFrames = [];
          for (const f of webpFrames) {
            const parsed = await parseWebpFrame(f.blob, f.durationMs);
            if (parsed) parsedFrames.push(parsed);
          }
          if (parsedFrames.length > 0) {
            const animBlob = buildAnimatedWebP(
              parsedFrames,
              recordCanvas.width,
              recordCanvas.height
            );
            downloadBlob(animBlob, `webcam_record_${getTimestampString()}.webp`);
          }
        } catch (err) {
          console.error("Failed to build animated WebP:", err);
          alert("Failed to build animated WebP: " + err.message);
        }
      }
      webpFrames = [];
      recordBtnText.textContent = "Record";
    } else {
      if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
      }
      recordBtnText.textContent = "Record";
    }
  }

  btnRecord.addEventListener("click", () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  });

  btnFlipH.addEventListener("click", async () => {
    await apiFetch("/control?action=flip_h");
  });

  btnFlipV.addEventListener("click", async () => {
    await apiFetch("/control?action=flip_v");
  });

  // Fullscreen
  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      if (videoWrapper.requestFullscreen) {
        videoWrapper.requestFullscreen();
      }
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      }
    }
  }

  btnFullscreen.addEventListener("click", toggleFullscreen);
  videoStream.addEventListener("dblclick", toggleFullscreen);

  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.key.toLowerCase() === "f") {
      toggleFullscreen();
    } else if (e.key.toLowerCase() === "s") {
      btnSnapshot.click();
    } else if (e.key.toLowerCase() === "r") {
      btnRecord.click();
    }
  });

  // Server settings modal
  btnSettings.addEventListener("click", () => {
    try {
      const u = new URL(serverBaseUrl);
      inputHost.value = u.hostname;
      inputPort.value = u.port || "8080";
    } catch (_) {
      inputHost.value = "127.0.0.1";
      inputPort.value = "8080";
    }
    settingsModal.classList.add("active");
  });

  function closeModal() {
    settingsModal.classList.remove("active");
  }

  btnCloseModal.addEventListener("click", closeModal);
  btnCancelModal.addEventListener("click", closeModal);

  btnSaveServer.addEventListener("click", () => {
    const host = inputHost.value.trim() || "127.0.0.1";
    const port = inputPort.value.trim() || "8080";
    serverBaseUrl = `http://${host}:${port}`;
    localStorage.setItem("remoteWebcamServer", serverBaseUrl);
    closeModal();
    updateServerDisplay();
    loadCameras();
    pollStatus();
  });

  // Init
  updateServerDisplay();
  loadCameras();
  pollStatus();
  statusInterval = setInterval(pollStatus, 1000);
})();
