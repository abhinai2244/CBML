from asyncio import sleep
from pyrogram.enums import ButtonStyle

from .. import task_dict, task_dict_lock, user_data, multi_tags
from ..core.tg_client import Config
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.status_utils import (
    get_task_by_gid,
    get_all_tasks,
    MirrorStatus,
)
from ..core.tg_client import TgClient
from ..helper.telegram_helper import button_build
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.telegram_helper.message_utils import (
    send_message,
    auto_delete_message,
    delete_message,
    edit_message,
)


@new_task
async def cancel(_, message):
    user_id = (message.from_user or message.sender_chat).id
    msg = message.text.split("_", maxsplit=1)
    if len(msg) > 1:
        cmd_data = msg[1].split("@", maxsplit=1)
        if len(cmd_data) > 1 and cmd_data[1].strip() != TgClient.BNAME:
            return
        gid = cmd_data[0]
        if len(gid) == 6:
            multi_tags.discard(gid)
            return
        else:
            task = await get_task_by_gid(gid)
            if task is None:
                await send_message(message, f"<blockquote>Task GID <code>{gid}</code> not found!</blockquote>")
                return
    elif reply_to_id := message.reply_to_message_id:
        async with task_dict_lock:
            task = task_dict.get(reply_to_id)
        if task is None:
            await send_message(message, "<blockquote>No active task found for replied message!</blockquote>")
            return
    elif len(msg) == 1:
        msg = (
            "<b>🚫 Cancel Task Usage</b>\n\n"
            "<blockquote>Reply to the task message or pass task GID:\n"
            f"<code>/{BotCommands.CancelTaskCommand[0]} GID</code></blockquote>"
        )
        await send_message(message, msg)
        return
    if (
        Config.OWNER_ID != user_id
        and task.listener.user_id != user_id
        and (user_id not in user_data or not user_data[user_id].get("SUDO"))
    ):
        await send_message(message, "<blockquote>You do not have permission to cancel this task!</blockquote>")
        return
    obj = task.task()
    await obj.cancel_task()


@new_task
async def cancel_multi(_, query):
    data = query.data.split()
    if len(data) < 3:
        return await query.answer("Invalid request!", show_alert=True)
    user_id = query.from_user.id
    if user_id != int(data[1]) and not await CustomFilters.sudo("", query):
        await query.answer("This menu is not for you!", show_alert=True)
        return
    tag = int(data[2])
    if tag in multi_tags:
        multi_tags.discard(int(data[2]))
        msg = "Multi-link task stopped!"
    else:
        msg = "Already stopped or completed!"
    await query.answer(msg, show_alert=True)
    await delete_message(query.message, query.message.reply_to_message)


async def cancel_all(status, user_id):
    matches = await get_all_tasks(status.strip(), user_id)
    if not matches:
        return False
    for task in matches:
        obj = task.task()
        await obj.cancel_task()
        await sleep(2)
    return True


def create_cancel_buttons(is_sudo, user_id=""):
    buttons = button_build.ButtonMaker()
    buttons.data_button(
        "Downloading", f"canall ms {MirrorStatus.STATUS_DOWNLOAD} {user_id}"
    )
    buttons.data_button(
        "Uploading", f"canall ms {MirrorStatus.STATUS_UPLOAD} {user_id}"
    )
    buttons.data_button("Seeding", f"canall ms {MirrorStatus.STATUS_SEED} {user_id}")
    buttons.data_button("Splitting", f"canall ms {MirrorStatus.STATUS_SPLIT} {user_id}")
    buttons.data_button("Cloning", f"canall ms {MirrorStatus.STATUS_CLONE} {user_id}")
    buttons.data_button(
        "Extracting", f"canall ms {MirrorStatus.STATUS_EXTRACT} {user_id}"
    )
    buttons.data_button(
        "Archiving", f"canall ms {MirrorStatus.STATUS_ARCHIVE} {user_id}"
    )
    buttons.data_button(
        "QueuedDl", f"canall ms {MirrorStatus.STATUS_QUEUEDL} {user_id}"
    )
    buttons.data_button(
        "QueuedUp", f"canall ms {MirrorStatus.STATUS_QUEUEUP} {user_id}"
    )
    buttons.data_button(
        "SampleVideo", f"canall ms {MirrorStatus.STATUS_SAMVID} {user_id}"
    )
    buttons.data_button(
        "ConvertMedia", f"canall ms {MirrorStatus.STATUS_CONVERT} {user_id}"
    )
    buttons.data_button("FFmpeg", f"canall ms {MirrorStatus.STATUS_FFMPEG} {user_id}")
    buttons.data_button("Paused", f"canall ms {MirrorStatus.STATUS_PAUSED} {user_id}")
    buttons.data_button("All Tasks", f"canall ms All {user_id}")
    if is_sudo:
        if user_id:
            buttons.data_button("All Added Tasks", f"canall bot ms {user_id}")
        else:
            buttons.data_button("My Tasks Only", f"canall user ms {user_id}")
    buttons.data_button("Close", f"canall close ms {user_id}", style=ButtonStyle.DANGER)
    return buttons.build_menu(2)


@new_task
async def cancel_all_buttons(_, message):
    async with task_dict_lock:
        count = len(task_dict)
    if count == 0:
        await send_message(message, "<b>No active tasks to cancel!</b>")
        return
    is_sudo = await CustomFilters.sudo("", message)
    button = create_cancel_buttons(is_sudo, message.from_user.id)
    can_msg = await send_message(
        message, "<b>🛑 Bulk Task Cancel Menu</b>\n\n<blockquote>Select task category to cancel.</blockquote>", button
    )
    await auto_delete_message(message, can_msg)


@new_task
async def cancel_all_update(_, query):
    data = query.data.split()
    if len(data) < 2:
        return await query.answer("Invalid request!", show_alert=True)
    message = query.message
    reply_to = message.reply_to_message
    user_id = int(data[3]) if len(data) > 3 else ""
    is_sudo = await CustomFilters.sudo("", query)
    if not is_sudo and user_id and user_id != query.from_user.id:
        await query.answer("This menu is not for you!", show_alert=True)
        return
    await query.answer()
    if data[1] == "close":
        await delete_message(reply_to, message)
    elif data[1] == "back":
        button = create_cancel_buttons(is_sudo, user_id)
        await edit_message(message, "<b>🛑 Bulk Task Cancel Menu</b>\n\n<blockquote>Select task category to cancel.</blockquote>", button)
    elif data[1] == "bot":
        button = create_cancel_buttons(is_sudo, "")
        await edit_message(message, "<b>🛑 Bulk Task Cancel Menu</b>\n\n<blockquote>Select task category to cancel.</blockquote>", button)
    elif data[1] == "user":
        button = create_cancel_buttons(is_sudo, query.from_user.id)
        await edit_message(message, "<b>🛑 Bulk Task Cancel Menu</b>\n\n<blockquote>Select task category to cancel.</blockquote>", button)
    elif data[1] == "ms":
        buttons = button_build.ButtonMaker()
        buttons.data_button(
            "Yes, Cancel All", f"canall {data[2]} confirm {user_id}", style=ButtonStyle.SUCCESS
        )
        buttons.data_button("◀️ Back", f"canall back confirm {user_id}")
        buttons.data_button(
            "❌ Close", f"canall close confirm {user_id}", style=ButtonStyle.DANGER
        )
        button = buttons.build_menu(2)
        await edit_message(
            message, f"<b>⚠️ Confirm Cancellation</b>\n\n<blockquote>Are you sure you want to cancel all <b>{data[2]}</b> tasks?</blockquote>", button
        )
    else:
        button = create_cancel_buttons(is_sudo, user_id)
        await edit_message(message, "<b>🛑 Cancelling selected tasks... Please wait.</b>", button)
        res = await cancel_all(data[1], user_id)
        if not res:
            await send_message(reply_to, f"<b>No matching active tasks found for {data[1]}!</b>")


async def _cancel_single_range_task(rt):
    from bot import active_range_tasks, task_dict, task_dict_lock
    from contextlib import suppress
    from ..helper.ext_utils.range_utils import save_range_tasks_to_file

    rt["is_cancelled"] = True
    range_id = rt["range_id"]
    active_range_tasks.pop(range_id, None)
    await save_range_tasks_to_file()

    if sub := rt.get("current_sub_task"):
        sub.is_cancelled = True
        async with task_dict_lock:
            task_status = task_dict.get(sub.mid)
        if task_status:
            with suppress(Exception):
                await task_status.cancel_task()


@new_task
async def cancel_range_link(_, message):
    from bot import active_range_tasks
    user_id = (message.from_user or message.sender_chat).id
    is_sudo = await CustomFilters.sudo("", message)

    if is_sudo:
        user_tasks = list(active_range_tasks.values())
    else:
        user_tasks = [t for t in active_range_tasks.values() if t.get("user_id") == user_id]

    if not user_tasks:
        return await send_message(message, "<b>No active range link tasks found to cancel!</b>")

    target_id = None
    msg_args = message.text.split(maxsplit=1)
    if len(msg_args) > 1:
        target_id = msg_args[1].strip()
    elif "_" in message.text.split()[0]:
        target_id = message.text.split()[0].split("_", 1)[1].strip()

    if target_id:
        matching = [t for t in user_tasks if t["range_id"] == target_id or t["range_id"].endswith(target_id)]
        if matching:
            user_tasks = matching

    if len(user_tasks) == 1:
        rt = user_tasks[0]
        await _cancel_single_range_task(rt)
        return await send_message(
            message,
            f"<b>🛑 Range Link Task Cancelled</b>\n\n<blockquote>• <b>Range ID:</b> <code>{rt['range_id']}</code>\n• <b>Progress:</b> <code>{rt.get('current_idx', 1)}/{rt.get('total_links', 1)}</code> items</blockquote>"
        )

    buttons = button_build.ButtonMaker()
    for rt in user_tasks:
        buttons.data_button(
            f"Range {rt['range_id']} ({rt.get('current_idx', 1)}/{rt.get('total_links', 1)})",
            f"cancelrl {rt['range_id']}"
        )
    buttons.data_button("❌ Close", "cancelrl close", style=ButtonStyle.DANGER)

    prompt = (
        f"<b>🛑 Active Range Link Tasks ({len(user_tasks)})</b>\n\n"
        "<blockquote>Select a range link task below to cancel:</blockquote>"
    )
    can_msg = await send_message(message, prompt, buttons.build_menu(1))
    await auto_delete_message(message, can_msg)


@new_task
async def cancel_range_link_cb(_, query):
    from bot import active_range_tasks
    data = query.data.split()
    if len(data) < 2:
        return await query.answer("Invalid request!", show_alert=True)

    if data[1] == "close":
        await query.answer()
        return await delete_message(query.message)

    range_id = data[1]
    rt = active_range_tasks.get(range_id)

    if not rt:
        return await query.answer("Range link task already completed or not found!", show_alert=True)

    user_id = query.from_user.id
    is_sudo = await CustomFilters.sudo("", query)
    if not is_sudo and rt.get("user_id") != user_id:
        return await query.answer("This menu is not for you!", show_alert=True)

    await _cancel_single_range_task(rt)
    await query.answer("Range link task cancelled!", show_alert=True)
    await edit_message(
        query.message,
        f"<b>🛑 Range Link Task Cancelled</b>\n\n<blockquote>• <b>Range ID:</b> <code>{range_id}</code>\n• <b>Status:</b> Stopped by user.</blockquote>"
    )
