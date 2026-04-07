"""Radio stream audio source via ffmpeg piped directly from the stream URL."""

from __future__ import annotations

import logging
import subprocess
import traceback

from polystation.config import ConfigLoader
from polystation.sources.base import AudioSource

logger = logging.getLogger(__name__)


class RadioSource(AudioSource):
    """Streams audio from an HTTP radio URL using ffmpeg directly.

    Passes the radio stream URL straight to ffmpeg, which handles buffering
    and MP3/AAC decoding internally.  This is simpler and more robust than
    the original approach of accumulating bytes in memory and writing temp
    files — ffmpeg can handle live HTTP streams natively.

    Args:
        url: Radio stream URL (HTTP/HTTPS).  Falls back to config's default_url.
        config: Loaded ConfigLoader instance.

    Raises:
        ValueError: If no URL is provided and none is found in config.
    """

    source_name: str = "radio"

    def __init__(self, url: str | None, config: ConfigLoader) -> None:
        radio_config = config.get_source_config("radio")
        self.url: str = url or radio_config.get("default_url", "")
        if not self.url:
            raise ValueError(
                "Radio URL not provided and not found in configuration"
            )

        audio_cfg = radio_config.get("audio", {})
        self.codec: str = audio_cfg.get("codec", "pcm_s16le")
        self.sample_rate: int = audio_cfg.get("sample_rate", 16000)
        self.channels: int = audio_cfg.get("channels", 1)

        logger.info("RadioSource configured for URL: %s", self.url)

    def get_audio_stream(self) -> subprocess.Popen:
        """Start an ffmpeg process that reads the radio URL and outputs PCM audio.

        Returns:
            Running ffmpeg subprocess with raw PCM data on stdout.

        Raises:
            Exception: On ffmpeg startup failure.
        """
        try:
            process = subprocess.Popen(
                [
                    "ffmpeg",
                    "-i", self.url,
                    "-acodec", self.codec,
                    "-ar", str(self.sample_rate),
                    "-ac", str(self.channels),
                    "-f", "wav",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            logger.info("ffmpeg process started for radio source: %s", self.url)
            return process
        except Exception:
            logger.error("Failed to start ffmpeg:\n%s", traceback.format_exc())
            raise
