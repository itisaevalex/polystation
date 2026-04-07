"""Vosk model loading and audio waveform recognition."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from vosk import KaldiRecognizer, Model

logger = logging.getLogger(__name__)

_MODEL_DOWNLOAD_BASE = "https://alphacephei.com/vosk/models"


class SpeechRecognizer:
    """Wraps a Vosk model and KaldiRecognizer for streaming recognition.

    Args:
        model_name: Directory name of the Vosk model to load.
        sample_rate: Audio sample rate in Hz expected by the recognizer.
    """

    def __init__(
        self,
        model_name: str = "vosk-model-small-en-us-0.15",
        sample_rate: int = 16000,
    ) -> None:
        self.model_name = model_name
        self.sample_rate = sample_rate

        model_path = Path(model_name)
        if not model_path.exists():
            logger.warning(
                "Model directory '%s' not found. "
                "Download it from: %s/%s.zip",
                model_name,
                _MODEL_DOWNLOAD_BASE,
                model_name,
            )

        logger.info("Loading Vosk model: %s", model_name)
        self._model = Model(model_name)
        self._rec = KaldiRecognizer(self._model, float(sample_rate))
        logger.info("Speech recognition model loaded successfully")

    def accept_waveform(self, data: bytes) -> str | None:
        """Feed raw PCM audio data to the recognizer.

        Args:
            data: Raw PCM bytes (16-bit signed little-endian, mono).

        Returns:
            Lowercased recognised text when a complete utterance is detected,
            or None if the recognizer is still accumulating audio.
        """
        if self._rec.AcceptWaveform(data):
            result = json.loads(self._rec.Result())
            text = result.get("text", "").strip().lower()
            return text if text else None
        return None
