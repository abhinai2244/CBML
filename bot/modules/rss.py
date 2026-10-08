from json import loads as jloads, JSONDecodeError
from niquests import AsyncSession
from pyrogram.enums import ButtonStyle
from apscheduler.triggers.interval import IntervalTrigger
from asyncio import Lock, sleep
from datetime import datetime, timedelta
from feedparser import parse as feed_parse
from functools import partial
from io import BytesIO
from pyrogram.filters import create
from pyrogram.handlers import MessageHandler
from time import time
from re import compile, I

from .. import scheduler, rss_dict, LOGGER
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import (
    new_task,
    arg_parser,
    get_size_bytes,
    resolve_command,
)
from ..helper.ext_utils.status_utils import get_readable_file_size
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.exceptions import RssShutdownException
from ..helper.ext_utils.help_messages import RSS_HELP_MESSAGE
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    send_rss,
    send_file,
    delete_message,
)

rss_dict_lock = Lock()
handler_dict = {}
size_regex = compile(r"(\d+(\.\d+)?\s?(GB|MB|KB|GiB|MiB|KiB))", I)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _json_to_rss(data, feed_title="TorAPI"):
    items = (
        data
        if isinstance(data, list)
        else data.get("data", [])
        if isinstance(data, dict)
        else []
    )
    if not items:
        return None
    entries = ""
    for item in items:
        title = (
            item.get("Name", "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        url = item.get("Url", "")
        torrent = item.get("Torrent", "")
        size = item.get("Size", "")
        entries += f"""<item>
<title>{title}</title>
<link>{url}</link>
<guid isPermaLink="false">{item.get("Id", url)}</guid>
<enclosure url="{torrent}" type="application/x-bittorrent"/>
<description>Size: {size}</description>
</item>
"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torrent="http://xmlns.ezrss.it/0.1/dtd/">
<channel>
<title>{feed_title}</title>
{entries}
</channel>
</rss>"""


def _parse_feed(content):
    try:
        data = jloads(content)
        rss_xml = _json_to_rss(data)
        if rss_xml:
            return feed_parse(rss_xml)
    except (JSONDecodeError, TypeError):
        pass
    return feed_parse(content)


async def _start_rss_download(
    url, command, user_id, rss_chat_id, rss_topic_id, item_title
):
    """Send a notification to RSS_CHAT and start the download directly."""
    handler = resolve_command(command)
    if handler is None:
        LOGGER.error(f"RSS: Cannot start download, unknown command: {command}")
        return

    cmd_text = f"/{command.strip().lstrip('/')}"
    parts = cmd_text.split(maxsplit=1)
    if len(parts) > 1:
        cmd_text = f"{parts[0]} {url} {parts[1]}"
    else:
        cmd_text = f"{parts[0]} {url}"

    try:
        user = await TgClient.bot.get_users(user_id)
    except Exception as e:
        LOGGER.error(
            f"RSS: Failed to get user {user_id}, "
            f"cannot start download for '{item_title}': {e}"
        )
        return

    msg = await send_rss(cmd_text, rss_chat_id, rss_topic_id)
    if isinstance(msg, str):
        LOGGER.error(f"RSS: Failed to send to RSS_CHAT: {msg}")
        return

    msg.text = cmd_text
    msg.from_user = user
    msg._rss_trigger = True

    await handler(TgClient.bot, msg)


async def rss_menu(event):
    user_id = event.from_user.id
    buttons = ButtonMaker()
    buttons.data_button("Subscribe", f"rss sub {user_id}")
    buttons.data_button("Subscriptions", f"rss list {user_id} 0")
    buttons.data_button("Get Items", f"rss get {user_id}")
    buttons.data_button("Edit", f"rss edit {user_id}")
    buttons.data_button("Pause", f"rss pause {user_id}")
    buttons.data_button("Resume", f"rss resume {user_id}")
    buttons.data_button("Unsubscribe", f"rss unsubscribe {user_id}")
    if await CustomFilters.sudo("", event):
        buttons.data_button("All Subscriptions", f"rss listall {user_id} 0")
        buttons.data_button("Pause All", f"rss allpause {user_id}")
        buttons.data_button("Resume All", f"rss allresume {user_id}")
        buttons.data_button("Unsubscribe All", f"rss allunsub {user_id}")
        buttons.data_button("Delete User", f"rss deluser {user_id}")
        buttons.data_button("Use This Chat", f"rss setchat {user_id}")
        if scheduler.running:
            buttons.data_button("Shutdown RSS", f"rss shutdown {user_id}")
        else:
            buttons.data_button("Start RSS", f"rss start {user_id}")
    buttons.data_button("Close", f"rss close {user_id}", style=ButtonStyle.DANGER)
    button = buttons.build_menu(2)
    if chat := Config.RSS_CHAT:
        if isinstance(chat, int):
            rss_id = chat
        elif "|" in chat:
            rss_id = chat.split("|", 1)[0]
            rss_id = int(rss_id) if rss_id.lstrip("-").isdigit() else rss_id
        elif chat.lstrip("-").isdigit():
            rss_id = int(chat)
        else:
            rss_id = chat
        event_chat = getattr(event, "chat", None) or event.message.chat
        if event_chat.id == rss_id:
            chat_display = "This Chat"
        else:
            chat_display = f"<code>{chat}</code>"
    else:
        chat_display = "<b>Not Set!</b>"
    msg = f"<b>📡 RSS Feed Subscriptions Manager</b>\n\n<blockquote>• <b>Subscribed Users:</b> {len(rss_dict)}\n• <b>Scheduler Status:</b> {'Running' if scheduler.running else 'Stopped'}\n• <b>RSS Notification Chat:</b> {chat_display}</blockquote>"
    return msg, button


async def update_rss_menu(query):
    msg, button = await rss_menu(query)
    await edit_message(query.message, msg, button)


@new_task
async def get_rss_menu(_, message):
    if Config.DISABLE_RSS:
        await send_message(
            message, "<blockquote>RSS monitoring is currently disabled by the bot owner.</blockquote>"
        )
        return
    msg, button = await rss_menu(message)
    await send_message(message, msg, button)


@new_task
async def rss_sub(_, message, pre_event):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    if username := message.from_user.username:
        tag = f"@{username}"
    else:
        tag = message.from_user.mention(style="html")
    msg = ""
    items = message.text.split("\n")
    for index, item in enumerate(items, start=1):
        args = item.split()
        if len(args) < 2:
            await send_message(
                message,
                f"<blockquote>Input error at line {index}. Format: Title FeedURL [options]</blockquote>",
            )
            continue
        title = args[0].strip()
        if (user_feeds := rss_dict.get(user_id, False)) and title in user_feeds:
            await send_message(
                message, f"<blockquote>Title '<code>{title}</code>' is already subscribed!</blockquote>"
            )
            continue
        feed_link = args[1].strip()
        if feed_link.startswith(("-inf", "-exf", "-c")):
            await send_message(
                message,
                f"<blockquote>Missing title in line {index}! Please check format.</blockquote>",
            )
            continue
        inf_lists = []
        exf_lists = []
        if len(args) > 2:
            arg_base = {"-c": None, "-inf": None, "-exf": None, "-stv": None}
            arg_parser(args[2:], arg_base)
            cmd = arg_base["-c"]
            inf = arg_base["-inf"]
            exf = arg_base["-exf"]
            stv = arg_base["-stv"]
            if stv is not None:
                stv = stv.lower() == "true"
            if inf is not None:
                filters_list = inf.split("|")
                for x in filters_list:
                    y = x.split(" or ")
                    inf_lists.append(y)
            if exf is not None:
                filters_list = exf.split("|")
                for x in filters_list:
                    y = x.split(" or ")
                    exf_lists.append(y)
        else:
            inf = None
            exf = None
            cmd = None
            stv = False
        try:
            async with AsyncSession() as client:
                client.headers.update(headers)
                res = await client.get(feed_link, allow_redirects=True, timeout=60)
            html = res.text
            rss_d = _parse_feed(html)
            last_link = ""
            last_title = ""
            size = 0
            feed_title = rss_d.feed.get("title", "Unknown")
            if rss_d.entries:
                last_title = rss_d.entries[0]["title"]
                if rss_d.entries[0].get("size"):
                    size = int(rss_d.entries[0]["size"])
                elif rss_d.entries[0].get("summary"):
                    summary = rss_d.entries[0]["summary"]
                    matches = size_regex.findall(summary)
                    sizes = [match[0] for match in matches]
                    size = get_size_bytes(sizes[0])
                try:
                    last_link = rss_d.entries[0]["links"][1]["href"]
                except IndexError:
                    last_link = rss_d.entries[0]["link"]
            msg += f"<b>📡 RSS Subscription Added</b>\n\n"
            msg += f"<blockquote>• <b>Title:</b> <code>{title}</code>\n• <b>Feed URL:</b> {feed_link}\n"
            if rss_d.entries:
                msg += f"• <b>Latest Item ({feed_title}):</b> <code>{last_title.replace('>', '').replace('<', '')}</code>\n"
                msg += f"• <b>Latest Link:</b> <code>{last_link}</code>\n"
                if size:
                    msg += f"• <b>Size:</b> {get_readable_file_size(size)}\n"
            else:
                msg += "• <b>Note:</b> Feed is empty right now. New items will be monitored.\n"
            msg += f"• <b>Command:</b> <code>{cmd or 'None'}</code>\n"
            msg += f"• <b>Include Filter:</b> <code>{inf or 'None'}</code>\n• <b>Exclude Filter:</b> <code>{exf or 'None'}</code>\n• <b>Case Sensitive:</b> {stv}</blockquote>"
            async with rss_dict_lock:
                if rss_dict.get(user_id, False):
                    rss_dict[user_id][title] = {
                        "link": feed_link,
                        "last_feed": last_link,
                        "last_title": last_title,
                        "inf": inf_lists,
                        "exf": exf_lists,
                        "paused": False,
                        "command": cmd,
                        "sensitive": stv,
                        "tag": tag,
                    }
                else:
                    rss_dict[user_id] = {
                        title: {
                            "link": feed_link,
                            "last_feed": last_link,
                            "last_title": last_title,
                            "inf": inf_lists,
                            "exf": exf_lists,
                            "paused": False,
                            "command": cmd,
                            "sensitive": stv,
                            "tag": tag,
                        }
                    }
            LOGGER.info(
                f"Rss Feed Added: id: {user_id} - title: {title} - link: {feed_link} - c: {cmd} - inf: {inf} - exf: {exf} - stv {stv}"
            )
        except (IndexError, AttributeError) as e:
            emsg = f"The URL {feed_link} does not appear to be a valid RSS feed."
            await send_message(message, f"<blockquote>{emsg}\nError: {e}</blockquote>")
        except Exception as e:
            await send_message(message, f"<blockquote>{e}</blockquote>")
    if msg:
        await database.rss_update(user_id)
        await send_message(message, msg)
        is_sudo = await CustomFilters.sudo("", message)
        if scheduler.state == 2:
            scheduler.resume()
        elif is_sudo and not scheduler.running:
            add_job()
            scheduler.start()
    await update_rss_menu(pre_event)


async def get_user_id(title):
    async with rss_dict_lock:
        return next(
            (
                (True, user_id)
                for user_id, feed in rss_dict.items()
                if feed["title"] == title
            ),
            (False, False),
        )


@new_task
async def rss_update(_, message, pre_event, state):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    titles = message.text.split()
    is_sudo = await CustomFilters.sudo("", message)
    updated = []
    for title in titles:
        title = title.strip()
        if not (res := rss_dict[user_id].get(title, False)):
            if is_sudo:
                res, user_id = await get_user_id(title)
            if not res:
                user_id = message.from_user.id
                await send_message(message, f"<blockquote>Feed '<code>{title}</code>' not found!</blockquote>")
                continue
        istate = rss_dict[user_id][title].get("paused", False)
        if istate and state == "pause" or not istate and state == "resume":
            await send_message(message, f"<blockquote>Feed '<code>{title}</code>' is already {state}d!</blockquote>")
            continue
        async with rss_dict_lock:
            updated.append(title)
            if state == "unsubscribe":
                del rss_dict[user_id][title]
            elif state == "pause":
                rss_dict[user_id][title]["paused"] = True
            elif state == "resume":
                rss_dict[user_id][title]["paused"] = False
        if state == "resume":
            if scheduler.state == 2:
                scheduler.resume()
            elif is_sudo and not scheduler.running:
                add_job()
                scheduler.start()
        if is_sudo and Config.DATABASE_URL and user_id != message.from_user.id:
            await database.rss_update(user_id)
        if not rss_dict[user_id]:
            async with rss_dict_lock:
                del rss_dict[user_id]
            await database.rss_delete(user_id)
            if not rss_dict:
                await database.trunc_table("rss")
    if updated:
        LOGGER.info(f"Rss link with Title(s): {updated} has been {state}d!")
        await send_message(
            message,
            f"<blockquote>RSS feed subscription(s) <code>{updated}</code> have been {state}d!</blockquote>",
        )
        if rss_dict.get(user_id):
            await database.rss_update(user_id)
    await update_rss_menu(pre_event)


async def rss_list(query, start, all_users=False):
    user_id = query.from_user.id
    buttons = ButtonMaker()
    if all_users:
        list_feed = f"<b>All RSS Subscriptions (Page {int(start / 5) + 1})</b>\n\n"
        async with rss_dict_lock:
            keysCount = sum(len(v.keys()) for v in rss_dict.values())
            index = 0
            for titles in rss_dict.values():
                for index, (title, data) in enumerate(
                    list(titles.items())[start : 5 + start]
                ):
                    list_feed += f"<blockquote>• <b>Title:</b> <code>{title}</code>\n"
                    list_feed += f"• <b>URL:</b> <code>{data['link']}</code>\n"
                    list_feed += f"• <b>Command:</b> <code>{data['command']}</code>\n"
                    list_feed += f"• <b>Inf:</b> <code>{data['inf']}</code>\n"
                    list_feed += f"• <b>Exf:</b> <code>{data['exf']}</code>\n"
                    list_feed += f"• <b>Sensitive:</b> <code>{data.get('sensitive', False)}</code>\n"
                    list_feed += f"• <b>Paused:</b> <code>{data['paused']}</code>\n"
                    list_feed += f"• <b>User:</b> {data['tag'].replace('@', '', 1)}</blockquote>\n\n"
                    index += 1
                    if index == 5:
                        break
    else:
        list_feed = f"<b>Your RSS Subscriptions (Page {int(start / 5) + 1})</b>\n\n"
        async with rss_dict_lock:
            keysCount = len(rss_dict.get(user_id, {}).keys())
            for title, data in list(rss_dict[user_id].items())[start : 5 + start]:
                list_feed += f"<blockquote>• <b>Title:</b> <code>{title}</code>\n"
                list_feed += f"• <b>URL:</b> <code>{data['link']}</code>\n"
                list_feed += f"• <b>Command:</b> <code>{data['command']}</code>\n"
                list_feed += f"• <b>Inf:</b> <code>{data['inf']}</code>\n"
                list_feed += f"• <b>Exf:</b> <code>{data['exf']}</code>\n"
                list_feed += f"• <b>Sensitive:</b> <code>{data.get('sensitive', False)}</code>\n"
                list_feed += f"• <b>Paused:</b> <code>{data['paused']}</code></blockquote>\n\n"
    buttons.data_button("◀️ Back", f"rss back {user_id}")
    buttons.data_button("❌ Close", f"rss close {user_id}", style=ButtonStyle.DANGER)
    if keysCount > 5:
        for x in range(0, keysCount, 5):
            buttons.data_button(
                f"{int(x / 5) + 1}", f"rss list {user_id} {x}", position="footer"
            )
    button = buttons.build_menu(2)
    if query.message.text.html == list_feed:
        return
    await edit_message(query.message, list_feed, button)


@new_task
async def rss_get(_, message, pre_event):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    args = message.text.split()
    if len(args) < 2:
        await send_message(
            message,
            "<blockquote>Input error. Specify Title and item count (e.g. <code>MyTitle 5</code>).</blockquote>",
        )
        await update_rss_menu(pre_event)
        return
    try:
        title = args[0]
        count = int(args[1])
        data = rss_dict[user_id].get(title, False)
        if data and count > 0:
            try:
                msg = await send_message(
                    message, f"<b>Fetching last {count} items from <code>{title}</code>...</b>"
                )
                async with AsyncSession() as client:
                    client.headers.update(headers)
                    res = await client.get(data["link"], allow_redirects=True, timeout=60)
                html = res.text
                rss_d = _parse_feed(html)
                item_info = f"<b>📡 RSS Items: {title}</b>\n\n"
                for item_num in range(count):
                    try:
                        link = rss_d.entries[item_num]["links"][1]["href"]
                    except IndexError:
                        link = rss_d.entries[item_num]["link"]
                    item_info += f"<blockquote>• <b>Name:</b> <code>{rss_d.entries[item_num]['title'].replace('>', '').replace('<', '')}</code>\n"
                    item_info += f"• <b>Link:</b> <code>{link}</code></blockquote>\n\n"
                item_info_ecd = item_info.encode()
                if len(item_info_ecd) > 4000:
                    with BytesIO(item_info_ecd) as out_file:
                        out_file.name = f"rssGet {title} items_no. {count}.txt"
                        await send_file(message, out_file)
                    await delete_message(msg)
                else:
                    await edit_message(msg, item_info)
            except IndexError as e:
                LOGGER.error(f"RSS get: {e}")
                await edit_message(
                    msg, "<blockquote>Parse depth exceeded. Try again with a smaller item count.</blockquote>"
                )
            except Exception as e:
                LOGGER.error(f"RSS get: {e}")
                await edit_message(msg, f"<blockquote>{str(e) or 'Unknown error occurred'}</blockquote>")
        else:
            await send_message(message, "<blockquote>Feed title not found! Please enter a valid title.</blockquote>")
    except Exception as e:
        LOGGER.error(f"RSS get: {e}")
        await send_message(message, f"<blockquote>Input error: {e}</blockquote>")
    await update_rss_menu(pre_event)


@new_task
async def rss_edit(_, message, pre_event):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    items = message.text.split("\n")
    updated = False
    for item in items:
        args = item.split()
        title = args[0].strip()
        if len(args) < 2:
            await send_message(
                message,
                f"<blockquote>Input error at line <code>{item}</code>. Check help format.</blockquote>",
            )
            continue
        elif not rss_dict[user_id].get(title, False):
            await send_message(message, f"<blockquote>Feed '<code>{title}</code>' not found!</blockquote>")
            continue
        updated = True
        inf_lists = []
        exf_lists = []
        arg_base = {"-c": None, "-inf": None, "-exf": None, "-stv": None}
        arg_parser(args[1:], arg_base)
        cmd = arg_base["-c"]
        inf = arg_base["-inf"]
        exf = arg_base["-exf"]
        stv = arg_base["-stv"]
        async with rss_dict_lock:
            if stv is not None:
                stv = stv.lower() == "true"
                rss_dict[user_id][title]["sensitive"] = stv
            if cmd is not None:
                if cmd.lower() == "none":
                    cmd = None
                rss_dict[user_id][title]["command"] = cmd
            if inf is not None:
                if inf.lower() != "none":
                    filters_list = inf.split("|")
                    for x in filters_list:
                        y = x.split(" or ")
                        inf_lists.append(y)
                rss_dict[user_id][title]["inf"] = inf_lists
            if exf is not None:
                if exf.lower() != "none":
                    filters_list = exf.split("|")
                    for x in filters_list:
                        y = x.split(" or ")
                        exf_lists.append(y)
                rss_dict[user_id][title]["exf"] = exf_lists
    if updated:
        await database.rss_update(user_id)
    await update_rss_menu(pre_event)


@new_task
async def rss_delete(_, message, pre_event):
    handler_dict[message.from_user.id] = False
    users = message.text.split()
    for user in users:
        user = int(user)
        async with rss_dict_lock:
            del rss_dict[user]
        await database.rss_delete(user)
    await update_rss_menu(pre_event)


async def event_handler(client, query, pfunc):
    user_id = query.from_user.id
    handler_dict[user_id] = True
    start_time = time()

    async def event_filter(_, __, event):
        user = event.from_user or event.sender_chat
        return bool(
            user.id == user_id and event.chat.id == query.message.chat.id and event.text
        )

    handler = client.add_handler(MessageHandler(pfunc, create(event_filter)), group=-1)
    while handler_dict[user_id]:
        await sleep(0.5)
        if time() - start_time > 60:
            handler_dict[user_id] = False
            await update_rss_menu(query)
    client.remove_handler(*handler)


@new_task
async def rss_listener(client, query):
    user_id = query.from_user.id
    message = query.message
    data = query.data.split()
    if int(data[2]) != user_id and not await CustomFilters.sudo("", query):
        await query.answer(
            text="This menu is not for you!", show_alert=True
        )
    elif data[1] == "close":
        await query.answer()
        handler_dict[user_id] = False
        await delete_message(message, message.reply_to_message)
    elif data[1] == "back":
        await query.answer()
        handler_dict[user_id] = False
        await update_rss_menu(query)
    elif data[1] == "sub":
        await query.answer()
        handler_dict[user_id] = False
        buttons = ButtonMaker()
        buttons.data_button("◀️ Back", f"rss back {user_id}")
        buttons.data_button("❌ Close", f"rss close {user_id}", style=ButtonStyle.DANGER)
        button = buttons.build_menu(2)
        await edit_message(message, RSS_HELP_MESSAGE, button)
        pfunc = partial(rss_sub, pre_event=query)
        await event_handler(client, query, pfunc)
    elif data[1] == "list":
        handler_dict[user_id] = False
        if len(rss_dict.get(int(data[2]), {})) == 0:
            await query.answer(text="No active RSS subscriptions found!", show_alert=True)
        else:
            await query.answer()
            start = int(data[3])
            await rss_list(query, start)
    elif data[1] == "get":
        handler_dict[user_id] = False
        if len(rss_dict.get(int(data[2]), {})) == 0:
            await query.answer(text="No active RSS subscriptions found!", show_alert=True)
        else:
            await query.answer()
            buttons = ButtonMaker()
            buttons.data_button("◀️ Back", f"rss back {user_id}")
            buttons.data_button(
                "❌ Close", f"rss close {user_id}", style=ButtonStyle.DANGER
            )
            button = buttons.build_menu(2)
            await edit_message(
                message,
                "<blockquote>Send title and item count separated by space:\nExample: <code>MyTitle 5</code>\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
                button,
            )
            pfunc = partial(rss_get, pre_event=query)
            await event_handler(client, query, pfunc)
    elif data[1] in ["unsubscribe", "pause", "resume"]:
        handler_dict[user_id] = False
        if len(rss_dict.get(int(data[2]), {})) == 0:
            await query.answer(text="No active RSS subscriptions found!", show_alert=True)
        else:
            await query.answer()
            buttons = ButtonMaker()
            buttons.data_button("◀️ Back", f"rss back {user_id}")
            if data[1] == "pause":
                buttons.data_button("Pause All My Feeds", f"rss uallpause {user_id}")
            elif data[1] == "resume":
                buttons.data_button("Resume All My Feeds", f"rss uallresume {user_id}")
            elif data[1] == "unsubscribe":
                buttons.data_button("Unsub All My Feeds", f"rss uallunsub {user_id}")
            buttons.data_button(
                "❌ Close", f"rss close {user_id}", style=ButtonStyle.DANGER
            )
            button = buttons.build_menu(2)
            await edit_message(
                message,
                f"<blockquote>Send feed titles separated by space to {data[1]}.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
                button,
            )
            pfunc = partial(rss_update, pre_event=query, state=data[1])
            await event_handler(client, query, pfunc)
    elif data[1] == "edit":
        handler_dict[user_id] = False
        if len(rss_dict.get(int(data[2]), {})) == 0:
            await query.answer(text="No active RSS subscriptions found!", show_alert=True)
        else:
            await query.answer()
            buttons = ButtonMaker()
            buttons.data_button("◀️ Back", f"rss back {user_id}")
            buttons.data_button(
                "❌ Close", f"rss close {user_id}", style=ButtonStyle.DANGER
            )
            button = buttons.build_menu(2)
            msg = """<b>✏️ Edit RSS Subscription Filters</b>

<blockquote>Send updated title filters on a new line:
Example:
<code>Title1 -c mirror -up remote:path -exf sample -inf 1080 -stv true</code>
⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>"""
            await edit_message(message, msg, button)
            pfunc = partial(rss_edit, pre_event=query)
            await event_handler(client, query, pfunc)
    elif data[1].startswith("uall"):
        handler_dict[user_id] = False
        if len(rss_dict.get(int(data[2]), {})) == 0:
            await query.answer(text="No active RSS subscriptions found!", show_alert=True)
            return
        await query.answer()
        if data[1].endswith("unsub"):
            async with rss_dict_lock:
                del rss_dict[int(data[2])]
            await database.rss_delete(int(data[2]))
            await update_rss_menu(query)
        elif data[1].endswith("pause"):
            async with rss_dict_lock:
                for info in rss_dict[int(data[2])].values():
                    info["paused"] = True
            await database.rss_update(int(data[2]))
        elif data[1].endswith("resume"):
            async with rss_dict_lock:
                for info in rss_dict[int(data[2])].values():
                    info["paused"] = False
            if scheduler.state == 2:
                scheduler.resume()
            await database.rss_update(int(data[2]))
        await update_rss_menu(query)
    elif data[1].startswith("all"):
        if len(rss_dict) == 0:
            await query.answer(text="No active RSS subscriptions found!", show_alert=True)
            return
        await query.answer()
        if data[1].endswith("unsub"):
            async with rss_dict_lock:
                rss_dict.clear()
            await database.trunc_table("rss")
            await update_rss_menu(query)
        elif data[1].endswith("pause"):
            async with rss_dict_lock:
                for user_feeds in rss_dict.values():
                    for feed in user_feeds.values():
                        feed["paused"] = True
            if scheduler.running:
                scheduler.pause()
            await database.rss_update_all()
        elif data[1].endswith("resume"):
            async with rss_dict_lock:
                for user_feeds in rss_dict.values():
                    for feed in user_feeds.values():
                        feed["paused"] = False
            if scheduler.state == 2:
                scheduler.resume()
            elif not scheduler.running:
                add_job()
                scheduler.start()
                await update_rss_menu(query)
            await database.rss_update_all()
    elif data[1] == "deluser":
        if len(rss_dict) == 0:
            await query.answer(text="No active RSS subscriptions found!", show_alert=True)
        else:
            await query.answer()
            buttons = ButtonMaker()
            buttons.data_button("◀️ Back", f"rss back {user_id}")
            buttons.data_button(
                "❌ Close", f"rss close {user_id}", style=ButtonStyle.DANGER
            )
            button = buttons.build_menu(2)
            msg = "<blockquote>Send user IDs separated by space to remove their RSS feeds.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>"
            await edit_message(message, msg, button)
            pfunc = partial(rss_delete, pre_event=query)
            await event_handler(client, query, pfunc)
    elif data[1] == "listall":
        if not rss_dict:
            await query.answer(text="No active RSS subscriptions found!", show_alert=True)
        else:
            await query.answer()
            start = int(data[3])
            await rss_list(query, start, all_users=True)
    elif data[1] == "shutdown":
        if scheduler.running:
            await query.answer()
            scheduler.shutdown(wait=False)
            await sleep(0.5)
            await update_rss_menu(query)
        else:
            await query.answer(text="RSS scheduler already stopped!", show_alert=True)
    elif data[1] == "start":
        if not scheduler.running:
            await query.answer()
            add_job()
            scheduler.start()
            await update_rss_menu(query)
        else:
            await query.answer(text="RSS scheduler already running!", show_alert=True)
    elif data[1] == "setchat":
        chat_id = message.chat.id
        topic_msg = getattr(message, "topic_message", False)
        thread_id = message.message_thread_id if topic_msg else None
        chat_value = f"{chat_id}|{thread_id}" if thread_id else str(chat_id)
        old_value = Config.RSS_CHAT
        Config.set("RSS_CHAT", chat_value)
        await database.update_config({"RSS_CHAT": chat_value})
        await query.answer(text=f"RSS_CHAT set to {chat_value}", show_alert=True)
        if not scheduler.running:
            add_job()
            scheduler.start()
        if str(old_value) != chat_value:
            await update_rss_menu(query)


async def rss_monitor():
    chat = Config.RSS_CHAT
    if not chat:
        LOGGER.warning("RSS_CHAT not added! Shutting down rss scheduler...")
        scheduler.shutdown(wait=False)
        return
    if len(rss_dict) == 0:
        scheduler.pause()
        return
    all_paused = True
    rss_topic_id = rss_chat_id = None
    if isinstance(chat, int):
        rss_chat_id = chat
    elif "|" in chat:
        rss_chat_id, rss_topic_id = list(
            map(
                lambda x: int(x) if x.lstrip("-").isdigit() else x,
                chat.split("|", 1),
            )
        )
    elif chat.lstrip("-").isdigit():
        rss_chat_id = int(chat)
    for user, items in list(rss_dict.items()):
        for title, data in list(items.items()):
            try:
                if data["paused"]:
                    continue
                tries = 0
                while True:
                    try:
                        async with AsyncSession() as client:
                            client.headers.update(headers)
                            res = await client.get(data["link"], allow_redirects=True, timeout=60)
                        html = res.text
                        break
                    except Exception:
                        tries += 1
                        if tries > 3:
                            raise
                        continue
                rss_d = _parse_feed(html)
                if not rss_d.entries:
                    LOGGER.warning(
                        f"No entries found for > Feed Title: {title} - Feed Link: {data['link']}"
                    )
                    continue
                entry0 = rss_d.entries[0]
                links = entry0.get("links", [])
                if len(links) > 1:
                    last_link = links[1].get("href")
                elif links:
                    last_link = links[0].get("href")
                else:
                    last_link = entry0.get("link")
                last_title = entry0.get("title")
                all_paused = False
                if data["last_feed"] == last_link or data["last_title"] == last_title:
                    continue
                feed_count = 0
                while True:
                    try:
                        await sleep(10)
                    except Exception:
                        raise RssShutdownException("RSS Monitor Stopped!")
                    try:
                        item_title = rss_d.entries[feed_count]["title"]
                        try:
                            url = rss_d.entries[feed_count]["links"][1]["href"]
                        except IndexError:
                            url = rss_d.entries[feed_count]["link"]
                        if data["last_feed"] == url or data["last_title"] == item_title:
                            break
                        if rss_d.entries[feed_count].get("size"):
                            size = int(rss_d.entries[feed_count]["size"])
                        elif rss_d.entries[feed_count].get("summary"):
                            summary = rss_d.entries[feed_count]["summary"]
                            matches = size_regex.findall(summary)
                            sizes = [match[0] for match in matches]
                            size = get_size_bytes(sizes[0])
                        else:
                            size = 0
                    except IndexError:
                        LOGGER.warning(
                            f"Reached Max index no. {feed_count} for this feed: {title}."
                        )
                        break
                    parse = True
                    for flist in data["inf"]:
                        if (
                            data.get("sensitive", False)
                            and all(x.lower() not in item_title.lower() for x in flist)
                        ) or (
                            not data.get("sensitive", False)
                            and all(x not in item_title for x in flist)
                        ):
                            parse = False
                            feed_count += 1
                            break
                    if not parse:
                        continue
                    for flist in data["exf"]:
                        if (
                            data.get("sensitive", False)
                            and any(x.lower() in item_title.lower() for x in flist)
                        ) or (
                            not data.get("sensitive", False)
                            and any(x in item_title for x in flist)
                        ):
                            parse = False
                            feed_count += 1
                            break
                    if not parse:
                        continue
                    if command := data["command"]:
                        if (
                            size
                            and Config.RSS_SIZE_LIMIT
                            and Config.RSS_SIZE_LIMIT < size
                        ):
                            feed_count += 1
                            continue
                        await _start_rss_download(
                            url=url,
                            command=command,
                            user_id=user,
                            rss_chat_id=rss_chat_id,
                            rss_topic_id=rss_topic_id,
                            item_title=item_title,
                        )
                    else:
                        feed_msg = f"<b>📡 New RSS Item Found</b>\n\n"
                        feed_msg += f"<blockquote>• <b>Name:</b> <code>{item_title.replace('>', '').replace('<', '')}</code>\n"
                        feed_msg += f"• <b>Link:</b> <code>{url}</code>\n"
                        if size:
                            feed_msg += f"• <b>Size:</b> {get_readable_file_size(size)}\n"
                        feed_msg += f"• <b>User:</b> <code>{data['tag']}</code> (<code>#ID{user}</code>)</blockquote>"
                        await send_rss(feed_msg, rss_chat_id, rss_topic_id)
                    feed_count += 1
                async with rss_dict_lock:
                    if user not in rss_dict or not rss_dict[user].get(title, False):
                        continue
                    rss_dict[user][title].update(
                        {"last_feed": last_link, "last_title": last_title}
                    )
                await database.rss_update(user)
                LOGGER.info(f"Feed Name: {title}")
                LOGGER.info(f"Last item: {last_link}")
            except RssShutdownException as ex:
                LOGGER.info(ex)
                break
            except Exception as e:
                LOGGER.error(
                    f"RSS monitor: {e} - Feed Name: {title} - Feed Link: {data['link']}"
                )
                continue
    if all_paused:
        scheduler.pause()


def add_job():
    scheduler.add_job(
        rss_monitor,
        trigger=IntervalTrigger(seconds=Config.RSS_DELAY),
        id="0",
        name="RSS",
        misfire_grace_time=15,
        max_instances=1,
        next_run_time=datetime.now() + timedelta(seconds=20),
        replace_existing=True,
    )


add_job()
if not Config.DISABLE_RSS:
    scheduler.start()
else:
    LOGGER.info("RSS monitoring is disabled.")
