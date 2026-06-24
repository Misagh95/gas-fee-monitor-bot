"""
Ethereum Gas Fee Monitor Bot
Monitors Ethereum gas prices via Etherscan/GasNow and alerts chats on low/high gas.
Features: live gas command, threshold alerts, periodic gas reports, custom networks.
"""
import os
import json
import asyncio
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

import httpx
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)

ADMIN_IDS = [x.strip() for x in os.getenv("ADMIN_CHAT_ID", "").split(",") if x.strip()]
ALERTS_FILE = os.path.join(DATA_DIR, "gas_alerts.json")

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "120"))
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "15"))

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

gas_alerts: Dict[str, Dict[str, Any]] = {}
last_alert_state: Dict[str, Dict[str, bool]] = {}


def load_json(path: str, default: Any) -> Any:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load {path}: {e}")
            return default
    return default


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_state() -> None:
    global gas_alerts, last_alert_state
    gas_alerts = load_json(ALERTS_FILE, {})
    last_alert_state = load_json(os.path.join(DATA_DIR, "gas_last_alert.json"), {})


def save_alerts() -> None:
    save_json(ALERTS_FILE, gas_alerts)


def save_last_alert_state() -> None:
    save_json(os.path.join(DATA_DIR, "gas_last_alert.json"), last_alert_state)


def is_admin(chat_id: Any) -> bool:
    if not ADMIN_IDS:
        return True
    return str(chat_id) in ADMIN_IDS


def to_chat_id(value: Any) -> Any:
    try:
        return int(value)
    except Exception:
        return value


async def fetch_gas_etherscan() -> Optional[Dict[str, int]]:
    if not ETHERSCAN_API_KEY:
        return None
    url = "https://api.etherscan.io/api"
    params = {
        "module": "gastracker",
        "action": "gasoracle",
        "apikey": ETHERSCAN_API_KEY,
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(url, params=params)
            data = r.json()
            if data.get("status") == "1" and "result" in data:
                res = data["result"]
                return {
                    "safe": int(res["SafeGasPrice"]),
                    "standard": int(res["ProposeGasPrice"]),
                    "fast": int(res["FastGasPrice"]),
                    "base": int(res.get("suggestBaseFee", 0)),
                }
    except Exception as e:
        logger.warning(f"Etherscan gas fetch failed: {e}")
    return None


async def fetch_gas_blocknative() -> Optional[Dict[str, int]]:
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get("https://api.blocknative.com/gasprices/blockprices")
            if r.status_code == 200:
                data = r.json()
                # Simplified extraction
                base = int(data.get("baseFeePerGas", 0))
                return {
                    "safe": base,
                    "standard": base + 2,
                    "fast": base + 5,
                    "base": base,
                }
    except Exception as e:
        logger.warning(f"Blocknative gas fetch failed: {e}")
    return None


async def fetch_gas() -> Optional[Dict[str, Any]]:
    gas = await fetch_gas_etherscan()
    if not gas:
        gas = await fetch_gas_blocknative()
    if not gas:
        return None
    return {
        **gas,
        "timestamp": datetime.utcnow().isoformat(),
    }


def gas_emoji(gwei: int) -> str:
    if gwei < 15:
        return "🟢"
    if gwei < 30:
        return "🟡"
    if gwei < 80:
        return "🟠"
    return "🔴"


# =============================
# Commands
# =============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    text = (
        "⛽ <b>Ethereum Gas Monitor Bot</b>\n\n"
        "Commands:\n"
        "/gas - Current gas prices\n"
        "/set_low <gwei> - Alert when gas drops below\n"
        "/set_high <gwei> - Alert when gas rises above\n"
        "/status - Your alert thresholds\n"
        "/clear - Remove all alerts\n"
        "/report - Enable/disable periodic reports"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_gas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    gas = await fetch_gas()
    if not gas:
        await update.message.reply_text("❌ Failed to fetch gas prices. Try again later.")
        return
    text = (
        f"⛽ <b>Ethereum Gas Prices</b>\n\n"
        f"{gas_emoji(gas['safe'])} Safe: <b>{gas['safe']} Gwei</b>\n"
        f"{gas_emoji(gas['standard'])} Standard: <b>{gas['standard']} Gwei</b>\n"
        f"{gas_emoji(gas['fast'])} Fast: <b>{gas['fast']} Gwei</b>\n"
        f"Base Fee: {gas['base']} Gwei\n\n"
        f"<i>Updated: {gas['timestamp'][:19]} UTC</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_set_low(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /set_low <gwei>")
        return
    try:
        gwei = float(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Please enter a number.")
        return
    key = str(chat_id)
    gas_alerts.setdefault(key, {})
    gas_alerts[key]["low"] = gwei
    gas_alerts[key]["report"] = gas_alerts[key].get("report", True)
    save_alerts()
    await update.message.reply_text(
        f"✅ Low gas alert set: I'll notify when gas drops below <b>{gwei} Gwei</b>.",
        parse_mode="HTML",
    )


async def cmd_set_high(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /set_high <gwei>")
        return
    try:
        gwei = float(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Please enter a number.")
        return
    key = str(chat_id)
    gas_alerts.setdefault(key, {})
    gas_alerts[key]["high"] = gwei
    gas_alerts[key]["report"] = gas_alerts[key].get("report", True)
    save_alerts()
    await update.message.reply_text(
        f"✅ High gas alert set: I'll notify when gas rises above <b>{gwei} Gwei</b>.",
        parse_mode="HTML",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    key = str(update.effective_chat.id)
    cfg = gas_alerts.get(key, {})
    low = cfg.get("low")
    high = cfg.get("high")
    report = cfg.get("report", True)
    text = (
        f"⚙️ <b>Your Gas Alert Settings</b>\n\n"
        f"Low alert: <b>{low if low else 'Not set'} Gwei</b>\n"
        f"High alert: <b>{high if high else 'Not set'} Gwei</b>\n"
        f"Periodic reports: <b>{'On' if report else 'Off'}</b>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        return
    key = str(chat_id)
    if key in gas_alerts:
        del gas_alerts[key]
    save_alerts()
    await update.message.reply_text("✅ All gas alerts cleared.")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        return
    key = str(chat_id)
    gas_alerts.setdefault(key, {})
    current = gas_alerts[key].get("report", True)
    gas_alerts[key]["report"] = not current
    save_alerts()
    status = "enabled" if gas_alerts[key]["report"] else "disabled"
    await update.message.reply_text(f"✅ Periodic reports {status}.")


# =============================
# Background Monitoring
# =============================

async def gas_monitor(app: Application) -> None:
    report_counter = 0
    while True:
        try:
            gas = await fetch_gas()
            if not gas:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            report_counter += 1
            for chat_key, cfg in list(gas_alerts.items()):
                chat_id = to_chat_id(chat_key)
                state = last_alert_state.setdefault(chat_key, {"low": False, "high": False})
                low = cfg.get("low")
                high = cfg.get("high")
                standard = gas["standard"]

                # Low gas alert
                if low is not None and standard <= low:
                    if not state.get("low"):
                        text = (
                            f"🟢 <b>Low Gas Alert!</b>\n\n"
                            f"Standard gas is now <b>{standard} Gwei</b> (below your {low} Gwei threshold).\n"
                            f"Good time to transact!"
                        )
                        try:
                            await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                        except Exception as e:
                            logger.warning(f"Gas alert send failed {chat_id}: {e}")
                        state["low"] = True
                elif low is not None and standard > low:
                    state["low"] = False

                # High gas alert
                if high is not None and standard >= high:
                    if not state.get("high"):
                        text = (
                            f"🔴 <b>High Gas Alert!</b>\n\n"
                            f"Standard gas is now <b>{standard} Gwei</b> (above your {high} Gwei threshold).\n"
                            f"Consider waiting."
                        )
                        try:
                            await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                        except Exception as e:
                            logger.warning(f"Gas alert send failed {chat_id}: {e}")
                        state["high"] = True
                elif high is not None and standard < high:
                    state["high"] = False

                # Periodic report every 30 cycles (approx every CHECK_INTERVAL*30)
                if cfg.get("report", True) and report_counter % 30 == 0:
                    text = (
                        f"📊 <b>Gas Report</b>\n\n"
                        f"Safe: {gas['safe']} Gwei\n"
                        f"Standard: {gas['standard']} Gwei\n"
                        f"Fast: {gas['fast']} Gwei\n"
                        f"Base: {gas['base']} Gwei"
                    )
                    try:
                        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                    except Exception as e:
                        logger.warning(f"Gas report send failed {chat_id}: {e}")
            save_last_alert_state()
        except Exception as e:
            logger.error(f"Gas monitor error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


async def post_init(application: Application) -> None:
    asyncio.create_task(gas_monitor(application))
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("gas", "Current gas prices"),
        BotCommand("set_low", "Set low gas alert"),
        BotCommand("set_high", "Set high gas alert"),
        BotCommand("status", "Alert settings"),
        BotCommand("clear", "Clear alerts"),
        BotCommand("report", "Toggle periodic reports"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Gas monitor bot initialized.")


def main() -> None:
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing!")
        return
    load_state()

    application = Application.builder().token(TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gas", cmd_gas))
    application.add_handler(CommandHandler("set_low", cmd_set_low))
    application.add_handler(CommandHandler("set_high", cmd_set_high))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("clear", cmd_clear))
    application.add_handler(CommandHandler("report", cmd_report))

    application.run_polling()


if __name__ == "__main__":
    main()
