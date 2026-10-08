from asyncio import gather
from html import escape
from pyrogram.enums import ButtonStyle
from time import monotonic, time
from uuid import uuid4
from re import match

from aiofiles import open as aiopen
from cloudscraper import create_scraper
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .. import LOGGER, auth_chats, user_data
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import new_task, update_user_ldata
from ..helper.ext_utils.links_utils import decode_slink
from ..helper.ext_utils.status_utils import get_readable_time
from ..helper.ext_utils.db_handler import database
from ..helper.languages import Language
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.telegram_helper.tg_utils import chat_info
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    edit_reply_markup,
    send_file,
    send_message,
)


async def _build_start_buttons():
    buttons = ButtonMaker()
    lang = Language()
    buttons.url_button(
        lang.START_BUTTON1, "https://github.com/abhinai2244/CBML", "header"
    )
    buttons.url_button(lang.START_BUTTON2, "https://t.me/cantarellabots", "header")

    chat_ids = list(auth_chats.keys())
    if Config.AUTHORIZED_CHATS:
        for raw_id in Config.AUTHORIZED_CHATS.split():
            cid = raw_id.split("|")[0].strip()
            try:
                cid_int = int(cid)
                if cid_int not in chat_ids:
                    chat_ids.append(cid_int)
            except ValueError:
                pass

    if chat_ids:
        tasks = [chat_info(cid) for cid in chat_ids]
        chats = await gather(*tasks, return_exceptions=True)
        for idx, (cid, chat) in enumerate(zip(chat_ids, chats), 1):
            if isinstance(chat, Exception) or chat is None:
                title = f"Auth Chat {idx}"
                link = f"https://t.me/c/{str(cid)[4:]}" if str(cid).startswith("-100") else None
            else:
                title = getattr(chat, "title", None) or f"Auth Chat {idx}"
                if getattr(chat, "username", None):
                    link = f"https://t.me/{chat.username}"
                elif getattr(chat, "invite_link", None):
                    link = chat.invite_link
                elif str(cid).startswith("-100"):
                    link = f"https://t.me/c/{str(cid)[4:]}"
                else:
                    link = None

            if link:
                buttons.url_button(title, link, position="default")

    buttons.url_button(
        "TENKA IZUMO",
        "https://t.me/cantarella_wuwa",
        position="footer",
        style=ButtonStyle.DANGER,
    )

    return buttons.build_menu(b_cols=3, h_cols=2, f_cols=1)


@new_task
async def start(_, message):
    userid = message.from_user.id
    user_name = message.from_user.first_name if message.from_user else "User"
    reply_markup = await _build_start_buttons()

    if len(message.command) > 1 and message.command[1] in ("wzmlx", "htrx"):
        await delete_message(message)
    elif len(message.command) > 1 and message.command[1] != "start":
        decrypted_url = decode_slink(message.command[1])
        if Config.MEDIA_STORE and decrypted_url.startswith("file"):
            decrypted_url = decrypted_url.replace("file", "")
            chat_id, msg_id = decrypted_url.split("&&")
            LOGGER.info(f"Copying message from {chat_id} & {msg_id} to {userid}")
            return await TgClient.bot.copy_message(
                chat_id=userid,
                from_chat_id=int(chat_id) if match(r"\d+", chat_id) else chat_id,
                message_id=int(msg_id),
                disable_notification=True,
            )
        elif Config.VERIFY_TIMEOUT:
            input_token, pre_uid = decrypted_url.split("&&")
            if int(pre_uid) != userid:
                return await send_message(
                    message,
                    "<blockquote><b>Access Token is not yours!</b>\nPlease generate your own token.</blockquote>",
                )
            data = user_data.get(userid, {})
            if "VERIFY_TOKEN" not in data or data["VERIFY_TOKEN"] != input_token:
                return await send_message(
                    message,
                    "<blockquote><b>Access Token already used!</b>\nPlease generate a new one.</blockquote>",
                )
            elif (
                Config.LOGIN_PASS
                and data["VERIFY_TOKEN"].casefold() == Config.LOGIN_PASS.casefold()
            ):
                return await send_message(
                    message,
                    "<blockquote><b>Bot Already Logged In via Password</b>\nNo need to accept temporary tokens.</blockquote>",
                )
            btn = ButtonMaker()
            btn.data_button(
                "Activate Access Token", f"start pass {input_token}", "header"
            )
            token_markup = btn.build_menu(1)
            msg = f"""<b>🔑 Access Login Token</b>

<blockquote>• <b>Status:</b> Generated Successfully
• <b>Access Token:</b> <code>{input_token}</code>
• <b>Validity:</b> {get_readable_time(int(Config.VERIFY_TIMEOUT))}</blockquote>"""
            return await send_message(message, msg, token_markup)

    help_cmd = BotCommands.HelpCommand[0] if isinstance(BotCommands.HelpCommand, list) else BotCommands.HelpCommand
    if await CustomFilters.authorized(_, message):
        start_string = (
            f"<b>👋 Welcome, {escape(user_name)}!</b>\n\n"
            f"<blockquote><b>CANTARELLABOTS</b> is ready to mirror and leech files, torrents, and cloud links to Telegram or Cloud Storage.</blockquote>\n\n"
            f"<b>💡 Commands & Help:</b> Use /{help_cmd} to view all available commands and guides.\n"
            f"<b>💬 Authorized Chats:</b> Click any of the authorized chat buttons below to access supported groups."
        )
        await send_message(message, start_string, reply_markup, photo="IMAGES")
    elif Config.BOT_PM:
        start_string = (
            f"<b>👋 Welcome, {escape(user_name)}!</b>\n\n"
            f"<blockquote>Bot will send all your files and links here in private message. Start using now!</blockquote>\n\n"
            f"<b>💬 Authorized Chats:</b> Join any authorized chat below to start tasks."
        )
        await send_message(
            message,
            start_string,
            reply_markup,
            photo="IMAGES",
        )
    else:
        start_string = (
            f"<b>👋 Welcome to CANTARELLABOTS, {escape(user_name)}!</b>\n\n"
            f"<blockquote>Mirror and leech files, torrents, and links to Telegram or Cloud Storage.\n\n"
            f"<b>Note:</b> You are not authorized to use this bot instance directly in private.</blockquote>\n\n"
            f"<b>💬 Authorized Chats:</b> Join our authorized chats below to get access."
        )
        await send_message(
            message,
            start_string,
            reply_markup,
            photo="IMAGES",
        )
    await database.set_pm_users(userid)


@new_task
async def start_cb(_, query):
    user_id = query.from_user.id
    data = query.data.split()
    if len(data) < 3 or data[0] != "start":
        return await query.answer("Invalid request!", show_alert=True)
    input_token = data[2]
    u_data = user_data.get(user_id, {})

    if input_token == "activated":
        return await query.answer("Already activated!", show_alert=True)
    elif "VERIFY_TOKEN" not in u_data or u_data["VERIFY_TOKEN"] != input_token:
        return await query.answer("Already used! Please generate a new one.", show_alert=True)

    update_user_ldata(user_id, "VERIFY_TOKEN", str(uuid4()))
    update_user_ldata(user_id, "VERIFY_TIME", time())
    if Config.DATABASE_URL:
        await database.update_user_data(user_id)
    await query.answer("Access token activated successfully!", show_alert=True)

    if query.message and query.message.reply_markup and len(query.message.reply_markup.inline_keyboard) > 1:
        kb = query.message.reply_markup.inline_keyboard[1:]
        kb.insert(
            0,
            [InlineKeyboardButton("✅ Activated", callback_data="start pass activated", style=ButtonStyle.SUCCESS)],
        )
        await edit_reply_markup(query.message, InlineKeyboardMarkup(kb))


@new_task
async def login(_, message):
    if Config.LOGIN_PASS is None:
        return await send_message(message, "<blockquote>Login password feature is not enabled.</blockquote>")
    elif len(message.command) > 1:
        user_id = message.from_user.id
        input_pass = message.command[1]

        if user_data.get(user_id, {}).get("VERIFY_TOKEN", "") == Config.LOGIN_PASS:
            return await send_message(
                message, "<blockquote>Already logged in! No need to login again.</blockquote>"
            )

        if input_pass.casefold() != Config.LOGIN_PASS.casefold():
            return await send_message(
                message, "<blockquote>Incorrect password! Please try again.</blockquote>"
            )

        update_user_ldata(user_id, "VERIFY_TOKEN", Config.LOGIN_PASS)
        if Config.DATABASE_URL:
            await database.update_user_data(user_id)
        return await send_message(
            message, "<blockquote><b>Logged in successfully!</b> You can now use the bot.</blockquote>"
        )
    else:
        await send_message(
            message, "<b>🔑 Bot Login Usage Guide</b>\n\n<blockquote><code>/login [password]</code></blockquote>"
        )


@new_task
async def ping(_, message):
    start_time = monotonic()
    reply = await send_message(message, "<b>Pinging bot server...</b>")
    end_time = monotonic()
    await edit_message(
        reply, f"<b>🏓 Pong!</b>\n<blockquote><b>Latency:</b> <code>{int((end_time - start_time) * 1000)} ms</code></blockquote>"
    )


@new_task
async def log(_, message):
    uid = message.from_user.id
    buttons = ButtonMaker()
    buttons.data_button("Log Disp", f"log {uid} disp")
    buttons.data_button("Web Log", f"log {uid} web")
    buttons.data_button("Close", f"log {uid} close", style=ButtonStyle.DANGER)
    await send_file(message, "log.txt", buttons=buttons.build_menu(2))


@new_task
async def log_cb(_, query):
    data = query.data.split()
    message = query.message
    user_id = query.from_user.id
    if user_id != int(data[1]):
        await query.answer("This menu is not for you!", show_alert=True)
    elif data[2] == "close":
        await query.answer()
        await delete_message(message, message.reply_to_message)
    elif data[2] == "disp":
        await query.answer("Fetching log file...")
        async with aiopen("log.txt", "r") as f:
            content = await f.read()

        def parse(line):
            parts = line.split("] [", 1)
            return f"[{parts[1]}" if len(parts) > 1 else line

        try:
            res, total = [], 0
            for line in reversed(content.splitlines()):
                line = parse(line)
                res.append(line)
                total += len(line) + 1
                if total > 3500:
                    break
            log_content = escape("\n".join(reversed(res)))
            text = f"<b>📜 Recent Log Entries ({len(res)} lines)</b>\n\n<blockquote expandable>{log_content}</blockquote>"

            btn = ButtonMaker()
            btn.data_button("Close", f"log {user_id} close", style=ButtonStyle.DANGER)
            await send_message(message, text, btn.build_menu(1))
            await edit_reply_markup(message, None)
        except Exception as err:
            LOGGER.error(f"TG Log Display Error: {str(err)}")
    elif data[2] == "web":
        boundary = "R1eFDeaC554BUkLF"
        headers = {
            "Content-Type": f"multipart/form-data; boundary=----WebKitFormBoundary{boundary}",
            "Origin": "https://spaceb.in",
            "Referer": "https://spaceb.in/",
            "sec-ch-ua": '"Not-A.Brand";v="99", "Chromium";v="124"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        }

        async with aiopen("log.txt", "r") as f:
            content = await f.read()

        data = (
            f"------WebKitFormBoundary{boundary}\r\n"
            f'Content-Disposition: form-data; name="content"\r\n\r\n'
            f"{content}\r\n"
            f"------WebKitFormBoundary{boundary}--\r\n"
        )

        cget = create_scraper().request
        resp = cget("POST", "https://spaceb.in/", headers=headers, data=data)
        if resp.status_code == 200:
            await query.answer("Generating web paste...")
            btn = ButtonMaker()
            btn.url_button("📨 Open Web Log (Spacebin)", resp.url, style=ButtonStyle.PRIMARY)
            await edit_reply_markup(message, btn.build_menu(1))
        else:
            await query.answer("Web paste failed! Check logs.", show_alert=True)
