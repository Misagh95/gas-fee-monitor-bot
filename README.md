# Gas Fee Monitor Bot

A Telegram bot that monitors Ethereum gas prices and sends alerts when gas is low or high.

## Features

- `/gas` — Current gas prices (safe, standard, fast, base)
- `/set_low <gwei>` — Alert when gas drops below a threshold
- `/set_high <gwei>` — Alert when gas rises above a threshold
- `/status` — Show current alert settings
- `/clear` — Remove all alerts
- `/report` — Toggle periodic reports

## Environment Variables

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
ADMIN_CHAT_ID=123456789
DATA_DIR=.
CHECK_INTERVAL=120
HTTP_TIMEOUT=15
ETHERSCAN_API_KEY=your_key  # Required
```

## Install & Run

```bash
pip install -r requirements.txt
python bot.py
```

## Deploy

This project includes a `Dockerfile` and `render.yaml` for quick deployment on Render.com or any Docker-compatible host.

See the root `DEPLOY.md` for detailed instructions.
