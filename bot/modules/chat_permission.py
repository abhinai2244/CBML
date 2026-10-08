from time import time

from .. import user_data
from ..helper.ext_utils.bot_utils import update_user_ldata, new_task
from ..helper.ext_utils.db_handler import database
from ..helper.telegram_helper.message_utils import send_message


def _parse_time(time_str):
    time_str = time_str.strip().lower()
    mult = {"d": 86400, "h": 3600, "m": 60}
    for suffix, factor in mult.items():
        if time_str.endswith(suffix):
            try:
                return int(time_str[: -len(suffix)]) * factor
            except ValueError:
                return None
    return None


def _format_remaining(seconds):
    if seconds >= 86400:
        d = seconds // 86400
        h = (seconds % 86400) // 3600
        return f"{d}d {h}h" if h else f"{d}d"
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m" if m else f"{h}h"
    m = seconds // 60
    return f"{m}m"


def _get_blacklist_info(bl_value):
    if not bl_value:
        return False, None
    if bl_value is True:
        return True, "Permanent"
    if isinstance(bl_value, (int, float)):
        remaining = bl_value - time()
        if remaining > 0:
            return True, _format_remaining(int(remaining))
        return False, None
    return False, None


@new_task
async def authorize(_, message):
    msg = message.text.split()
    thread_id = None
    if len(msg) > 1:
        if "|" in msg[1]:
            chat_id, thread_id = list(map(int, msg[1].split("|")))
        else:
            chat_id = int(msg[1].strip())
    elif (
        reply_to := message.reply_to_message
    ) and reply_to.id != message.message_thread_id:
        chat_id = (reply_to.from_user or reply_to.sender_chat).id
    else:
        if message.is_topic_message:
            thread_id = message.message_thread_id
        chat_id = message.chat.id
    if chat_id in user_data and user_data[chat_id].get("AUTH"):
        if (
            thread_id is not None
            and thread_id in user_data[chat_id].get("thread_ids", [])
            or thread_id is None
        ):
            msg = "<blockquote>Chat or user is already authorized!</blockquote>"
        else:
            if "thread_ids" in user_data[chat_id]:
                user_data[chat_id]["thread_ids"].append(thread_id)
            else:
                user_data[chat_id]["thread_ids"] = [thread_id]
            msg = f"<blockquote><b>Authorized successfully!</b> Chat ID: <code>{chat_id}</code></blockquote>"
    else:
        update_user_ldata(chat_id, "AUTH", True)
        if thread_id is not None:
            update_user_ldata(chat_id, "thread_ids", [thread_id])
        await database.update_user_data(chat_id)
        msg = f"<blockquote><b>Authorized successfully!</b> Chat ID: <code>{chat_id}</code></blockquote>"
    await send_message(message, msg)


@new_task
async def unauthorize(_, message):
    msg = message.text.split()
    thread_id = None
    if len(msg) > 1:
        if "|" in msg[1]:
            chat_id, thread_id = list(map(int, msg[1].split("|")))
        else:
            chat_id = int(msg[1].strip())
    elif (
        reply_to := message.reply_to_message
    ) and reply_to.id != message.message_thread_id:
        chat_id = (reply_to.from_user or reply_to.sender_chat).id
    else:
        if message.is_topic_message:
            thread_id = message.message_thread_id
        chat_id = message.chat.id
    if chat_id in user_data and user_data[chat_id].get("AUTH"):
        if thread_id and thread_id in user_data[chat_id].get("thread_ids", []):
            user_data[chat_id]["thread_ids"].remove(thread_id)
            if not user_data[chat_id].get("thread_ids"):
                update_user_ldata(chat_id, "AUTH", False)
        else:
            update_user_ldata(chat_id, "AUTH", False)
        await database.update_user_data(chat_id)
        msg = f"<blockquote><b>Unauthorized successfully!</b> Chat ID: <code>{chat_id}</code></blockquote>"
    else:
        msg = "<blockquote>Chat or user is already unauthorized!</blockquote>"
    await send_message(message, msg)


@new_task
async def add_sudo(_, message):
    id_ = ""
    msg = message.text.split()
    if len(msg) > 1:
        id_ = int(msg[1].strip())
    elif reply_to := message.reply_to_message:
        id_ = (reply_to.from_user or reply_to.sender_chat).id
    if id_:
        if id_ in user_data and user_data[id_].get("SUDO"):
            msg = "<blockquote>User is already a Sudo user!</blockquote>"
        else:
            update_user_ldata(id_, "SUDO", True)
            await database.update_user_data(id_)
            msg = f"<blockquote><b>Promoted as Sudo user!</b> User ID: <code>{id_}</code></blockquote>"
    else:
        msg = "<blockquote>Provide user ID or reply to a user's message to promote.</blockquote>"
    await send_message(message, msg)


@new_task
async def remove_sudo(_, message):
    id_ = ""
    msg = message.text.split()
    if len(msg) > 1:
        id_ = int(msg[1].strip())
    elif reply_to := message.reply_to_message:
        id_ = (reply_to.from_user or reply_to.sender_chat).id
    if id_:
        if id_ in user_data and user_data[id_].get("SUDO"):
            update_user_ldata(id_, "SUDO", False)
            await database.update_user_data(id_)
            msg = f"<blockquote><b>Demoted Sudo user!</b> User ID: <code>{id_}</code></blockquote>"
        else:
            msg = "<blockquote>User is not a Sudo user! Sudo users added via config must be removed from config.env.</blockquote>"
    else:
        msg = "<blockquote>Provide user ID or reply to a user's message to demote.</blockquote>"
    await send_message(message, msg)


@new_task
async def add_blacklist(_, message):
    msg = message.text.split()
    id_ = None
    time_str = None

    i = 1
    while i < len(msg):
        arg = msg[i].lower()
        if arg.startswith("-t") and len(arg) > 2:
            time_str = arg[2:]
            i += 1
        elif arg == "-t" and i + 1 < len(msg):
            time_str = msg[i + 1]
            i += 2
        else:
            try:
                id_ = int(msg[i])
            except ValueError:
                pass
            i += 1

    if id_ is None and message.reply_to_message:
        id_ = (
            message.reply_to_message.from_user or message.reply_to_message.sender_chat
        ).id

    if id_ is None:
        help_msg = """<b>🚫 Blacklist Usage Guide</b>

<blockquote>• <b>Permanent:</b> <code>/bl {user_id}</code>
• <b>Temporary:</b> <code>/bl {user_id} -t 1d</code>
• <b>Reply:</b> Reply to message with <code>/bl -t 2h</code>
• <b>Time Units:</b> <code>1d</code> (days), <code>12h</code> (hours), <code>30m</code> (minutes)</blockquote>"""
        return await send_message(message, help_msg)

    if id_ in user_data and _get_blacklist_info(user_data[id_].get("BLACKLIST"))[0]:
        return await send_message(
            message, f"<blockquote><b>User already blacklisted!</b> ID: <code>{id_}</code></blockquote>"
        )

    if time_str:
        seconds = _parse_time(time_str)
        if seconds is None:
            return await send_message(
                message,
                "<blockquote>Invalid time format! Use <code>1d</code>, <code>2h</code>, or <code>30m</code>.</blockquote>",
            )
        bl_value = time() + seconds
        remaining = _format_remaining(seconds)
        update_user_ldata(id_, "BLACKLIST", bl_value)
        await database.update_user_data(id_)
        msg = f"""<b>🚫 Temporary Blacklist Applied</b>

<blockquote>• <b>User ID:</b> <code>{id_}</code>
• <b>Restriction Type:</b> Temporary
• <b>Duration:</b> {remaining}</blockquote>"""
    else:
        update_user_ldata(id_, "BLACKLIST", True)
        await database.update_user_data(id_)
        msg = f"""<b>🚫 Permanent Blacklist Applied</b>

<blockquote>• <b>User ID:</b> <code>{id_}</code>
• <b>Restriction Type:</b> Permanent
• <b>Status:</b> Restricted from using bot commands</blockquote>"""

    await send_message(message, msg)


@new_task
async def remove_blacklist(_, message):
    msg = message.text.split()
    id_ = None

    if len(msg) > 1:
        try:
            id_ = int(msg[1].strip())
        except ValueError:
            pass
    if id_ is None and message.reply_to_message:
        id_ = (
            message.reply_to_message.from_user or message.reply_to_message.sender_chat
        ).id

    if id_ is None:
        return await send_message(
            message,
            "<blockquote>Provide user ID or reply to user message to remove from blacklist.</blockquote>",
        )

    bl_value = user_data.get(id_, {}).get("BLACKLIST")
    is_bl, remaining = _get_blacklist_info(bl_value)
    if not is_bl:
        return await send_message(
            message, f"<blockquote><b>User is not blacklisted!</b> ID: <code>{id_}</code></blockquote>"
        )

    update_user_ldata(id_, "BLACKLIST", False)
    await database.update_user_data(id_)
    await send_message(
        message,
        f"""<b>✅ Blacklist Removed</b>

<blockquote>• <b>User ID:</b> <code>{id_}</code>
• <b>Status:</b> User restriction cleared!</blockquote>""",
    )


@new_task
async def black_listed(_, message):
    await send_message(
        message, "<blockquote><b>Blacklisted User Detected:</b> You are restricted from using this bot.</blockquote>"
    )
