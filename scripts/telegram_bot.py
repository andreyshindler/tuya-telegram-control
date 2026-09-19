#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram bot front-end for the Tuya device manager.

Talks to Tuya through TuyaDeviceManager (scripts/tuya_manager.py) — the same
code path the CLI uses. Commands are name-based rather than device-id based,
so you type "/on desk lamp" instead of pasting a 22-character device id.

Configuration (config.env, or the environment):
    TELEGRAM_BOT_TOKEN        required — from @BotFather
    TELEGRAM_ALLOWED_USERS    required — comma-separated numeric Telegram user
                              ids permitted to use the bot. Empty means nobody:
                              this bot switches things on and off in a home, so
                              it fails closed rather than open.
    TUYA_*                    as documented in config.env.example
"""

import asyncio
import html
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from intent import IntentParser
from speech import Transcriber
from tuya_manager import TuyaDeviceManager, load_config_from_env_file

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
# The HTTP client under python-telegram-bot logs every getUpdates poll at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)

# How long a fetched device list stays usable before it is re-fetched. Tuya's
# API is rate limited and the device list rarely changes, so this keeps the
# common commands to a single API call.
DEVICE_CACHE_TTL = 60.0

# Candidate on/off DP codes, most specific first. Devices disagree about what
# their main switch is called — switch_1 on multi-gang sockets, switch_led on
# bulbs, plain switch on many plugs — so the code is detected per device from
# its live status rather than assumed.
SWITCH_CODE_PRIORITY = (
    "switch",
    "switch_1",
    "switch_led",
    "switch_led_1",
    "power",
)

# Telegram caps voice notes well below this, but a long one still costs real
# transcription time and money, so refuse rather than grind.
MAX_VOICE_SECONDS = 120

# Brightness DP codes, most common first.
BRIGHTNESS_CODES = ("bright_value", "bright_value_v2", "bright_value_1")

# Status codes worth surfacing in /status, and how to label them.
INTERESTING_CODES = {
    "bright_value": "בהירות",
    "bright_value_v2": "בהירות",
    "bright_value_1": "בהירות",
    "temp_value": "גוון אור",
    "temp_current": "טמפרטורה",
    "temp_set": "טמפרטורת יעד",
    "humidity_value": "לחות",
    "cur_power": "הספק",
    "cur_voltage": "מתח",
    "cur_current": "זרם",
    "battery_percentage": "סוללה",
    "work_mode": "מצב עבודה",
}


def get_config(key: str, default: str = "") -> str:
    """Read a setting from config.env if present, else the environment."""
    return load_config_from_env_file().get(key) or os.environ.get(key, default)


def parse_allowed_users(raw: str) -> set:
    """Parse TELEGRAM_ALLOWED_USERS into a set of ints, ignoring junk."""
    allowed = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            allowed.add(int(chunk))
        except ValueError:
            logger.warning("Ignoring non-numeric entry in TELEGRAM_ALLOWED_USERS: %r", chunk)
    return allowed


class TuyaBot:
    """Holds the manager, the device cache and the per-device switch codes."""

    def __init__(self, allowed_users: set,
                 transcriber: Optional[Transcriber] = None,
                 intent: Optional[IntentParser] = None):
        self.allowed_users = allowed_users
        self.transcriber = transcriber
        self.intent = intent
        self._manager: Optional[TuyaDeviceManager] = None
        self._devices: List[Dict[str, Any]] = []
        self._devices_at: float = 0.0
        self._switch_codes: Dict[str, str] = {}
        # TuyaDeviceManager is synchronous and not thread-safe, and every call
        # here runs in a worker thread, so serialise access to it.
        self._lock = asyncio.Lock()

    # --- Tuya plumbing -----------------------------------------------------

    async def _call(self, fn, *args, **kwargs):
        """Run a blocking manager call off the event loop."""
        async with self._lock:
            if self._manager is None:
                # Constructing the manager connects to Tuya, so it blocks too.
                self._manager = await asyncio.to_thread(TuyaDeviceManager)
            method = getattr(self._manager, fn)
            return await asyncio.to_thread(method, *args, **kwargs)

    async def devices(self, force: bool = False) -> List[Dict[str, Any]]:
        if force or not self._devices or time.monotonic() - self._devices_at > DEVICE_CACHE_TTL:
            devices = await self._call("list_devices")
            if devices:
                self._devices = devices
                self._devices_at = time.monotonic()
            elif force:
                # An explicit refresh that came back empty should not keep
                # serving a stale list.
                self._devices = []
        return self._devices

    async def status(self, device_id: str) -> List[Dict[str, Any]]:
        return await self._call("get_device_status", device_id)

    async def switch_code(self, device_id: str) -> Optional[str]:
        """Find the DP code that acts as this device's main on/off switch."""
        if device_id in self._switch_codes:
            return self._switch_codes[device_id]

        status = await self.status(device_id)
        bool_codes = [
            s["code"] for s in status
            if isinstance(s.get("value"), bool) and s.get("code")
        ]
        code = next((c for c in SWITCH_CODE_PRIORITY if c in bool_codes), None)
        if code is None:
            code = next((c for c in bool_codes if c.startswith("switch")), None)
        if code is None:
            code = bool_codes[0] if bool_codes else None

        if code:
            self._switch_codes[device_id] = code
        return code

    async def set_switch(self, device_id: str, on: bool) -> Tuple[bool, str]:
        """Switch a device on or off. Returns (ok, detail-for-the-user)."""
        code = await self.switch_code(device_id)
        if code is None:
            return False, "no on/off control found on this device"
        ok = await self._call("control_device", device_id, code, on)
        return ok, code

    async def set_brightness(self, device_id: str, percent: int) -> Tuple[bool, str]:
        """Set brightness, if this device reports a brightness code at all."""
        status = await self.status(device_id)
        codes = {s.get("code") for s in status}
        code = next((c for c in BRIGHTNESS_CODES if c in codes), None)
        if code is None:
            return False, "unsupported"
        # Tuya brightness ranges vary by device (0-255, 10-1000). The reported
        # value's magnitude is the only hint available without the functions
        # call, so scale the percentage onto the range it implies.
        current = next((s.get("value") for s in status if s.get("code") == code), 0)
        ceiling = 1000 if isinstance(current, int) and current > 255 else 255
        value = max(1, round(percent / 100 * ceiling))
        ok = await self._call("control_device", device_id, code, value)
        return ok, code

    # --- name resolution ---------------------------------------------------

    async def resolve(self, query: str) -> List[Dict[str, Any]]:
        """
        Match a free-text name against the device list, narrowest first:
        exact name, then substring, then all-words-present in any order.
        """
        devices = await self.devices()
        q = query.strip().lower()
        if not q:
            return []

        exact = [d for d in devices if d.get("name", "").lower() == q]
        if exact:
            return exact

        substring = [d for d in devices if q in d.get("name", "").lower()]
        if substring:
            return substring

        words = q.split()
        return [
            d for d in devices
            if all(w in d.get("name", "").lower() for w in words)
        ]


# --- formatting ------------------------------------------------------------

def esc(text: Any) -> str:
    return html.escape(str(text))


def device_icon(device: Dict[str, Any]) -> str:
    category = (device.get("category") or "").lower()
    if category in ("dj", "dd", "dc", "xdd", "fwd", "tgq", "tgkg"):
        return "💡"
    if category in ("cz", "pc", "kg"):
        return "🔌"
    if category in ("wk", "wkf", "qn"):
        return "🌡"
    if category in ("cl", "clkg"):
        return "🪟"
    if category in ("mc", "ms", "sj", "rqbj", "ywbj", "pir"):
        return "🛡"
    return "▫️"


def online_marker(device: Dict[str, Any]) -> str:
    return "" if device.get("online", True) else " <i>(לא מחובר)</i>"


def format_device_list(devices: List[Dict[str, Any]]) -> str:
    if not devices:
        return (
            "לא נמצאו מכשירים.\n\n"
            "אם צריכים להיות — בדוק שחשבון האפליקציה עדיין מקושר "
            "(Tuya → Cloud → הפרויקט → Devices → Link App Account), "
            "ושה-IP של השרת נמצא ברשימת ההיתר של Tuya."
        )
    lines = [f"<b>{len(devices)} מכשירים</b>", ""]
    for d in sorted(devices, key=lambda x: x.get("name", "").lower()):
        lines.append(
            f"{device_icon(d)} <b>{esc(d.get('name', 'unnamed'))}</b>"
            f"{online_marker(d)}\n"
            f"    <code>{esc(d.get('id', '?'))}</code>"
        )
    return "\n".join(lines)


def format_status(device: Dict[str, Any], status: List[Dict[str, Any]],
                  switch_code: Optional[str]) -> str:
    name = esc(device.get("name", "unnamed"))
    lines = [f"{device_icon(device)} <b>{name}</b>{online_marker(device)}"]

    if not status:
        lines.append("\nהמכשיר לא מדווח מצב. יתכן שהוא לא מחובר.")
        return "\n".join(lines)

    by_code = {s.get("code"): s.get("value") for s in status}

    if switch_code and isinstance(by_code.get(switch_code), bool):
        lines.append(f"\nמצב: <b>{'דולק' if by_code[switch_code] else 'כבוי'}</b>"
                     f"  <code>{esc(switch_code)}</code>")

    extras = []
    for code, label in INTERESTING_CODES.items():
        if code in by_code:
            extras.append(f"{label}: <b>{esc(by_code[code])}</b>")
    if extras:
        lines.append("")
        lines.extend(extras)

    others = [
        f"<code>{esc(c)}</code> = {esc(v)}"
        for c, v in by_code.items()
        if c != switch_code and c not in INTERESTING_CODES
    ]
    if others:
        lines.append("\n<i>נתונים נוספים</i>")
        lines.extend(others)

    return "\n".join(lines)


def ambiguity_keyboard(devices: List[Dict[str, Any]], action: str) -> InlineKeyboardMarkup:
    """Buttons to disambiguate a name that matched several devices."""
    rows = [
        [InlineKeyboardButton(
            f"{device_icon(d)} {d.get('name', 'unnamed')}",
            callback_data=f"{action}|{d.get('id')}",
        )]
        for d in devices[:20]
    ]
    return InlineKeyboardMarkup(rows)


# --- handlers --------------------------------------------------------------

def authorised(bot: TuyaBot, update: Update) -> bool:
    user = update.effective_user
    if user and user.id in bot.allowed_users:
        return True
    logger.warning(
        "Rejected update from unauthorised user id=%s username=%s",
        getattr(user, "id", "?"), getattr(user, "username", "?"),
    )
    return False


def guard(handler):
    """Wrap a handler so unauthorised users get a flat refusal."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot: TuyaBot = context.application.bot_data["tuya"]
        if not authorised(bot, update):
            if update.callback_query:
                await update.callback_query.answer("Not authorised.", show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(
                    "Not authorised. Ask the owner to add your Telegram user id "
                    "to TELEGRAM_ALLOWED_USERS."
                )
            return
        return await handler(update, context)
    return wrapper


HELP = """<b>Tuya control</b>

/list — every device, with its id
/status &lt;name&gt; — what a device reports right now
/on &lt;name&gt; — switch on
/off &lt;name&gt; — switch off
/refresh — re-fetch the device list from Tuya
/whoami — your Telegram user id

Names are matched loosely, so <code>/on desk</code> finds "Desk lamp".
If a name matches more than one device you get buttons to pick from.

<b>בעברית</b> — אפשר גם פשוט לדבר או לכתוב, בלי פקודות:
🎙 שלח הודעה קולית, למשל "תכבה את האור בסלון"
⌨️ או כתוב את אותו הדבר כטקסט
השמות מותאמים לפי משמעות, גם אם המכשירים מוגדרים באנגלית."""


@guard
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP, parse_mode=ParseMode.HTML)


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Deliberately unguarded: someone locked out needs to read their own id
    # to be added to the allowlist. It reveals nothing and controls nothing.
    user = update.effective_user
    await update.effective_message.reply_text(
        f"Your Telegram user id is {user.id}." if user else "No user on this update."
    )


@guard
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot: TuyaBot = context.application.bot_data["tuya"]
    message = await update.effective_message.reply_text("Fetching…")
    try:
        devices = await bot.devices()
    except Exception as exc:
        logger.exception("list_devices failed")
        await message.edit_text(f"Tuya call failed: {esc(exc)}", parse_mode=ParseMode.HTML)
        return
    await message.edit_text(format_device_list(devices), parse_mode=ParseMode.HTML)


@guard
async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot: TuyaBot = context.application.bot_data["tuya"]
    message = await update.effective_message.reply_text("Re-fetching from Tuya…")
    try:
        devices = await bot.devices(force=True)
    except Exception as exc:
        logger.exception("forced refresh failed")
        await message.edit_text(f"Tuya call failed: {esc(exc)}", parse_mode=ParseMode.HTML)
        return
    await message.edit_text(
        f"Refreshed — {len(devices)} device(s).\n\n{format_device_list(devices)}",
        parse_mode=ParseMode.HTML,
    )


async def _resolve_or_prompt(update: Update, bot: TuyaBot, args: List[str],
                             action: str, usage: str) -> Optional[Dict[str, Any]]:
    """
    Turn command arguments into exactly one device, or reply with usage /
    'not found' / disambiguation buttons and return None.
    """
    message = update.effective_message
    if not args:
        await message.reply_text(usage, parse_mode=ParseMode.HTML)
        return None

    query = " ".join(args)
    try:
        matches = await bot.resolve(query)
    except Exception as exc:
        logger.exception("device lookup failed")
        await message.reply_text(f"Tuya call failed: {esc(exc)}", parse_mode=ParseMode.HTML)
        return None

    if not matches:
        await message.reply_text(
            f"Nothing matches “{esc(query)}”. /list shows what there is.",
            parse_mode=ParseMode.HTML,
        )
        return None

    if len(matches) > 1:
        await message.reply_text(
            f"“{esc(query)}” matches {len(matches)} devices — which one?",
            parse_mode=ParseMode.HTML,
            reply_markup=ambiguity_keyboard(matches, action),
        )
        return None

    return matches[0]


async def _apply_switch(bot: TuyaBot, device: Dict[str, Any], on: bool) -> str:
    device_id = device.get("id")
    name = esc(device.get("name", "unnamed"))
    try:
        ok, detail = await bot.set_switch(device_id, on)
    except Exception as exc:
        logger.exception("control_device failed")
        return f"⚠️ שגיאה בפנייה ל-Tuya: {esc(exc)}"

    if ok:
        return f"✅ <b>{name}</b> {'הודלק' if on else 'כובה'}."
    if device.get("online") is False:
        return f"❌ <b>{name}</b> לא קיבל את הפקודה — הוא מדווח שהוא לא מחובר."
    return f"❌ <b>{name}</b> לא קיבל את הפקודה ({esc(detail)})."


@guard
async def cmd_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot: TuyaBot = context.application.bot_data["tuya"]
    device = await _resolve_or_prompt(
        update, bot, context.args, "on",
        "Usage: <code>/on &lt;device name&gt;</code>",
    )
    if device:
        await update.effective_message.reply_text(
            await _apply_switch(bot, device, True), parse_mode=ParseMode.HTML
        )


@guard
async def cmd_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot: TuyaBot = context.application.bot_data["tuya"]
    device = await _resolve_or_prompt(
        update, bot, context.args, "off",
        "Usage: <code>/off &lt;device name&gt;</code>",
    )
    if device:
        await update.effective_message.reply_text(
            await _apply_switch(bot, device, False), parse_mode=ParseMode.HTML
        )


@guard
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot: TuyaBot = context.application.bot_data["tuya"]
    device = await _resolve_or_prompt(
        update, bot, context.args, "status",
        "Usage: <code>/status &lt;device name&gt;</code>",
    )
    if not device:
        return
    await update.effective_message.reply_text(
        await _status_text(bot, device), parse_mode=ParseMode.HTML
    )


async def _status_text(bot: TuyaBot, device: Dict[str, Any]) -> str:
    try:
        status = await bot.status(device.get("id"))
        code = await bot.switch_code(device.get("id"))
    except Exception as exc:
        logger.exception("status lookup failed")
        return f"⚠️ שגיאה בפנייה ל-Tuya: {esc(exc)}"
    return format_status(device, status, code)


@guard
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle a disambiguation button press."""
    bot: TuyaBot = context.application.bot_data["tuya"]
    query = update.callback_query
    await query.answer()

    action, _, device_id = (query.data or "").partition("|")
    devices = await bot.devices()
    device = next((d for d in devices if d.get("id") == device_id), None)
    if device is None:
        await query.edit_message_text("That device is no longer in the list. Try /refresh.")
        return

    if action == "status":
        text = await _status_text(bot, device)
    elif action in ("on", "off"):
        text = await _apply_switch(bot, device, action == "on")
    else:
        text = "Unrecognised action."

    await query.edit_message_text(text, parse_mode=ParseMode.HTML)


# --- natural language, in Hebrew ------------------------------------------

async def _run_intent(bot: TuyaBot, text: str) -> str:
    """Map an utterance to an action, perform it, and describe it in Hebrew."""
    try:
        devices = await bot.devices()
    except Exception as exc:
        logger.exception("device list failed before intent parse")
        return f"⚠️ שגיאה בפנייה ל-Tuya: {esc(exc)}"

    if not devices:
        return "לא נמצאו מכשירים בחשבון."

    try:
        result = await bot.intent.parse(text, devices)
    except Exception as exc:
        logger.exception("intent parse failed")
        return f"⚠️ לא הצלחתי להבין את הבקשה: {esc(exc)}"

    action = result["action"]
    reply = esc(result["reply_he"])
    device = next((d for d in devices if d.get("id") == result["device_id"]), None)

    if action == "unclear":
        return f"🤔 {reply}"

    if action == "list":
        return format_device_list(devices)

    if device is None:
        return "🤔 לא זיהיתי את המכשיר. נסה שוב בבקשה."

    if action == "status":
        return await _status_text(bot, device)

    if action in ("on", "off"):
        outcome = await _apply_switch(bot, device, action == "on")
        return f"{reply}\n{outcome}"

    if action == "brightness":
        percent = result["value"]
        if not isinstance(percent, int) or not 1 <= percent <= 100:
            return "🤔 לא הבנתי לאיזו עוצמה. אפשר להגיד למשל ‏\"תעמעם ל-30 אחוז\"."
        name = esc(device.get("name", ""))
        try:
            ok, detail = await bot.set_brightness(device.get("id"), percent)
        except Exception as exc:
            logger.exception("brightness failed")
            return f"⚠️ שגיאה בפנייה ל-Tuya: {esc(exc)}"
        if detail == "unsupported":
            return f"❌ ל<b>{name}</b> אין שליטה על עוצמת אור."
        if ok:
            return f"{reply}\n✅ <b>{name}</b> — העוצמה עודכנה ל-{percent}%."
        return f"❌ <b>{name}</b> לא קיבל את הפקודה."

    return "🤔 לא הבנתי מה לעשות."


@guard
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Any non-command message is treated as a spoken-style request."""
    bot: TuyaBot = context.application.bot_data["tuya"]
    message = update.effective_message
    if bot.intent is None:
        await message.reply_text(
            "שליטה בשפה חופשית אינה מוגדרת (חסר ANTHROPIC_API_KEY). "
            "אפשר להשתמש בפקודות: /list, /on, /off, /status"
        )
        return

    await message.chat.send_action(ChatAction.TYPING)
    await message.reply_text(await _run_intent(bot, message.text), parse_mode=ParseMode.HTML)


@guard
async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Transcribe a voice note, then treat the transcript as a request."""
    bot: TuyaBot = context.application.bot_data["tuya"]
    message = update.effective_message
    voice = message.voice or message.audio

    if bot.transcriber is None:
        await message.reply_text(
            "הודעות קוליות אינן מוגדרות (חסר STT_URL/STT_KEY). "
            "אפשר לכתוב את הבקשה כטקסט."
        )
        return
    if bot.intent is None:
        await message.reply_text("חסר ANTHROPIC_API_KEY, ולכן אין פענוח של בקשות חופשיות.")
        return
    if voice.duration and voice.duration > MAX_VOICE_SECONDS:
        await message.reply_text(
            f"ההודעה ארוכה מדי ({voice.duration} שניות). עד {MAX_VOICE_SECONDS} שניות."
        )
        return

    await message.chat.send_action(ChatAction.TYPING)
    try:
        handle = await voice.get_file()
        audio = bytes(await handle.download_as_bytearray())
        transcript = await bot.transcriber.transcribe(audio)
    except Exception as exc:
        logger.exception("transcription failed")
        await message.reply_text(f"⚠️ לא הצלחתי לתמלל את ההודעה: {esc(exc)}",
                                parse_mode=ParseMode.HTML)
        return

    logger.info("Transcribed %ss of audio: %r", getattr(voice, "duration", "?"), transcript)
    # Always echo the transcript: when it mishears a device name, seeing the
    # wrong word is the difference between "it's broken" and "say it again".
    outcome = await _run_intent(bot, transcript)
    await message.reply_text(
        f"🎙 <i>{esc(transcript)}</i>\n\n{outcome}", parse_mode=ParseMode.HTML
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled error while processing update", exc_info=context.error)


def main():
    token = get_config("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather and put "
            "the token in config.env (see config.env.example)."
        )

    allowed = parse_allowed_users(get_config("TELEGRAM_ALLOWED_USERS"))
    if not allowed:
        raise SystemExit(
            "TELEGRAM_ALLOWED_USERS is empty, so nobody could use the bot.\n"
            "Message the running bot with /whoami to learn your Telegram user id, "
            "then set TELEGRAM_ALLOWED_USERS=<that id> in config.env and restart.\n"
            "Refusing to start unrestricted: anyone who finds the bot would be "
            "able to switch things on and off in your home."
        )
    logger.info("Authorised Telegram user ids: %s", ", ".join(str(u) for u in sorted(allowed)))

    transcriber = Transcriber.from_config(get_config)
    intent = IntentParser.from_config(get_config)

    app = Application.builder().token(token).build()
    app.bot_data["tuya"] = TuyaBot(allowed, transcriber, intent)

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler(["list", "devices"], cmd_list))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("on", cmd_on))
    app.add_handler(CommandHandler("off", cmd_off))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    # Registered last: anything that is not a command and not audio is treated
    # as a free-text request.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    logger.info("Starting Telegram polling")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
