"""API key generation and loading for the Polymarket CLOB."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv, set_key

from polystation.trading.client import create_clob_client

logger = logging.getLogger(__name__)


def generate_api_keys(env_path: str = ".env") -> dict[str, str]:
    """Generate new CLOB API credentials and persist them to a .env file.

    Creates a fresh API key via the CLOB client and writes CLOB_API_KEY,
    CLOB_SECRET, and CLOB_PASS_PHRASE to the .env file.

    Args:
        env_path: Path to the .env file.

    Returns:
        Dict with keys "api_key", "api_secret", and "api_passphrase".
    """
    client = create_clob_client(env_path)
    creds = client.create_api_key()

    load_dotenv(env_path)
    set_key(env_path, "CLOB_API_KEY", creds.api_key)
    set_key(env_path, "CLOB_SECRET", creds.api_secret)
    set_key(env_path, "CLOB_PASS_PHRASE", creds.api_passphrase)

    logger.info("API credentials generated and saved to %s", env_path)

    return {
        "api_key": creds.api_key,
        "api_secret": creds.api_secret,
        "api_passphrase": creds.api_passphrase,
    }


def get_api_creds(env_path: str = ".env") -> dict[str, str | None]:
    """Load existing API credentials from the environment.

    Args:
        env_path: Path to the .env file to load.

    Returns:
        Dict with keys "api_key", "secret", and "passphrase".
    """
    load_dotenv(env_path)
    return {
        "api_key": os.getenv("CLOB_API_KEY"),
        "secret": os.getenv("CLOB_SECRET"),
        "passphrase": os.getenv("CLOB_PASS_PHRASE"),
    }
