"""
Audio Streamer Module
Captures 16kHz 16-bit Mono PCM audio from system microphone using arecord / ALSA
compatible with SmartCam audio receiver (/audio).
"""

import shutil
import subprocess
import logging
from typing import Generator

logger = logging.getLogger("AudioStreamer")


class AudioStreamer:
    """Streams live microphone audio as raw 16kHz 16-bit PCM."""

    RATE = 16000
    CHANNELS = 1
    CHUNK_SIZE = 1024  # 1024 samples = 2048 bytes

    @classmethod
    def is_available(cls) -> bool:
        """Checks if arecord is installed."""
        return shutil.which("arecord") is not None

    @classmethod
    def iter_audio_pcm(cls) -> Generator[bytes, None, None]:
        """
        Spawns arecord and streams raw PCM audio.
        Yields raw byte chunks.
        """
        if not cls.is_available():
            logger.warning("arecord not found; audio streaming disabled.")
            return

        cmd = [
            "arecord",
            "-q",
            "-t", "raw",
            "-f", "S16_LE",
            "-r", str(cls.RATE),
            "-c", str(cls.CHANNELS),
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
