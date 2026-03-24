"""Telegram bot for alerts and remote control (kill switch, status, P&L)."""

import asyncio
import json
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from risk.kill_switch import KillSwitch
from shared.redis_client import RedisClient

logger = logging.getLogger(__name__)


class TelegramAlertBot:
    """Telegram bot: sends alerts, accepts commands from authorized chat_id."""

    def __init__(self, config: dict, redis: RedisClient):
        self._config = config
        self._redis = redis
        tg_cfg = config.get("monitoring", {}).get("telegram", {})
        self._token = tg_cfg.get("bot_token", "")
        self._chat_id = str(tg_cfg.get("chat_id", ""))
        self._enabled = tg_cfg.get("enabled", False)
        self._app: Application | None = None
        self._kill_switch = KillSwitch(
            redis, config.get("risk", {}).get("kill_switch_key", "risk:kill_switch")
        )

    def _authorized(self, update: Update) -> bool:
        """Only accept commands from the configured chat_id."""
        return str(update.effective_chat.id) == self._chat_id

    async def start(self) -> None:
        if not self._enabled or not self._token:
            logger.info("Telegram bot disabled")
            return

        self._app = Application.builder().token(self._token).build()

        # Register command handlers
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("pnl", self._cmd_pnl))
        self._app.add_handler(CommandHandler("positions", self._cmd_positions))
        self._app.add_handler(CommandHandler("kill", self._cmd_kill))
        self._app.add_handler(CommandHandler("resume", self._cmd_resume))

        # Start alert listener
        asyncio.create_task(self._alert_listener())

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("Telegram bot started")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        logger.info("Telegram bot stopped")

    async def send_message(self, text: str) -> None:
        """Send a message to the configured chat."""
        if not self._enabled or not self._app or not self._chat_id:
            return
        try:
            await self._app.bot.send_message(chat_id=self._chat_id, text=text)
        except Exception:
            logger.exception("Failed to send Telegram message")

    # ── Command handlers ──

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        state = await self._redis.get_flag("portfolio:state")
        ks = await self._kill_switch.get_state()
        if state:
            msg = (
                f"Equity: ${state.get('total_equity', 0):.2f}\n"
                f"Open positions: {state.get('open_positions', 0)}\n"
                f"Daily P&L: ${state.get('daily_pnl', 0):.2f}\n"
                f"Kill switch: {'ON' if ks.get('active') else 'OFF'}"
            )
        else:
            msg = "No portfolio data available"
        await update.message.reply_text(msg)

    async def _cmd_pnl(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        state = await self._redis.get_flag("portfolio:state")
        if state:
            dp = state.get("daily_pnl", 0)
            sign = "+" if dp >= 0 else ""
            msg = (
                f"Daily P&L: {sign}${dp:.2f}\n"
                f"Total equity: ${state.get('total_equity', 0):.2f}\n"
                f"Peak equity: ${state.get('peak_equity', 0):.2f}"
            )
        else:
            msg = "No P&L data available"
        await update.message.reply_text(msg)

    async def _cmd_positions(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        state = await self._redis.get_flag("portfolio:state")
        if state and state.get("position_symbols"):
            lines = ["Open positions:"]
            for sym in state["position_symbols"]:
                price = state.get("prices", {}).get(sym, 0)
                lines.append(f"  {sym}: ${price:.2f}")
            msg = "\n".join(lines)
        else:
            msg = "No open positions"
        await update.message.reply_text(msg)

    async def _cmd_kill(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        await self._kill_switch.activate("Telegram /kill command")
        await update.message.reply_text("Kill switch ACTIVATED. All trading halted.")

    async def _cmd_resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        await self._kill_switch.deactivate()
        await update.message.reply_text("Kill switch DEACTIVATED. Trading resumed.")

    # ── Alert listener ──

    async def _alert_listener(self) -> None:
        """Subscribe to monitoring:alerts and forward to Telegram."""
        channel = self._config.get("redis", {}).get("channels", {}).get(
            "alerts", "monitoring:alerts"
        )

        async def _on_alert(data: dict):
            level = data.get("level", "info").upper()
            msg = data.get("message", "")
            source = data.get("source", "unknown")
            text = f"[{level}] ({source}) {msg}"
            await self.send_message(text)

        await self._redis.subscribe(channel, _on_alert)
