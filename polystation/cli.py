"""Argparse-based CLI entry point for the speech bot."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback


def _run_monitor(args: argparse.Namespace) -> int:
    """Handle the ``monitor`` subcommand."""
    from polystation.config import get_config
    from polystation.sources.base import StreamTrader

    config = get_config()
    config.ensure_paths()

    source_name: str = args.source
    url: str | None = args.url
    debug: bool = args.debug

    if source_name == "youtube":
        from polystation.sources.youtube import YouTubeSource
        source = YouTubeSource(url, config)
    elif source_name == "twitter":
        from polystation.sources.twitter import TwitterSource
        source = TwitterSource(url, config)
    elif source_name == "radio":
        from polystation.sources.radio import RadioSource
        source = RadioSource(url, config)
    else:
        print(f"Unknown source: {source_name}", file=sys.stderr)
        return 1

    trader = StreamTrader(source=source, config=config, debug=debug)
    try:
        trader.start()
    except Exception:
        logging.critical("Fatal error:\n%s", traceback.format_exc())
        return 1

    return 0


def _run_setup(args: argparse.Namespace) -> int:
    """Handle the ``setup`` subcommand."""
    action: str = args.action

    try:
        if action == "wallet":
            from polystation.wallet.generator import generate_new_wallet
            info = generate_new_wallet()
            print(f"Wallet generated")
            print(f"  Address:     {info['address']}")
            print(f"  Private key: {info['private_key']}")
            print("Credentials saved to .env")

        elif action == "allowances":
            from polystation.wallet.allowances import set_allowances
            set_allowances()
            print("Allowances set successfully")

        elif action == "api-keys":
            from polystation.wallet.credentials import generate_api_keys
            creds = generate_api_keys()
            print("API credentials generated")
            print(f"  API key: {creds['api_key']}")
            print("Credentials saved to .env")

        else:
            print(f"Unknown setup action: {action}", file=sys.stderr)
            return 1

    except Exception:
        logging.critical("Setup failed:\n%s", traceback.format_exc())
        return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="polystation",
        description="Polymarket Speech Bot — automated trading triggered by speech recognition",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- monitor ---
    monitor_parser = subparsers.add_parser(
        "monitor",
        help="Monitor an audio source and trade on keyword detections",
    )
    monitor_sub = monitor_parser.add_subparsers(dest="source", required=True)

    for source_name in ("youtube", "twitter", "radio"):
        sp = monitor_sub.add_parser(source_name, help=f"Monitor a {source_name} stream")
        sp.add_argument("--url", type=str, default=None, help="Stream URL to monitor")
        sp.add_argument("--debug", action="store_true", help="Enable debug logging")

    # --- setup ---
    setup_parser = subparsers.add_parser(
        "setup",
        help="One-time setup operations",
    )
    setup_sub = setup_parser.add_subparsers(dest="action", required=True)

    setup_sub.add_parser("wallet", help="Generate a new BIP44 Ethereum wallet")
    setup_sub.add_parser("allowances", help="Set Polymarket contract allowances on Polygon")
    setup_sub.add_parser("api-keys", help="Generate CLOB API credentials")

    return parser


def main() -> None:
    """Entry point called by ``python -m polystation`` and the installed script."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "monitor":
        sys.exit(_run_monitor(args))
    elif args.command == "setup":
        sys.exit(_run_setup(args))
    else:
        parser.print_help()
        sys.exit(1)
