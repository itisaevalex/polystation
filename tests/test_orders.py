"""Tests for polystation.trading.orders — create_and_submit_order()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from polystation.trading.orders import create_and_submit_order


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_client() -> MagicMock:
    """A mock ClobClient with create_order and post_order methods."""
    client = MagicMock()
    signed_order = MagicMock(name="signed_order")
    client.create_order.return_value = signed_order
    client.post_order.return_value = {"success": True, "order_id": "abc123"}
    return client


# ---------------------------------------------------------------------------
# Successful order submission
# ---------------------------------------------------------------------------

class TestCreateAndSubmitOrderSuccess:

    def test_returns_response_dict(self, mock_client: MagicMock) -> None:
        response = create_and_submit_order(
            mock_client, token_id="tok1", side="BUY", price=0.9, size=100
        )
        assert response == {"success": True, "order_id": "abc123"}

    def test_calls_create_order_once(self, mock_client: MagicMock) -> None:
        create_and_submit_order(
            mock_client, token_id="tok1", side="BUY", price=0.9, size=100
        )
        mock_client.create_order.assert_called_once()

    def test_calls_post_order_once(self, mock_client: MagicMock) -> None:
        create_and_submit_order(
            mock_client, token_id="tok1", side="BUY", price=0.9, size=100
        )
        mock_client.post_order.assert_called_once()

    def test_post_order_receives_signed_order(self, mock_client: MagicMock) -> None:
        signed = mock_client.create_order.return_value
        create_and_submit_order(
            mock_client, token_id="tok1", side="BUY", price=0.9, size=100
        )
        mock_client.post_order.assert_called_once_with(signed)

    def test_order_args_contain_correct_params(self, mock_client: MagicMock) -> None:
        create_and_submit_order(
            mock_client, token_id="tok_xyz", side="SELL", price=0.5, size=200
        )
        create_call_args = mock_client.create_order.call_args
        order_args = create_call_args[0][0]
        assert order_args.token_id == "tok_xyz"
        assert order_args.side == "SELL"
        assert order_args.price == 0.5
        assert order_args.size == 200

    def test_returns_none_when_post_order_returns_none(
        self, mock_client: MagicMock
    ) -> None:
        mock_client.post_order.return_value = None
        result = create_and_submit_order(
            mock_client, token_id="tok1", side="BUY", price=0.9, size=100
        )
        assert result is None


# ---------------------------------------------------------------------------
# Retry / backoff behaviour
# ---------------------------------------------------------------------------

class TestCreateAndSubmitOrderRetry:

    @patch("time.sleep", return_value=None)
    def test_raises_after_exhausting_retries(
        self, _mock_sleep: MagicMock, mock_client: MagicMock
    ) -> None:
        mock_client.create_order.side_effect = RuntimeError("network error")
        with pytest.raises(RuntimeError, match="network error"):
            create_and_submit_order(
                mock_client, token_id="tok1", side="BUY", price=0.9, size=100
            )
        assert mock_client.create_order.call_count == 5  # max_tries=5

    @patch("time.sleep", return_value=None)
    def test_succeeds_after_transient_failures(
        self, _mock_sleep: MagicMock, mock_client: MagicMock
    ) -> None:
        real_signed = MagicMock(name="signed")
        success_response = {"success": True, "order_id": "retry_ok"}
        mock_client.create_order.side_effect = [
            RuntimeError("fail 1"),
            RuntimeError("fail 2"),
            real_signed,
        ]
        mock_client.post_order.return_value = success_response

        result = create_and_submit_order(
            mock_client, token_id="tok1", side="BUY", price=0.9, size=100
        )
        assert result == success_response
        assert mock_client.create_order.call_count == 3

    @patch("time.sleep", return_value=None)
    def test_post_order_failure_triggers_retry(
        self, _mock_sleep: MagicMock, mock_client: MagicMock
    ) -> None:
        success_response = {"success": True}
        mock_client.post_order.side_effect = [
            ConnectionError("timeout"),
            success_response,
        ]

        result = create_and_submit_order(
            mock_client, token_id="tok1", side="BUY", price=0.9, size=100
        )
        assert result == success_response
        assert mock_client.post_order.call_count == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestCreateAndSubmitOrderEdgeCases:

    def test_zero_size_is_forwarded(self, mock_client: MagicMock) -> None:
        create_and_submit_order(
            mock_client, token_id="tok", side="BUY", price=0.5, size=0
        )
        args_obj = mock_client.create_order.call_args[0][0]
        assert args_obj.size == 0

    def test_float_price_precision(self, mock_client: MagicMock) -> None:
        create_and_submit_order(
            mock_client, token_id="tok", side="BUY", price=0.123456789, size=1
        )
        args_obj = mock_client.create_order.call_args[0][0]
        assert args_obj.price == pytest.approx(0.123456789)

    def test_buy_side_forwarded(self, mock_client: MagicMock) -> None:
        create_and_submit_order(
            mock_client, token_id="tok", side="BUY", price=0.9, size=5
        )
        args_obj = mock_client.create_order.call_args[0][0]
        assert args_obj.side == "BUY"

    def test_sell_side_forwarded(self, mock_client: MagicMock) -> None:
        create_and_submit_order(
            mock_client, token_id="tok", side="SELL", price=0.1, size=5
        )
        args_obj = mock_client.create_order.call_args[0][0]
        assert args_obj.side == "SELL"
