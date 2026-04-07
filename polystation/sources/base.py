"""Abstract base class for audio sources and the shared StreamTrader loop."""

from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from subprocess import Popen
from typing import Any

from polystation.config import ConfigLoader
from polystation.log import setup_logging
from polystation.speech.detector import Detection, KeywordDetector
from polystation.speech.recognizer import SpeechRecognizer
from polystation.trading.client import create_clob_client
from polystation.trading.orders import create_and_submit_order
from polystation.trading.recorder import record_detection, record_trade

logger = logging.getLogger(__name__)


class AudioSource(ABC):
    """Abstract base class for audio stream sources.

    Concrete subclasses provide a subprocess whose stdout yields raw PCM WAV
    data that can be fed directly to a KaldiRecognizer.

    Class attributes:
        source_name: Short identifier for this source (e.g. "youtube").
            Must be overridden in every subclass.
    """

    source_name: str

    @abstractmethod
    def get_audio_stream(self) -> Popen:
        """Return a subprocess whose stdout yields raw PCM audio data.

        The subprocess must output WAV frames: 16-bit signed little-endian
        PCM at 16000 Hz, mono.
        """
        ...


class StreamTrader:
    """Core monitoring/trading loop that works with any AudioSource.

    Reads audio chunks from the source subprocess, runs speech recognition in
    a dedicated worker thread, and fires off trades in background threads when
    keywords are detected.

    Args:
        source: An AudioSource implementation.
        config: Loaded ConfigLoader instance.
        debug: Enable DEBUG-level logging when True.
    """

    def __init__(
        self, source: AudioSource, config: ConfigLoader, debug: bool = False
    ) -> None:
        self.source = source
        self.config = config
        self.debug = debug

        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=10)
        self.executed_markets: set[str] = set()
        self.detection_history: list[dict[str, Any]] = []

        logs_dir = config.get_setting("paths", "logs", "logs")
        self.main_logger, self.trade_logger, self.speech_logger = setup_logging(
            source.source_name, logs_dir, debug
        )

        self.main_logger.info("Initializing trading client")
        self.trading_client = create_clob_client()
        self.main_logger.info("Trading client initialized successfully")

        model_name = config.get_setting("speech", "model_name", "vosk-model-small-en-us-0.15")
        sample_rate = config.get_setting("speech", "sample_rate", 16000)
        self.recognizer = SpeechRecognizer(model_name=model_name, sample_rate=sample_rate)
        self.sample_rate: int = sample_rate

        exact_matching = config.get_setting("speech", "exact_matching", False)
        self.detector = KeywordDetector(
            config.get_enabled_markets(),
            exact_matching_override=exact_matching,
        )

        self.main_logger.info("Loaded %d markets", len(self.detector.markets))
        for market_id, market_data in self.detector.markets.items():
            self.main_logger.info(
                "  %s — %s: %s",
                market_id,
                market_data.get("name", ""),
                market_data.get("keywords", []),
            )

    def start(self) -> None:
        """Main monitoring loop — blocks until interrupted or stream ends."""
        self.main_logger.info(
            "Starting StreamTrader for source: %s", self.source.source_name
        )

        process = self.source.get_audio_stream()
        chunk_size = int(
            self.sample_rate * self.config.get_setting("speech", "chunk_size", 1)
        )

        audio_thread = threading.Thread(target=self._process_audio, daemon=True)
        audio_thread.start()
        self.main_logger.info("Audio processing thread started")

        try:
            self.main_logger.info("Beginning audio stream reading")
            while True:
                audio_data = process.stdout.read(chunk_size)  # type: ignore[union-attr]
                if not audio_data:
                    self.main_logger.warning("Audio stream ended or returned no data")
                    if self.config.get_setting("app", "auto_restart", True):
                        self.main_logger.info("Restarting audio stream...")
                        process.terminate()
                        process.wait()
                        process = self.source.get_audio_stream()
                        continue
                    break

                try:
                    self._audio_queue.put_nowait(audio_data)
                except queue.Full:
                    pass  # Drop oldest chunk; real-time priority over completeness

        except KeyboardInterrupt:
            self.main_logger.info("Keyboard interrupt received — shutting down")
        except Exception:
            self.main_logger.error(
                "Error in main loop:\n%s", traceback.format_exc()
            )
        finally:
            process.terminate()
            process.wait()
            self.main_logger.info("Shutdown complete")

    def _process_audio(self) -> None:
        """Audio processing worker — runs in a daemon thread."""
        prevent_dupes = self.config.get_setting(
            "trading", "prevent_duplicate_trades", True
        )
        record_all = self.config.get_setting("app", "record_all_transcripts", False)
        save_detections = self.config.get_setting("speech", "save_detections", True)
        logs_dir = Path(self.config.get_setting("paths", "logs", "logs"))

        while True:
            try:
                audio_data = self._audio_queue.get(timeout=5)
                if not audio_data:
                    continue

                text = self.recognizer.accept_waveform(audio_data)
                if text is None:
                    continue

                timestamp = datetime.now().strftime("%H:%M:%S")
                self.speech_logger.info('[%s] "%s"', timestamp, text)

                if record_all:
                    transcript_dir = logs_dir / "transcripts"
                    transcript_dir.mkdir(parents=True, exist_ok=True)
                    (transcript_dir / f"transcript_{int(time.time())}.txt").write_text(
                        f"{timestamp}: {text}"
                    )

                excluded = self.executed_markets if prevent_dupes else set()
                detections = self.detector.check_text(text, excluded_markets=excluded)

                for det in detections:
                    if save_detections:
                        detections_dir = self.config.get_setting(
                            "paths", "detections", "detections"
                        )
                        record_detection(detections_dir, det.to_dict())

                    self.detection_history.append(det.to_dict())

                    market_config = self.detector.markets[det.market_id]
                    threading.Thread(
                        target=self._place_trade,
                        args=(det, market_config),
                        daemon=True,
                    ).start()

            except queue.Empty:
                self.speech_logger.debug("Audio queue timeout — continuing")
            except Exception:
                self.speech_logger.error(
                    "Error processing audio:\n%s", traceback.format_exc()
                )
                time.sleep(1)

    def _place_trade(self, detection: Detection, market_config: dict[str, Any]) -> None:
        """Execute a trade for a detected keyword in a background thread.

        Args:
            detection: The Detection event that triggered this trade.
            market_config: Market configuration dict with token_id, side, etc.
        """
        market_id = detection.market_id
        prevent_dupes = self.config.get_setting(
            "trading", "prevent_duplicate_trades", True
        )
        trades_dir = self.config.get_setting("paths", "trades", "trades")

        trade_info: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "market_id": market_id,
            "market_name": market_config.get("name", market_id),
            "detected_keyword": detection.keyword,
            "status": "pending",
            "source": self.source.source_name,
        }

        self.trade_logger.info(
            "Executing trade for %s triggered by '%s'", market_id, detection.keyword
        )

        if prevent_dupes and market_id in self.executed_markets:
            self.trade_logger.warning(
                "Skipping trade for %s — already executed", market_id
            )
            trade_info["status"] = "skipped"
            trade_info["reason"] = "already_executed"
            return

        detection_time = time.time()
        try:
            resp = create_and_submit_order(
                client=self.trading_client,
                token_id=market_config["token_id"],
                side=market_config["side"],
                price=market_config["price"],
                size=market_config["size"],
            )

            if resp:
                self.executed_markets.add(market_id)
                latency = time.time() - detection_time

                trade_info["status"] = "success"
                trade_info["order_response"] = resp
                trade_info["execution_latency"] = latency

                self.trade_logger.info(
                    "Trade executed — %s — latency: %.3fs", market_id, latency
                )
                self.trade_logger.info("Response: %s", resp)
            else:
                trade_info["status"] = "failed"
                self.trade_logger.error(
                    "Trade failed — %s: no response from server", market_id
                )

        except Exception:
            trade_info["status"] = "error"
            trade_info["error"] = traceback.format_exc()
            self.trade_logger.error(
                "Trade error — %s:\n%s", market_id, traceback.format_exc()
            )

        record_trade(trades_dir, trade_info)
