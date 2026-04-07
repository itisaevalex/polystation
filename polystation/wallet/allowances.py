"""Polygon contract approval setup for Polymarket trading."""

from __future__ import annotations

import logging
import os
import time

from dotenv import load_dotenv
from web3 import Web3
from web3.constants import MAX_INT
from web3.middleware import ExtraDataToPOAMiddleware

logger = logging.getLogger(__name__)

_RPC_URL = "https://polygon-rpc.com"
_CHAIN_ID = 137

_USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
_CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

# Contracts that need both USDC ERC-20 approval and CTF ERC-1155 approval.
_SPENDER_ADDRESSES = [
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",  # CTF Exchange
    "0xC5d563A36AE78145C45a50134d48A1215220f80a",  # Neg Risk CTF Exchange
    "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",  # Neg Risk Adapter
]

_ERC20_APPROVE_ABI = (
    '[{"constant":false,"inputs":[{"name":"_spender","type":"address"},'
    '{"name":"_value","type":"uint256"}],"name":"approve","outputs":'
    '[{"name":"","type":"bool"}],"payable":false,"stateMutability":'
    '"nonpayable","type":"function"}]'
)

_ERC1155_APPROVAL_ABI = (
    '[{"inputs":[{"internalType":"address","name":"operator","type":"address"},'
    '{"internalType":"bool","name":"approved","type":"bool"}],"name":'
    '"setApprovalForAll","outputs":[],"stateMutability":"nonpayable","type":"function"}]'
)

_TX_SLEEP_SECONDS = 20


def _approve_and_wait(
    w3: Web3,
    contract_fn,
    spender: str,
    pub_key: str,
    priv_key: str,
    chain_id: int,
    label: str,
) -> None:
    """Build, sign, send a single approval transaction, then wait for receipt.

    Args:
        w3: Connected Web3 instance.
        contract_fn: Bound contract function (approve or setApprovalForAll).
        spender: Spender contract address.
        pub_key: Sender public key (checksummed).
        priv_key: Sender private key.
        chain_id: Polygon chain ID.
        label: Human-readable description for log messages.
    """
    nonce = w3.eth.get_transaction_count(pub_key, "latest")
    raw_txn = contract_fn.build_transaction(
        {"chainId": chain_id, "from": pub_key, "nonce": nonce}
    )
    signed = w3.eth.account.sign_transaction(raw_txn, private_key=priv_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=600)
    logger.info("%s receipt: %s", label, receipt)
    time.sleep(_TX_SLEEP_SECONDS)


def set_allowances(env_path: str = ".env") -> None:
    """Set Polymarket contract allowances on Polygon for the configured wallet.

    Approves maximum USDC spending and grants ERC-1155 CTF approval for each
    of the three Polymarket exchange contracts.

    Args:
        env_path: Path to the .env file containing PK and PBK.

    Raises:
        EnvironmentError: If PK or PBK are not set in the environment.
        Exception: If the wallet has no MATIC balance.
    """
    load_dotenv(env_path)

    priv_key = os.getenv("PK")
    pub_key = os.getenv("PBK")

    if not priv_key or not pub_key:
        raise EnvironmentError(
            "PK and PBK must be set in the environment (or .env file)"
        )

    w3 = Web3(Web3.HTTPProvider(_RPC_URL))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    balance = w3.eth.get_balance(pub_key)
    if balance == 0:
        raise Exception("No MATIC in wallet — send some MATIC before setting allowances")

    logger.info(
        "MATIC balance: %s MATIC", w3.from_wei(balance, "ether")
    )

    usdc = w3.eth.contract(address=_USDC_ADDRESS, abi=_ERC20_APPROVE_ABI)
    ctf = w3.eth.contract(address=_CTF_ADDRESS, abi=_ERC1155_APPROVAL_ABI)
    max_val = int(MAX_INT, 0)

    for spender in _SPENDER_ADDRESSES:
        logger.info("Setting allowances for spender: %s", spender)

        _approve_and_wait(
            w3,
            usdc.functions.approve(spender, max_val),
            spender,
            pub_key,
            priv_key,
            _CHAIN_ID,
            f"USDC approve({spender})",
        )

        _approve_and_wait(
            w3,
            ctf.functions.setApprovalForAll(spender, True),
            spender,
            pub_key,
            priv_key,
            _CHAIN_ID,
            f"CTF setApprovalForAll({spender})",
        )

    logger.info("All allowances set successfully")
