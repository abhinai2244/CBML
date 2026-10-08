from .. import (
    task_dict,
    task_dict_lock,
    user_data,
    queued_up,
    queued_dl,
    queue_dict_lock,
)
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.status_utils import get_task_by_gid
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.message_utils import send_message
from ..helper.ext_utils.task_manager import start_dl_from_queued, start_up_from_queued


@new_task
async def remove_from_queue(_, message):
    user_id = (message.from_user or message.sender_chat).id
    msg = message.text.split()
    status = msg[1] if len(msg) > 1 and msg[1] in ["fd", "fu"] else ""
    if status and len(msg) > 2 or not status and len(msg) > 1:
        gid = msg[2] if status else msg[1]
        task = await get_task_by_gid(gid)
        if task is None:
            await send_message(message, f"<blockquote>Task GID <code>{gid}</code> not found!</blockquote>")
            return
    elif reply_to_id := message.reply_to_message_id:
        async with task_dict_lock:
            task = task_dict.get(reply_to_id)
        if task is None:
            await send_message(message, "<blockquote>No active queued task found for replied message!</blockquote>")
            return
    elif len(msg) in {1, 2}:
        msg = f"""<b>⚡ Force Start Task Usage</b>

<blockquote>Reply to a queued task command message or pass GID:
• <code>/{BotCommands.ForceStartCommand[0]} GID</code> (Force download & upload)
• <code>/{BotCommands.ForceStartCommand[0]} GID fd</code> (Force download only)
• <code>/{BotCommands.ForceStartCommand[0]} GID fu</code> (Force upload only)</blockquote>"""
        await send_message(message, msg)
        return
    if (
        Config.OWNER_ID != user_id
        and task.listener.user_id != user_id
        and (user_id not in user_data or not user_data[user_id].get("SUDO"))
    ):
        await send_message(message, "<blockquote>You do not have permission to force start this task!</blockquote>")
        return
    listener = task.listener
    msg = ""
    async with queue_dict_lock:
        if status == "fu":
            listener.force_upload = True
            if listener.mid in queued_up:
                await start_up_from_queued(listener.mid)
                msg = "<b>Task force started for upload!</b>"
            else:
                msg = "<b>Force upload enabled for this task!</b>"
        elif status == "fd":
            listener.force_download = True
            if listener.mid in queued_dl:
                await start_dl_from_queued(listener.mid)
                msg = "<b>Task force started for download only!</b>"
            else:
                msg = "<b>This task is not in the download queue!</b>"
        else:
            listener.force_download = True
            listener.force_upload = True
            if listener.mid in queued_up:
                await start_up_from_queued(listener.mid)
                msg = "<b>Task force started for upload!</b>"
            elif listener.mid in queued_dl:
                await start_dl_from_queued(listener.mid)
                msg = "<b>Task force started for download & upload!</b>"
            else:
                msg = "<b>This task is not in queue!</b>"
    if msg:
        await send_message(message, msg)
