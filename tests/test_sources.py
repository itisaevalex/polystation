"""Tests for polystation.sources — YouTubeSource, TwitterSource, RadioSource."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from polystation.sources.base import AudioSource
from polystation.sources.youtube import YouTubeSource
from polystation.sources.twitter import TwitterSource
from polystation.sources.radio import RadioSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(source_key: str, default_url: str | None = None) -> MagicMock:
    """Return a mock ConfigLoader.

    If *default_url* is provided the source config will contain it,
    otherwise it will be an empty dict.
    """
    cfg = MagicMock()
    if default_url:
        cfg.get_source_config.return_value = {"default_url": default_url}
    else:
        cfg.get_source_config.return_value = {}
    return cfg


# ---------------------------------------------------------------------------
# YouTubeSource
# ---------------------------------------------------------------------------

class TestYouTubeSource:

    def test_source_name_property(self) -> None:
        cfg = _make_config("youtube", "https://www.youtube.com/watch?v=TEST")
        src = YouTubeSource(url="https://www.youtube.com/watch?v=TEST", config=cfg)
        assert src.source_name == "youtube"

    def test_accepts_explicit_url(self) -> None:
        url = "https://www.youtube.com/watch?v=EXPLICIT"
        cfg = _make_config("youtube")
        src = YouTubeSource(url=url, config=cfg)
        assert src.url == url

    def test_falls_back_to_config_url(self) -> None:
        config_url = "https://www.youtube.com/watch?v=FROM_CONFIG"
        cfg = _make_config("youtube", config_url)
        src = YouTubeSource(url=None, config=cfg)
        assert src.url == config_url

    def test_raises_when_no_url_and_config_has_no_url(self) -> None:
        cfg = _make_config("youtube")
        with pytest.raises(ValueError):
            YouTubeSource(url=None, config=cfg)

    def test_explicit_url_takes_precedence_over_config(self) -> None:
        explicit = "https://www.youtube.com/watch?v=EXPLICIT"
        config_url = "https://www.youtube.com/watch?v=FROM_CONFIG"
        cfg = _make_config("youtube", config_url)
        src = YouTubeSource(url=explicit, config=cfg)
        assert src.url == explicit

    def test_is_audio_source(self) -> None:
        cfg = _make_config("youtube", "https://www.youtube.com/watch?v=TEST")
        src = YouTubeSource(url="https://www.youtube.com/watch?v=TEST", config=cfg)
        assert isinstance(src, AudioSource)


# ---------------------------------------------------------------------------
# TwitterSource
# ---------------------------------------------------------------------------

class TestTwitterSource:

    def test_source_name_property(self) -> None:
        cfg = _make_config("twitter", "https://x.com/i/broadcasts/TEST")
        src = TwitterSource(url="https://x.com/i/broadcasts/TEST", config=cfg)
        assert src.source_name == "twitter"

    def test_accepts_explicit_url(self) -> None:
        url = "https://x.com/i/broadcasts/EXPLICIT"
        cfg = _make_config("twitter")
        src = TwitterSource(url=url, config=cfg)
        assert src.url == url

    def test_falls_back_to_config_url(self) -> None:
        config_url = "https://x.com/i/broadcasts/FROM_CONFIG"
        cfg = _make_config("twitter", config_url)
        src = TwitterSource(url=None, config=cfg)
        assert src.url == config_url

    def test_raises_when_no_url_and_config_has_no_url(self) -> None:
        cfg = _make_config("twitter")
        with pytest.raises(ValueError):
            TwitterSource(url=None, config=cfg)

    def test_explicit_url_takes_precedence_over_config(self) -> None:
        explicit = "https://x.com/i/broadcasts/EXPLICIT"
        config_url = "https://x.com/i/broadcasts/FROM_CONFIG"
        cfg = _make_config("twitter", config_url)
        src = TwitterSource(url=explicit, config=cfg)
        assert src.url == explicit

    def test_is_audio_source(self) -> None:
        cfg = _make_config("twitter", "https://x.com/i/broadcasts/TEST")
        src = TwitterSource(url="https://x.com/i/broadcasts/TEST", config=cfg)
        assert isinstance(src, AudioSource)


# ---------------------------------------------------------------------------
# RadioSource
# ---------------------------------------------------------------------------

class TestRadioSource:

    def test_source_name_property(self) -> None:
        cfg = _make_config("radio", "https://streams.example.com/radio.mp3")
        src = RadioSource(url="https://streams.example.com/radio.mp3", config=cfg)
        assert src.source_name == "radio"

    def test_accepts_explicit_url(self) -> None:
        url = "https://streams.example.com/test.mp3"
        cfg = _make_config("radio")
        src = RadioSource(url=url, config=cfg)
        assert src.url == url

    def test_falls_back_to_config_url(self) -> None:
        config_url = "https://streams.example.com/config.mp3"
        cfg = _make_config("radio", config_url)
        src = RadioSource(url=None, config=cfg)
        assert src.url == config_url

    def test_raises_when_no_url_and_config_has_no_url(self) -> None:
        cfg = _make_config("radio")
        with pytest.raises(ValueError):
            RadioSource(url=None, config=cfg)

    def test_explicit_url_takes_precedence_over_config(self) -> None:
        explicit = "https://streams.example.com/explicit.mp3"
        config_url = "https://streams.example.com/config.mp3"
        cfg = _make_config("radio", config_url)
        src = RadioSource(url=explicit, config=cfg)
        assert src.url == explicit

    def test_is_audio_source(self) -> None:
        cfg = _make_config("radio", "https://streams.example.com/radio.mp3")
        src = RadioSource(url="https://streams.example.com/radio.mp3", config=cfg)
        assert isinstance(src, AudioSource)


# ---------------------------------------------------------------------------
# Cross-source: source_name uniqueness
# ---------------------------------------------------------------------------

class TestSourceNameUniqueness:

    def test_all_source_names_are_distinct(self) -> None:
        yt_cfg = _make_config("youtube", "https://www.youtube.com/watch?v=X")
        tw_cfg = _make_config("twitter", "https://x.com/i/broadcasts/X")
        rd_cfg = _make_config("radio", "https://streams.example.com/r.mp3")

        yt = YouTubeSource(url="https://www.youtube.com/watch?v=X", config=yt_cfg)
        tw = TwitterSource(url="https://x.com/i/broadcasts/X", config=tw_cfg)
        rd = RadioSource(url="https://streams.example.com/r.mp3", config=rd_cfg)

        names = [yt.source_name, tw.source_name, rd.source_name]
        assert len(set(names)) == 3

    def test_source_name_is_string(self) -> None:
        sources = [
            YouTubeSource("https://www.youtube.com/watch?v=X", _make_config("youtube", "x")),
            TwitterSource("https://x.com/i/broadcasts/X", _make_config("twitter", "x")),
            RadioSource("https://streams.example.com/r.mp3", _make_config("radio", "x")),
        ]
        for src in sources:
            assert isinstance(src.source_name, str)
            assert src.source_name != ""
