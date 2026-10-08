from asyncio import sleep
from time import time
from secrets import token_hex

from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked

from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.status_utils import get_readable_time
from ..helper.telegram_helper.message_utils import (
    edit_message,
    send_message,
)

bc_cache = {}


async def delete_broadcast(bc_id, message):
    if bc_id not in bc_cache:
        return await send_message(message, "Invalid or expired Broadcast ID!")

    temp_wait = await send_message(
        message, "<b>Deleting broadcasted messages... Please wait.</b>"
    )
    total, success, failed = 0, 0, 0
    msgs = bc_cache.get(bc_id, [])
    for uid, msg_id in msgs:
        try:
            await (await TgClient.bot.get_messages(uid, msg_id)).delete()
            success += 1
        except FloodWait as e:
            await sleep(e.value)
            await (await TgClient.bot.get_messages(uid, msg_id)).delete()
            success += 1
        except Exception as e:
            print(f"Error deleting message for user {uid}: {e}")
            failed += 1
        total += 1
    return await edit_message(
        temp_wait,
        f"""<b>🗑️ Broadcast Message Deletion Stats</b>

<blockquote>• <b>Total Targets:</b> {total}
• <b>Successfully Deleted:</b> {success}
• <b>Failed Attempts:</b> {failed}
• <b>Broadcast ID:</b> <code>{bc_id}</code></blockquote>""",
    )


async def edit_broadcast(bc_id, message, rply):
    if bc_id not in bc_cache:
        return await send_message(message, "Invalid or expired Broadcast ID!")

    temp_wait = await send_message(
        message, "<b>Editing broadcasted messages... Please wait.</b>"
    )
    total, success, failed = 0, 0, 0
    for uid, msg_id in bc_cache[bc_id]:
        msg = await TgClient.bot.get_messages(uid, msg_id)
        if hasattr(msg, "forward_from") and msg.forward_from:
            return await edit_message(
                temp_wait,
                "<blockquote>Forwarded messages cannot be edited. They can only be deleted!</blockquote>",
            )
        try:
            await msg.edit(
                text=rply.text,
                entities=rply.entities,
                reply_markup=rply.reply_markup,
            )
            await sleep(0.3)
            success += 1
        except FloodWait as e:
            await sleep(e.value)
            await msg.edit(
                text=rply.text,
                entities=rply.entities,
                reply_markup=rply.reply_markup,
            )
            success += 1
        except Exception as e:
            print(f"Error editing message for user {uid}: {e}")
            failed += 1
        total += 1
    return await edit_message(
        temp_wait,
        f"""<b>✏️ Broadcast Message Edit Stats</b>

<blockquote>• <b>Total Targets:</b> {total}
• <b>Successfully Edited:</b> {success}
• <b>Failed Attempts:</b> {failed}
• <b>Broadcast ID:</b> <code>{bc_id}</code></blockquote>""",
    )


@new_task
async def broadcast(_, message):
    bc_id, forwarded, quietly, deleted, edited = "", False, False, False, False
    if not Config.DATABASE_URL:
        return await send_message(
            message, "DATABASE_URL is required to fetch database users!"
        )
    rply = message.reply_to_message
    if len(message.command) > 1:
        if not message.command[1].startswith("-"):
            bc_id = (
                message.command[1] if bc_cache.get(message.command[1], False) else ""
            )
            if not bc_id:
                return await send_message(
                    message,
                    "<blockquote>Broadcast ID not found in cache. Cached broadcasts are lost after bot restart.</blockquote>",
                )
        for arg in message.command:
            if arg in ["-f", "-forward"] and rply:
                forwarded = True
            if arg in ["-q", "-quiet"] and rply:
                quietly = True
            elif arg in ["-d", "-delete"] and bc_id:
                deleted = True
            elif arg in ["-e", "-edit"] and bc_id and rply:
                edited = True
    if not bc_id and not rply:
        return await send_message(
            message,
            """<b>📢 Broadcast Usage Guide</b>

<blockquote><b>Commands & Flags:</b>
• <b>Forward with Tag:</b> <code>/broadcast -f</code> (Reply to message)
• <b>Quiet Delivery:</b> <code>/broadcast -q</code> (Reply to message)
• <b>Edit Broadcast:</b> <code>/broadcast broadcast_id -e</code> (Reply to updated message)
• <b>Delete Broadcast:</b> <code>/broadcast broadcast_id -d</code>

<b>Notes:</b>
• Broadcasts can be edited or deleted until the next bot restart.
• Forwarded messages cannot be edited, only deleted.</blockquote>""",
        )
    if deleted:
        return await delete_broadcast(bc_id, message)
    elif edited:
        return await edit_broadcast(bc_id, message, rply)

    # Broadcasting logic
    start_time = time()
    status_fmt = """<b>📢 Broadcast Progress Stats</b>

<blockquote>• <b>Total Users:</b> {t}
• <b>Successful:</b> {s}
• <b>Blocked Users:</b> {b}
• <b>Deleted Accounts:</b> {d}
• <b>Failed Attempts:</b> {u}</blockquote>"""
    updater = time()
    bc_hash, bc_msgs = token_hex(5), []
    pls_wait = await send_message(message, status_fmt.format(t=0, s=0, b=0, d=0, u=0))
    t, s, b, d, u = 0, 0, 0, 0, 0
    for uid in await database.get_pm_uids():
        try:
            bc_msg = (
                await rply.forward(uid, disable_notification=quietly)
                if forwarded
                else await rply.copy(uid, disable_notification=quietly)
            )
            s += 1
        except FloodWait as e:
            await sleep(e.value * 1.1)
            bc_msg = (
                await rply.forward(uid, disable_notification=quietly)
                if forwarded
                else await rply.copy(uid, disable_notification=quietly)
            )
            s += 1
        except UserIsBlocked:
            await database.rm_pm_user(uid)
            b += 1
        except InputUserDeactivated:
            await database.rm_pm_user(uid)
            d += 1
        except Exception as e:
            print(f"Error broadcasting message to user {uid}: {e}")
            u += 1
        if bc_msg:
            bc_msgs.append((uid, bc_msg.id))
        t += 1
        if (time() - updater) > 10:
            await edit_message(pls_wait, status_fmt.format(t=t, s=s, b=b, d=d, u=u))
            updater = time()
    bc_cache[bc_hash] = bc_msgs
    await edit_message(
        pls_wait,
        f"""<b>📢 Broadcast Completed</b>

<blockquote>• <b>Total Users:</b> {t}
• <b>Successful:</b> {s}
• <b>Blocked Users:</b> {b}
• <b>Deleted Accounts:</b> {d}
• <b>Failed Attempts:</b> {u}
• <b>Elapsed Time:</b> {get_readable_time(time() - start_time)}
• <b>Broadcast ID:</b> <code>{bc_hash}</code></blockquote>""",
    )
