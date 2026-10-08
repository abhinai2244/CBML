from aiofiles.os import remove, path as aiopath
from asyncio import iscoroutinefunction

from .. import (
    task_dict,
    task_dict_lock,
    user_data,
    LOGGER,
    sabnzbd_client,
)
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..core.torrent_manager import TorrentManager
from ..helper.ext_utils.bot_utils import (
    bt_selection_buttons,
    new_task,
)
from ..helper.ext_utils.status_utils import get_task_by_gid, MirrorStatus
from ..helper.ext_utils.task_manager import limit_checker
from ..helper.telegram_helper.message_utils import (
    send_message,
    send_status_message,
    delete_message,
)


@new_task
async def select(_, message):
    if not Config.BASE_URL:
        await send_message(message, "<blockquote>BASE_URL is not configured! Selection web app requires BASE_URL.</blockquote>")
        return
    user_id = message.from_user.id
    text = message.text
    if " " in text.split("\n")[0]:
        text = text.replace(" ", "_", 1)
    msg = text.split("_", maxsplit=1)
    gid = None
    task = None
    if len(msg) > 1:
        cmd_data = msg[1].split("@", maxsplit=1)
        if len(cmd_data) > 1 and cmd_data[1].strip() != TgClient.BNAME:
            return
        gid = cmd_data[0].split()[0]
        if gid:
            task = await get_task_by_gid(gid)
            if task is None:
                await send_message(message, f"<blockquote>Task GID <code>{gid}</code> not found!</blockquote>")
                return
    if task is None and (reply_to_id := message.reply_to_message_id):
        async with task_dict_lock:
            task = task_dict.get(reply_to_id)
        if task is None:
            await send_message(message, "<blockquote>No active task found for replied message!</blockquote>")
            return
    if task is None:
        msg = (
            "<b>🎯 File Selection Usage</b>\n\n"
            "<blockquote>Reply to an active task message or pass task GID:\n"
            "<code>/select GID</code></blockquote>"
        )
        await send_message(message, msg)
        return
    if (
        Config.OWNER_ID != user_id
        and task.listener.user_id != user_id
        and (user_id not in user_data or not user_data[user_id].get("SUDO"))
    ):
        await send_message(message, "<blockquote>You do not have permission to modify files for this task!</blockquote>")
        return
    if not iscoroutinefunction(task.status):
        await send_message(message, "<blockquote>The task has completed its download phase.</blockquote>")
        return
    if await task.status() not in [
        MirrorStatus.STATUS_DOWNLOAD,
        MirrorStatus.STATUS_PAUSED,
        MirrorStatus.STATUS_QUEUEDL,
    ]:
        await send_message(
            message,
            "<blockquote>Task must be downloading, paused, or queued to open file selector.</blockquote>",
        )
        return
    if task.name().startswith("[METADATA]") or task.name().startswith("Trying"):
        await send_message(message, "<blockquote>Please wait until torrent metadata download finishes.</blockquote>")
        return

    try:
        await task.update()
        id_ = task.hash() if task.listener.is_qbit else task.gid()
        if not task.queued:
            if task.listener.is_nzb:
                await sabnzbd_client.pause_job(id_)
            elif task.listener.is_qbit:
                await TorrentManager.qbittorrent.torrents.stop([id_])
            else:
                try:
                    await TorrentManager.aria2.forcePause(id_)
                except Exception as e:
                    LOGGER.error(
                        f"{e} Error in pause, this mostly happens after abuse aria2"
                    )
        task.listener.select = True
    except Exception:
        await send_message(message, "<blockquote>This is not a BitTorrent or SABnzbd task.</blockquote>")
        return

    SBUTTONS = bt_selection_buttons(id_, message)
    msg = "<b>⏸️ Download Paused for File Selection</b>\n\n<blockquote>Select files in the web interface and click <b>Done Selecting</b> to resume download.</blockquote>"
    await send_message(message, msg, SBUTTONS)


async def _selection_limit_exceeded(task, message):
    mmsg = await limit_checker(task.listener)
    if not mmsg:
        return False
    await send_message(message, mmsg)
    await task.cancel_task()
    await delete_message(message)
    return True


@new_task
async def confirm_selection(_, query):
    user_id = query.from_user.id
    data = query.data.split()
    message = query.message
    task = await get_task_by_gid(data[2])
    if task is None:
        await query.answer("This task has been cancelled!", show_alert=True)
        await delete_message(message)
        return
    if user_id != task.listener.user_id:
        await query.answer("This task is not for you!", show_alert=True)
    elif data[1] == "pin":
        await query.answer(data[3], show_alert=True)
    elif data[1] == "done":
        await query.answer()
        id_ = data[3]
        task.listener.files_selected = True
        if hasattr(task, "seeding"):
            if task.listener.is_qbit:
                tor_info = (
                    await TorrentManager.qbittorrent.torrents.info(hashes=[id_])
                )[0]
                path = tor_info.content_path.rsplit("/", 1)[0]
                res = await TorrentManager.qbittorrent.torrents.files(id_)
                for f in res:
                    if f.priority == 0:
                        f_paths = [f"{path}/{f.name}", f"{path}/{f.name}.!qB"]
                        for f_path in f_paths:
                            if await aiopath.exists(f_path):
                                try:
                                    await remove(f_path)
                                except Exception:
                                    pass
                tor_info = (
                    await TorrentManager.qbittorrent.torrents.info(hashes=[id_])
                )[0]
                task.listener.size = tor_info.size
                if await _selection_limit_exceeded(task, message):
                    return
                if not task.queued:
                    await TorrentManager.qbittorrent.torrents.start([id_])
            else:
                res = await TorrentManager.aria2.getFiles(id_)
                for f in res:
                    if f["selected"] == "false" and await aiopath.exists(f["path"]):
                        try:
                            await remove(f["path"])
                        except Exception:
                            pass
                task.listener.size = sum(
                    int(f["length"]) for f in res if f["selected"] == "true"
                )
                if await _selection_limit_exceeded(task, message):
                    return
                if not task.queued:
                    try:
                        await TorrentManager.aria2.unpause(id_)
                    except Exception as e:
                        LOGGER.error(
                            f"{e} Error in resume, this mostly happens after abuse aria2."
                        )
        elif task.listener.is_nzb:
            if not task.queued:
                await sabnzbd_client.resume_job(id_)
        await send_status_message(message)
        await delete_message(message)
    else:
        await delete_message(message)
        await task.cancel_task()
