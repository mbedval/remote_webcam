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
