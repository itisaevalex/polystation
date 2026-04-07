"""YouTube audio source via yt-dlp + ffmpeg."""

from __future__ import annotations

import logging
import subprocess
import traceback

import yt_dlp

from polystation.config import ConfigLoader
from polystation.sources.base import AudioSource

logger = logging.getLogger(__name__)


class YouTubeSource(AudioSource):
    """Streams audio from a YouTube URL using yt-dlp and ffmpeg.

    Args:
        url: YouTube URL to monitor. Falls back to config's default_url.
        config: Loaded ConfigLoader instance.

    Raises:
        ValueError: If no URL is provided and none is found in config.
    """

    source_name: str = "youtube"

    def __init__(self, url: str | None, config: ConfigLoader) -> None:
        youtube_config = config.get_source_config("youtube")
        self.url: str = url or youtube_config.get("default_url", "")
        if not self.url:
            raise ValueError(
                "YouTube URL not provided and not found in configuration"
            )

        self.ytdlp_options: dict = youtube_config.get(
            "ytdlp_options", {"format": "bestaudio", "quiet": True}
        )
        audio_cfg = youtube_config.get("audio", {})
        self.codec: str = audio_cfg.get("codec", "pcm_s16le")
        self.sample_rate: int = audio_cfg.get("sample_rate", 16000)
        self.channels: int = audio_cfg.get("channels", 1)

        logger.info("YouTubeSource configured for URL: %s", self.url)

    def get_audio_stream(self) -> subprocess.Popen:
        """Extract the best audio URL via yt-dlp and pipe it through ffmpeg.

        Returns:
            Running ffmpeg subprocess with raw PCM data on stdout.

        Raises:
            Exception: On yt-dlp extraction failure or ffmpeg startup failure.
        """
        try:
            logger.info("Extracting audio URL for: %s", self.url)
            with yt_dlp.YoutubeDL(self.ytdlp_options) as ydl:
                info = ydl.extract_info(self.url, download=False)
                audio_url: str = info["url"]
            logger.info("Audio URL extracted successfully")
        except Exception:
            logger.error("Failed to extract audio URL:\n%s", traceback.format_exc())
            raise

        try:
            process = subprocess.Popen(
                [
                    "ffmpeg",
                    "-i", audio_url,
                    "-acodec", self.codec,
                    "-ar", str(self.sample_rate),
                    "-ac", str(self.channels),
                    "-f", "wav",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            logger.info("ffmpeg process started for YouTube source")
            return process
        except Exception:
            logger.error("Failed to start ffmpeg:\n%s", traceback.format_exc())
            raise
