"""BIP44 Ethereum wallet generation with .env persistence."""

from __future__ import annotations

import logging
from pathlib import Path

from bip_utils import (
    Bip39MnemonicGenerator,
    Bip39SeedGenerator,
    Bip44,
    Bip44Changes,
    Bip44Coins,
)
from dotenv import load_dotenv, set_key

logger = logging.getLogger(__name__)


def generate_new_wallet(env_path: str | Path = ".env") -> dict[str, str]:
    """Generate a new BIP44 Ethereum wallet and persist it to a .env file.

    Generates a 12-word BIP39 mnemonic, derives the first Ethereum account
    on the external chain (m/44'/60'/0'/0/0), and writes PK and PBK to the
    .env file.

    Args:
        env_path: Path to the .env file. Created if it does not exist.

    Returns:
        Dict with keys "address" and "private_key".
    """
    env_file = str(env_path)

    mnemonic = Bip39MnemonicGenerator().FromWordsNumber(12)
    logger.info("Generated mnemonic (12 words) — keep this secret")

    seed = Bip39SeedGenerator(mnemonic).Generate()

    bip44_root = Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
    eth_account = (
        bip44_root
        .Purpose()
        .Coin()
        .Account(0)
        .Change(Bip44Changes.CHAIN_EXT)
        .AddressIndex(0)
    )

    private_key: str = eth_account.PrivateKey().Raw().ToHex()
    address: str = eth_account.PublicKey().ToAddress()

    logger.info("Wallet address: %s", address)

    load_dotenv(env_file)
    set_key(env_file, "PK", private_key)
    set_key(env_file, "PBK", address)

    logger.info("Wallet credentials saved to %s", env_file)

    return {"address": address, "private_key": private_key}
