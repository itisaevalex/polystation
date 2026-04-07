# Polymarket Speech Bot

Automated trading on [Polymarket](https://polymarket.com/) prediction markets by monitoring live audio streams for specific keywords. When a keyword is detected via speech recognition, the system executes a pre-configured trade through the Polymarket CLOB API.

Supports YouTube, Twitter/X, and radio streams. Uses [Vosk](https://alphacephei.com/vosk/) for offline, low-latency speech recognition.

## Architecture

```
speech_bot/
├── cli.py               # CLI entry point
├── config.py            # YAML config loading
├── logging.py           # Structured logging
├── trading/
│   ├── client.py        # Polymarket CLOB client
│   ├── orders.py        # Order execution with retry
│   └── recorder.py      # Trade/detection JSON recording
├── speech/
│   ├── recognizer.py    # Vosk speech recognition
│   └── detector.py      # Keyword matching
├── sources/
│   ├── base.py          # Base source + StreamTrader loop
│   ├── youtube.py       # YouTube audio source
│   ├── twitter.py       # Twitter/X audio source
│   └── radio.py         # Radio stream source
└── wallet/
    ├── generator.py     # BIP44 wallet generation
    ├── allowances.py    # Contract approvals
    └── credentials.py   # API key management
```

## Requirements

- Python 3.10+
- FFmpeg
- Polygon wallet funded with MATIC and USDC.e

## Installation

```bash
git clone https://github.com/itisaevalex/assisted_speech_bot.git
cd assisted_speech_bot
pip install -e .
```

For development tools (pytest, ruff, mypy):

```bash
pip install -e ".[dev]"
```

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and fill in:

| Variable | Description |
|---|---|
| `HOST` | Polymarket API host |
| `PK` | Wallet private key |
| `PBK` | Wallet public key |
| `CLOB_API_KEY` | API key |
| `CLOB_SECRET` | API secret |
| `CLOB_PASS_PHRASE` | API passphrase |

### YAML Config Files

All configuration lives in `config/`:

- `config/settings.yaml` -- Global settings (trading, speech recognition, paths)
- `config/markets.yaml` -- Market definitions with keywords and trade parameters
- `config/sources/youtube.yaml` -- YouTube-specific settings
- `config/sources/twitter.yaml` -- Twitter/X-specific settings
- `config/sources/radio.yaml` -- Radio-specific settings

### Market Config Example

```yaml
crypto_market:
  name: "Crypto/Bitcoin Mention"
  token_id: "36604100954285610921025197770031955172..."
  keywords:
    - "crypto"
    - "bitcoin"
    - "cryptocurrency"
  trigger_type: "any"   # "any" (substring) or "exact" (full match)
  side: "BUY"
  price: 0.9
  size: 432
  max_position: 1000
  description: "Will Trump say crypto or Bitcoin during inauguration speech?"
```

## Usage

```bash
# Monitor a YouTube stream
speech-bot monitor youtube --url "https://youtube.com/watch?v=..." --debug

# Monitor a Twitter/X broadcast
speech-bot monitor twitter --url "https://x.com/i/broadcasts/..."

# Monitor a radio stream
speech-bot monitor radio --url "https://streams.example.com/stream.mp3"

# Or use python -m
python -m speech_bot monitor youtube

# Wallet setup
speech-bot setup wallet
speech-bot setup allowances
speech-bot setup api-keys
```

## Key Features

- **Offline speech recognition** -- Vosk model runs locally with low latency
- **Multi-platform audio** -- YouTube, Twitter/X, and radio streams
- **Keyword triggers** -- "any" (substring) or "exact" matching modes
- **Retry with backoff** -- Exponential backoff on order submission failures
- **Structured logging** -- Rotating log files for main, trade, and speech events
- **Trade recording** -- JSON logs of all trades and keyword detections
- **Duplicate prevention** -- Blocks repeated trades for the same detection
- **Auto-reconnect** -- Recovers automatically on stream failure

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy speech_bot/
```

## Links

- [YouTube explanation](https://www.youtube.com/watch?v=ZbFTmDgSe_4)
- [Polymarket CLOB API docs](https://docs.polymarket.com/)
- [Polymarket Python client](https://github.com/Polymarket/py-clob-client)

## Disclaimer

Experimental / educational. Use at your own risk.

## License

MIT
