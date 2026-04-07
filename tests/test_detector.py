"""Tests for polystation.speech.detector — KeywordDetector and Detection."""

from __future__ import annotations

from datetime import datetime

import pytest

from polystation.speech.detector import Detection, KeywordDetector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def markets_any() -> dict:
    """Markets that use trigger_type='any' (substring matching)."""
    return {
        "crypto_market": {
            "name": "Crypto/Bitcoin Mention",
            "token_id": "111",
            "keywords": ["crypto", "bitcoin", "cryptocurrency"],
            "trigger_type": "any",
        },
        "doge_market": {
            "name": "Dogecoin Mention",
            "token_id": "222",
            "keywords": ["dogecoin", "doge", "doge coin"],
            "trigger_type": "any",
        },
    }


@pytest.fixture()
def markets_exact() -> dict:
    """Markets that use trigger_type='exact' (whole-text equality)."""
    return {
        "greenland_market": {
            "name": "Greenland Mention",
            "token_id": "333",
            "keywords": ["greenland"],
            "trigger_type": "exact",
        },
        "drill_market": {
            "name": "Drill Baby Drill Mention",
            "token_id": "444",
            "keywords": ["drill baby drill"],
            "trigger_type": "exact",
        },
    }


@pytest.fixture()
def mixed_markets(markets_any: dict, markets_exact: dict) -> dict:
    return {**markets_any, **markets_exact}


@pytest.fixture()
def detector_any(markets_any: dict) -> KeywordDetector:
    return KeywordDetector(markets_any)


@pytest.fixture()
def detector_exact(markets_exact: dict) -> KeywordDetector:
    return KeywordDetector(markets_exact)


@pytest.fixture()
def detector_mixed(mixed_markets: dict) -> KeywordDetector:
    return KeywordDetector(mixed_markets)


# ---------------------------------------------------------------------------
# Detection dataclass
# ---------------------------------------------------------------------------

class TestDetectionDataclass:

    def test_fields_are_accessible(self) -> None:
        now = datetime.now()
        d = Detection(
            market_id="crypto_market",
            market_name="Crypto/Bitcoin Mention",
            keyword="bitcoin",
            full_text="trump mentioned bitcoin today",
            timestamp=now,
        )
        assert d.market_id == "crypto_market"
        assert d.market_name == "Crypto/Bitcoin Mention"
        assert d.keyword == "bitcoin"
        assert d.full_text == "trump mentioned bitcoin today"
        assert d.timestamp == now

    def test_two_equal_detections(self) -> None:
        now = datetime(2026, 1, 20, 12, 0, 0)
        d1 = Detection("m", "N", "kw", "text", now)
        d2 = Detection("m", "N", "kw", "text", now)
        assert d1 == d2


# ---------------------------------------------------------------------------
# trigger_type = "any"  (substring matching)
# ---------------------------------------------------------------------------

class TestTriggerTypeAny:

    def test_keyword_substring_match_returns_detection(
        self, detector_any: KeywordDetector
    ) -> None:
        results = detector_any.check_text("trump mentioned bitcoin today")
        assert len(results) == 1
        assert results[0].market_id == "crypto_market"
        assert results[0].keyword == "bitcoin"

    def test_partial_word_also_matches(
        self, detector_any: KeywordDetector
    ) -> None:
        # "cryptocurrency" contains "crypto" as a substring
        results = detector_any.check_text("cryptocurrency is volatile")
        market_ids = [r.market_id for r in results]
        assert "crypto_market" in market_ids

    def test_no_keyword_present_returns_empty(
        self, detector_any: KeywordDetector
    ) -> None:
        results = detector_any.check_text("the weather is nice today")
        assert results == []

    def test_first_matching_keyword_is_returned(
        self, detector_any: KeywordDetector
    ) -> None:
        """When multiple keywords could match, at least one Detection is produced."""
        results = detector_any.check_text("i love doge and dogecoin")
        doge_results = [r for r in results if r.market_id == "doge_market"]
        assert len(doge_results) >= 1

    def test_detection_carries_full_text(
        self, detector_any: KeywordDetector
    ) -> None:
        text = "i like bitcoin very much"
        results = detector_any.check_text(text)
        assert results[0].full_text == text

    def test_detection_timestamp_is_datetime(
        self, detector_any: KeywordDetector
    ) -> None:
        results = detector_any.check_text("bitcoin price rising")
        assert isinstance(results[0].timestamp, datetime)


# ---------------------------------------------------------------------------
# trigger_type = "exact"  (whole-text equality)
# ---------------------------------------------------------------------------

class TestTriggerTypeExact:

    def test_exact_text_match_returns_detection(
        self, detector_exact: KeywordDetector
    ) -> None:
        results = detector_exact.check_text("greenland")
        assert len(results) == 1
        assert results[0].market_id == "greenland_market"

    def test_substring_does_not_match_exact(
        self, detector_exact: KeywordDetector
    ) -> None:
        """The critical edge case: 'greenland' inside a longer sentence must NOT fire."""
        results = detector_exact.check_text("we are buying greenland from denmark")
        # "greenland" is a substring here but trigger_type is exact, so no match
        assert results == []

    def test_multi_word_exact_keyword_matches(
        self, detector_exact: KeywordDetector
    ) -> None:
        results = detector_exact.check_text("drill baby drill")
        assert len(results) == 1
        assert results[0].market_id == "drill_market"

    def test_multi_word_exact_keyword_substring_no_match(
        self, detector_exact: KeywordDetector
    ) -> None:
        results = detector_exact.check_text("we must drill baby drill harder")
        assert results == []

    def test_empty_text_no_match_exact(
        self, detector_exact: KeywordDetector
    ) -> None:
        assert detector_exact.check_text("") == []


# ---------------------------------------------------------------------------
# Multiple markets from the same text
# ---------------------------------------------------------------------------

class TestMultipleMarketDetection:

    def test_two_markets_detected_from_same_text(
        self, detector_any: KeywordDetector
    ) -> None:
        # "crypto" hits crypto_market; "doge" hits doge_market
        results = detector_any.check_text("crypto and doge are both up today")
        market_ids = {r.market_id for r in results}
        assert "crypto_market" in market_ids
        assert "doge_market" in market_ids

    def test_mixed_triggers_from_same_text(
        self, detector_mixed: KeywordDetector
    ) -> None:
        # "bitcoin" (any) fires, "greenland" exact will NOT fire (it's a substring)
        results = detector_mixed.check_text("i bought bitcoin near greenland")
        market_ids = {r.market_id for r in results}
        assert "crypto_market" in market_ids
        assert "greenland_market" not in market_ids


# ---------------------------------------------------------------------------
# excluded_markets parameter
# ---------------------------------------------------------------------------

class TestExcludedMarkets:

    def test_excluded_market_not_returned(
        self, detector_any: KeywordDetector
    ) -> None:
        results = detector_any.check_text(
            "bitcoin is great", excluded_markets={"crypto_market"}
        )
        market_ids = {r.market_id for r in results}
        assert "crypto_market" not in market_ids

    def test_non_excluded_market_still_returned(
        self, detector_any: KeywordDetector
    ) -> None:
        results = detector_any.check_text(
            "doge and bitcoin", excluded_markets={"crypto_market"}
        )
        market_ids = {r.market_id for r in results}
        assert "doge_market" in market_ids

    def test_empty_excluded_set_has_no_effect(
        self, detector_any: KeywordDetector
    ) -> None:
        results_without = detector_any.check_text("bitcoin")
        results_with = detector_any.check_text("bitcoin", excluded_markets=set())
        assert len(results_without) == len(results_with)

    def test_exclude_all_markets_returns_empty(
        self, detector_any: KeywordDetector
    ) -> None:
        results = detector_any.check_text(
            "crypto doge",
            excluded_markets={"crypto_market", "doge_market"},
        )
        assert results == []

    def test_none_excluded_markets_behaves_as_empty(
        self, detector_any: KeywordDetector
    ) -> None:
        """Passing None should behave identically to no excluded_markets."""
        results = detector_any.check_text("bitcoin", excluded_markets=None)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Case sensitivity
# ---------------------------------------------------------------------------

class TestCaseSensitivity:

    def test_lower_text_matches_lower_keyword(
        self, detector_any: KeywordDetector
    ) -> None:
        results = detector_any.check_text("bitcoin was discussed")
        assert len(results) == 1

    def test_uppercase_text_still_detected(
        self, detector_any: KeywordDetector
    ) -> None:
        """Speech recognisers emit lower-case, but the detector should handle
        upper-case input gracefully by lowering internally."""
        results = detector_any.check_text("BITCOIN mentioned")
        # After lowering, "bitcoin" is present – should match
        assert len(results) == 1

    def test_mixed_case_keyword_detection(
        self, detector_any: KeywordDetector
    ) -> None:
        results = detector_any.check_text("Bitcoin Price Surged")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_empty_text_returns_empty_list(
        self, detector_any: KeywordDetector
    ) -> None:
        assert detector_any.check_text("") == []

    def test_whitespace_only_text_returns_empty(
        self, detector_any: KeywordDetector
    ) -> None:
        assert detector_any.check_text("   ") == []

    def test_market_with_no_keywords_returns_no_detection(self) -> None:
        markets = {
            "empty_market": {
                "name": "Empty Keywords",
                "token_id": "999",
                "keywords": [],
                "trigger_type": "any",
            }
        }
        detector = KeywordDetector(markets)
        assert detector.check_text("bitcoin crypto doge") == []

    def test_empty_markets_dict_returns_empty(self) -> None:
        detector = KeywordDetector({})
        assert detector.check_text("bitcoin crypto") == []

    def test_return_type_is_list(self, detector_any: KeywordDetector) -> None:
        result = detector_any.check_text("some text")
        assert isinstance(result, list)

    def test_detection_market_name_matches_config(
        self, detector_any: KeywordDetector
    ) -> None:
        results = detector_any.check_text("bitcoin")
        assert results[0].market_name == "Crypto/Bitcoin Mention"

    def test_each_detected_market_appears_once(
        self, detector_any: KeywordDetector
    ) -> None:
        """A market should not appear more than once even if multiple keywords match."""
        # "crypto" AND "cryptocurrency" are both in the text
        results = detector_any.check_text("crypto and cryptocurrency discussed")
        crypto_hits = [r for r in results if r.market_id == "crypto_market"]
        assert len(crypto_hits) == 1
