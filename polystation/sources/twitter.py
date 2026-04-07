"""Twitter/X Spaces audio source via yt-dlp + optional m3u8 parsing + ffmpeg."""

from __future__ import annotations

import logging
import subprocess
import traceback

import m3u8

from polystation.config import ConfigLoader
from polystation.sources.base import AudioSource

logger = logging.getLogger(__name__)


class TwitterSource(AudioSource):
    """Streams audio from a Twitter/X Space or broadcast URL.

    Uses yt-dlp to resolve the stream URL, parses m3u8 playlists when
    present to prefer audio-only streams, then pipes through ffmpeg.

    Args:
        url: Twitter/X URL to monitor. Falls back to config's default_url.
        config: Loaded ConfigLoader instance.

    Raises:
        ValueError: If no URL is provided and none is found in config.
    """

    source_name: str = "twitter"

    def __init__(self, url: str | None, config: ConfigLoader) -> None:
        twitter_config = config.get_source_config("twitter")
        self.url: str = url or twitter_config.get("default_url", "")
        if not self.url:
            raise ValueError(
                "Twitter URL not provided and not found in configuration"
            )

        self.ytdlp_options: dict = twitter_config.get(
            "ytdlp_options", {"format": "audio_only/audio/worst", "quiet": True}
        )
        audio_cfg = twitter_config.get("audio", {})
        self.codec: str = audio_cfg.get("codec", "pcm_s16le")
        self.sample_rate: int = audio_cfg.get("sample_rate", 16000)
        self.channels: int = audio_cfg.get("channels", 1)

        logger.info("TwitterSource configured for URL: %s", self.url)

    def _get_stream_url(self) -> str:
        """Resolve the direct stream URL from the Twitter/X page URL.

        Uses yt-dlp --get-url to obtain the stream URL, then parses m3u8
        playlists to prefer audio-only variant streams.

        Returns:
            Direct stream URL ready for ffmpeg.

        Raises:
            RuntimeError: If yt-dlp produces no output or the call fails.
        """
        ytdlp_cmd = ["yt-dlp", "--get-url"]
        for key, value in self.ytdlp_options.items():
            if isinstance(value, bool):
                if value:
                    ytdlp_cmd.append(f"--{key}")
            else:
                ytdlp_cmd.extend([f"--{key}", str(value)])
        ytdlp_cmd.append(self.url)

        logger.debug("Running yt-dlp: %s", " ".join(ytdlp_cmd))
        try:
            stream_url = subprocess.check_output(
                ytdlp_cmd, stderr=subprocess.PIPE
            ).decode().strip()
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"yt-dlp failed: {exc.stderr.decode()}"
            ) from exc

        if not stream_url:
            raise RuntimeError("yt-dlp returned an empty stream URL")

        if stream_url.endswith(".m3u8"):
            logger.info("Parsing m3u8 playlist for audio stream")
            playlist = m3u8.load(stream_url)
            for variant in playlist.playlists:
                if "audio_only" in variant.uri.lower():
                    logger.info("Selected audio-only m3u8 stream")
                    return variant.uri
            if playlist.playlists:
                logger.info("Falling back to first m3u8 variant stream")
                return playlist.playlists[0].uri

        return stream_url

    def get_audio_stream(self) -> subprocess.Popen:
        """Resolve stream URL and start an ffmpeg process piping PCM audio.

        Returns:
            Running ffmpeg subprocess with raw PCM data on stdout.

        Raises:
            Exception: On URL resolution failure or ffmpeg startup failure.
        """
        try:
            stream_url = self._get_stream_url()
            logger.info("Stream URL resolved — starting ffmpeg")
        except Exception:
            logger.error(
                "Failed to get Twitter stream URL:\n%s", traceback.format_exc()
            )
            raise

        try:
            process = subprocess.Popen(
                [
                    "ffmpeg",
                    "-i", stream_url,
                    "-acodec", self.codec,
                    "-ar", str(self.sample_rate),
                    "-ac", str(self.channels),
                    "-f", "wav",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            logger.info("ffmpeg process started for Twitter source")
            return process
        except Exception:
            logger.error("Failed to start ffmpeg:\n%s", traceback.format_exc())
            raise
