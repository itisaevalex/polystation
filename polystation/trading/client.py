"""CLOB client creation from environment variables."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON


def create_clob_client(env_path: str = ".env") -> ClobClient:
    """Create and return a ClobClient using credentials from the environment.

    Loads the .env file first, then reads HOST, PK, and optional API key
    variables.  If CLOB_API_KEY is set, full API credentials are attached;
    otherwise the client operates in key-only mode.

    Args:
        env_path: Path to the .env file to load. Defaults to ".env".

    Returns:
        Authenticated ClobClient instance.
    """
    load_dotenv(env_path)

    host = os.getenv("HOST")
    key = os.getenv("PK")

    api_key = os.getenv("CLOB_API_KEY")
    creds: ApiCreds | None = None
    if api_key:
        creds = ApiCreds(
            api_key=api_key,
            api_secret=os.getenv("CLOB_SECRET", ""),
            api_passphrase=os.getenv("CLOB_PASS_PHRASE", ""),
        )

    return ClobClient(host=host, key=key, chain_id=POLYGON, creds=creds)
