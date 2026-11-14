"""
Audio Streamer Module
Captures 16kHz 16-bit Mono PCM audio from system microphone using arecord / ALSA
compatible with SmartCam audio receiver (/audio).
"""

import sys
import shutil
import subprocess
import logging
from typing import Generator, Optional

logger = logging.getLogger("AudioStreamer")


class AudioStreamer:
    """Streams live microphone audio as raw 16kHz 16-bit PCM."""

    RATE = 16000
    CHANNELS = 1
    CHUNK_SIZE = 1024  # 1024 samples = 2048 bytes

    @classmethod
    def get_webcam_mic_name(cls) -> Optional[str]:
        """Discovers the external USB webcam microphone device name on Windows."""
        try:
            from PyQt5.QtMultimedia import QAudioDeviceInfo, QAudio
            for d in QAudioDeviceInfo.availableDevices(QAudio.AudioInput):
                name = d.deviceName()
                name_l = name.lower()
                if any(k in name_l for k in ("ucamera", "web", "usb")):
                    return name
        except Exception:
            pass
        return None

    @classmethod
    def is_available(cls) -> bool:
        """Checks if an audio capture tool (arecord or ffmpeg) is installed."""
        if sys.platform == "win32":
            return shutil.which("ffmpeg") is not None
        return shutil.which("arecord") is not None or shutil.which("ffmpeg") is not None

    @classmethod
    def iter_audio_pcm(cls) -> Generator[bytes, None, None]:
        """
        Streams raw PCM audio from microphone.
        Yields raw byte chunks.
        """
        if not cls.is_available():
            logger.info("Audio capture tool not found; audio streaming disabled.")
            return

        if sys.platform == "win32":
            mic_name = cls.get_webcam_mic_name()
            audio_source = f"audio={mic_name}" if mic_name else "audio=default"
            cmd = [
                "ffmpeg",
                "-loglevel", "error",
                "-f", "dshow",
                "-i", audio_source,
                "-f", "s16le",
                "-ar", str(cls.RATE),
                "-ac", str(cls.CHANNELS),
                "-",
            ]
        elif shutil.which("arecord"):
            cmd = [
                "arecord",
                "-q",
                "-t", "raw",
                "-f", "S16_LE",
                "-r", str(cls.RATE),
                "-c", str(cls.CHANNELS),
            ]
        else:
            cmd = [
                "ffmpeg",
                "-loglevel", "error",
                "-f", "pulse",
                "-i", "default",
                "-f", "s16le",
                "-ar", str(cls.RATE),
                "-ac", str(cls.CHANNELS),
                "-",
            ]

        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=cls.CHUNK_SIZE * 2,
            )
            logger.info("Microphone audio stream started")

            while proc.poll() is None:
                chunk = proc.stdout.read(cls.CHUNK_SIZE * 2)
                if not chunk:
                    break
                yield chunk

        except GeneratorExit:
            pass
        except Exception as e:
            logger.error(f"Error in audio streaming: {e}")
        finally:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=0.5)
                except Exception:
                    proc.kill()
            logger.info("Microphone audio stream stopped")
