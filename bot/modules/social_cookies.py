from asyncio import sleep
from re import split as re_split
from os import path as ospath
from contextlib import suppress

from pyrogram import filters
from pyrogram.handlers import MessageHandler
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from .. import bot_loop, user_data
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task, update_user_ldata
from ..helper.ext_utils.cookie_utils import (
    SOCIAL_COOKIE_PLATFORMS,
    describe_cookie_report,
    normalize_cookie_file,
    social_cookie_path,
)
from ..helper.ext_utils.db_handler import database
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import delete_message, edit_message, send_message

_cookie_handlers = {}



def _method(user_id, platform):
    methods = user_data.get(user_id, {}).get("SOCIAL_AUTH_METHODS", {})
    return methods.get(platform, "cookie")

def _credentials(user_id, platform):
    creds = user_data.get(user_id, {}).get("SOCIAL_LOGIN", {})
    return creds.get(platform) if isinstance(creds, dict) else None

def _menu(user_id):
    buttons = ButtonMaker()
    for key, (label, _) in SOCIAL_COOKIE_PLATFORMS.items():
        mode = _method(user_id, key)
        icon = "🍪" if mode == "cookie" else "🔐"
        buttons.data_button(f"{icon} {label} · {mode.title()}", f"scookie {key}")
    buttons.data_button("◀️ Close", "scookie close", "footer")
    return buttons.build_menu(2)


def _status(user_id, platform):
    path = social_cookie_path(user_id, platform)
    return ospath.exists(path)


async def _render(message, user_id):
    lines = [
        "<b>🍪 Social Media Cookie Settings</b>",
        "",
        "<blockquote>Upload a Netscape-format <code>cookies.txt</code> for a platform "
        "when that site requires login.</blockquote>",
        "",
    ]
    for key, (label, _) in SOCIAL_COOKIE_PLATFORMS.items():
        state = "Cookie ✓" if _status(user_id, key) else ("Login ✓" if _credentials(user_id, key) else "Not set")
        lines.append(f"• <b>{label}:</b> {state} · <code>{_method(user_id, key)}</code>")
    lines.append("")
    lines.append("🔒 Cookies are stored per-user. Never share your cookie file.")
    await edit_message(message, "\n".join(lines), _menu(user_id))


async def _wait_for_cookie(client, query, user_id, platform):
    chat_id = query.message.chat.id

    if user_id in _cookie_handlers:
        old_item = _cookie_handlers.pop(user_id, None)
        if old_item and old_item[0]:
            with suppress(Exception):
                client.remove_handler(*old_item[0])

    prompt = await edit_message(
        query.message,
        f"<b>🍪 {SOCIAL_COOKIE_PLATFORMS[platform][0]} Cookies</b>\n\n"
        "<blockquote>Send your exported <code>cookies.txt</code> document now.\n"
        "Only Netscape-format cookie exports are accepted.\n"
        "⏱️ Time left: <code>60 sec</code></blockquote>",
        InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"scookie cancel {platform}")]]),
    )

    async def cookie_filter(_, __, event):
        u = event.from_user or event.sender_chat
        if not u or u.id != user_id or event.chat.id != chat_id:
            return False
        # If user runs any bot command, immediately abort cookie prompt and pass through
        if event.text and event.text.startswith("/"):
            _cookie_handlers.pop(user_id, None)
            with suppress(Exception):
                client.remove_handler(*handler)
            return False
        # Only catch document uploads or explicit cancel text
        if event.document:
            return True
        if event.text and event.text.lower().strip() in ("cancel", "close", "stop", "back"):
            return True
        return False

    async def pfunc(_, msg):
        if msg.chat.id != chat_id or not msg.from_user or msg.from_user.id != user_id:
            return

        if msg.text and msg.text.lower().strip() in ("cancel", "close", "stop", "back"):
            _cookie_handlers.pop(user_id, None)
            with suppress(Exception):
                client.remove_handler(*handler)
            await send_message(msg, "❌ Cookie upload cancelled.")
            with suppress(Exception):
                await _render(query.message, user_id)
            return

        if not msg.document:
            return

        name = (msg.document.file_name or "").lower()
        if not (name.endswith(".txt") or "cookie" in name):
            await send_message(msg, "❌ Please send a Netscape cookies.txt file.")
            return

        path = social_cookie_path(user_id, platform)
        try:
            await msg.download(file_name=path)
            report = normalize_cookie_file(path)
            if report.get("error") or not report.get("total"):
                with suppress(Exception):
                    import os
                    os.remove(path)
                await send_message(
                    msg,
                    "❌ Cookies were not saved.\n"
                    f"{describe_cookie_report(report)}"
                )
            else:
                update_user_ldata(user_id, "SOCIAL_COOKIE_FILES", {
                    **user_data.get(user_id, {}).get("SOCIAL_COOKIE_FILES", {}),
                    platform: path,
                })
                await database.update_user_data(user_id)
                await send_message(
                    msg,
                    f"✅ <b>{SOCIAL_COOKIE_PLATFORMS[platform][0]} cookies saved.</b>\n"
                    f"{describe_cookie_report(report)}"
                )
        except Exception as e:
            await send_message(msg, f"❌ Failed to save cookies: {e}")
        finally:
            _cookie_handlers.pop(user_id, None)
            with suppress(Exception):
                client.remove_handler(*handler)
            with suppress(Exception):
                await _render(query.message, user_id)

    handler = client.add_handler(
        MessageHandler(
            pfunc,
            filters=filters.create(cookie_filter),
        ),
        group=-2,
    )
    _cookie_handlers[user_id] = (handler, platform)

    try:
        for _ in range(120):
            if user_id not in _cookie_handlers:
                break
            await sleep(0.5)
    finally:
        _cookie_handlers.pop(user_id, None)
        with suppress(Exception):
            client.remove_handler(*handler)
        with suppress(Exception):
            await _render(query.message, user_id)


async def _wait_for_login(client, query, user_id, platform):
    chat_id = query.message.chat.id
    label = SOCIAL_COOKIE_PLATFORMS[platform][0]

    if user_id in _cookie_handlers:
        old_item = _cookie_handlers.pop(user_id, None)
        if old_item and old_item[0]:
            with suppress(Exception):
                client.remove_handler(*old_item[0])

    prompt = await edit_message(
        query.message,
        f"<b>🔐 {label} Login</b>\n\n"
        "<blockquote>Send username/email and password in two lines:\n"
        "<code>username_or_email</code>\n<code>password</code>\n\n"
        "Use only an account you are authorized to access. Delete the message after saving.</blockquote>",
        InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"scookie cancel {platform}")]]),
    )

    async def login_filter(_, __, event):
        u = event.from_user or event.sender_chat
        if not u or u.id != user_id or event.chat.id != chat_id:
            return False
        if event.text and event.text.startswith("/"):
            _cookie_handlers.pop(user_id, None)
            with suppress(Exception):
                client.remove_handler(*handler)
            return False
        return bool(event.text)

    async def pfunc(_, msg):
        if msg.chat.id != chat_id or not msg.from_user or msg.from_user.id != user_id:
            return

        if not msg.text:
            return
        if msg.text.lower().strip() in ("cancel", "close", "stop", "back"):
            _cookie_handlers.pop(user_id, None)
            with suppress(Exception):
                client.remove_handler(*handler)
            await send_message(msg, "❌ Login input cancelled.")
            with suppress(Exception):
                await _render(query.message, user_id)
            return

        parts = msg.text.splitlines()
        if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
            await send_message(msg, "❌ Invalid format. Use two lines: username/email then password.")
            return

        creds = user_data.get(user_id, {}).get("SOCIAL_LOGIN", {})
        if not isinstance(creds, dict):
            creds = {}
        creds[platform] = {"username": parts[0].strip(), "password": parts[1].strip()}
        methods = user_data.get(user_id, {}).get("SOCIAL_AUTH_METHODS", {})
        if not isinstance(methods, dict):
            methods = {}
        methods[platform] = "login"
        update_user_ldata(user_id, "SOCIAL_LOGIN", creds)
        update_user_ldata(user_id, "SOCIAL_AUTH_METHODS", methods)
        await database.update_user_data(user_id)
        with suppress(Exception):
            await msg.delete()
        _cookie_handlers.pop(user_id, None)
        with suppress(Exception):
            client.remove_handler(*handler)
        with suppress(Exception):
            await _render(query.message, user_id)

    handler = client.add_handler(
        MessageHandler(
            pfunc,
            filters=filters.create(login_filter),
        ),
        group=-2,
    )
    _cookie_handlers[user_id] = (handler, platform)

    try:
        for _ in range(120):
            if user_id not in _cookie_handlers:
                break
            await sleep(0.5)
    finally:
        _cookie_handlers.pop(user_id, None)
        with suppress(Exception):
            client.remove_handler(*handler)
        with suppress(Exception):
            await _render(query.message, user_id)


@new_task
async def cookiesettings(client, message):
    if not message.from_user or not message.chat or message.chat.type.value != "private":
        await message.reply("🔒 Please use /cookiesettings in your private chat with the bot.")
        return
    user_id = message.from_user.id
    await send_message(
        message,
        "<b>🍪 Social Media Cookie Settings</b>\n\n"
        "Choose a platform below to add or replace its cookie file.\n\n"
        "Use only cookies you are authorized to provide. Never share exported cookies.",
        _menu(user_id),
    )


@new_task
async def social_cookie_callback(client, query):
    if not query.from_user:
        return
    user_id = query.from_user.id
    data = query.data.split()
    if len(data) < 2:
        return
    await query.answer()
    if len(data) >= 3 and data[1] == "cancel":
        old_item = _cookie_handlers.pop(user_id, None)
        if old_item and old_item[0]:
            with suppress(Exception):
                client.remove_handler(*old_item[0])
        await _render(query.message, user_id)
        return
    if data[1] == "back":
        old_item = _cookie_handlers.pop(user_id, None)
        if old_item and old_item[0]:
            with suppress(Exception):
                client.remove_handler(*old_item[0])
        await _render(query.message, user_id)
        return
    if data[1] == "close":
        old_item = _cookie_handlers.pop(user_id, None)
        if old_item and old_item[0]:
            with suppress(Exception):
                client.remove_handler(*old_item[0])
        await query.message.delete()
        return
    platform = data[1]
    if platform not in SOCIAL_COOKIE_PLATFORMS:
        return
    if len(data) >= 3 and data[2] == "method":
        buttons = ButtonMaker()
        current = _method(user_id, platform)
        buttons.data_button(f"{'✓ ' if current == 'cookie' else ''}🍪 Cookie File", f"scookie {platform} setmethod cookie")
        buttons.data_button(f"{'✓ ' if current == 'login' else ''}🔐 Login", f"scookie {platform} setmethod login")
        buttons.data_button("◀️ Back", "scookie back", "footer")
        await edit_message(query.message, f"<b>🔐 {SOCIAL_COOKIE_PLATFORMS[platform][0]} Authentication Method</b>", buttons.build_menu(1))
        return
    if len(data) >= 3 and data[2] == "setmethod":
        mode = data[3] if len(data) > 3 else "cookie"
        methods = user_data.get(user_id, {}).get("SOCIAL_AUTH_METHODS", {})
        if not isinstance(methods, dict):
            methods = {}
        methods[platform] = mode
        update_user_ldata(user_id, "SOCIAL_AUTH_METHODS", methods)
        await database.update_user_data(user_id)
        if mode == "login":
            await _wait_for_login(client, query, user_id, platform)
        else:
            await _render(query.message, user_id)
        return
    if len(data) >= 3 and data[2] == "removelogin":
        creds = user_data.get(user_id, {}).get("SOCIAL_LOGIN", {})
        if isinstance(creds, dict):
            creds.pop(platform, None)
        methods = user_data.get(user_id, {}).get("SOCIAL_AUTH_METHODS", {})
        if isinstance(methods, dict):
            methods.pop(platform, None)
        await database.update_user_data(user_id)
        await _render(query.message, user_id)
        return
    if len(data) >= 3 and data[2] == "remove":
        path = social_cookie_path(user_id, platform)
        with suppress(Exception):
            import os
            os.remove(path)
        d = user_data.get(user_id, {}).get("SOCIAL_COOKIE_FILES", {})
        if isinstance(d, dict):
            d.pop(platform, None)
        await database.update_user_data(user_id)
        await _render(query.message, user_id)
        return
    if len(data) >= 3 and data[2] == "upload":
        await _wait_for_cookie(client, query, user_id, platform)
        return
    if _status(user_id, platform):
        buttons = ButtonMaker()
        buttons.data_button("🔄 Replace Cookies", f"scookie {platform} upload")
        buttons.data_button("🗑️ Remove", f"scookie {platform} remove")
        buttons.data_button("◀️ Back", "scookie back", "footer")
        await edit_message(
            query.message,
            f"<b>🍪 {SOCIAL_COOKIE_PLATFORMS[platform][0]}</b>\n\n"
            "Cookie file is already configured. You can replace or remove it.",
            buttons.build_menu(2),
        )
    else:
        await _wait_for_cookie(client, query, user_id, platform)


# callback aliases handled through the same function
