"""Order creation and submission with exponential backoff retry."""

from __future__ import annotations

import logging
import traceback
from typing import Literal

import backoff
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

logger = logging.getLogger(__name__)


@backoff.on_exception(
    backoff.expo,
    Exception,
    max_tries=5,
    jitter=backoff.full_jitter,
)
def create_and_submit_order(
    client: ClobClient,
    token_id: str,
    side: Literal["BUY", "SELL"],
    price: float,
    size: int,
) -> dict | None:
    """Create, sign, and submit a limit order to the CLOB with retry logic.

    Retries up to 5 times with exponential backoff and full jitter on any
    exception.

    Args:
        client: Authenticated ClobClient instance.
        token_id: The Polymarket token identifier for the outcome.
        side: "BUY" or "SELL".
        price: Limit price between 0 and 1.
        size: Number of shares.

    Returns:
        The server response dict on success, or None if the order was not
        placed (should not normally occur given the retry decorator).

    Raises:
        Exception: Re-raised after all retries are exhausted.
    """
    try:
        logger.info(
            "Creating order: token_id=%s side=%s price=%s size=%s",
            token_id,
            side,
            price,
            size,
        )

        order_args = OrderArgs(
            price=price,
            size=size,
            side=side,
            token_id=token_id,
        )

        signed_order = client.create_order(order_args)
        logger.info("Order created and signed successfully")

        response = client.post_order(signed_order)
        logger.info("Order submitted successfully: %s", response)

        return response
    except Exception:
        logger.error("Order error:\n%s", traceback.format_exc())
        raise
