from psutil import cpu_percent, virtual_memory, disk_usage
from time import time
from asyncio import gather, iscoroutinefunction

from pyrogram.enums import ChatType
from pyrogram.errors import QueryIdInvalid
from .. import user_data

from .. import (
    task_dict_lock,
    status_dict,
    task_dict,
    bot_start_time,
    intervals,
    sabnzbd_client,
    DOWNLOAD_DIR,
)
from ..core.config_manager import Config
from ..core.torrent_manager import TorrentManager
from ..core.jdownloader_booter import jdownloader
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.status_utils import (
    EngineStatus,
    MirrorStatus,
    get_readable_file_size,
    get_readable_time,
    speed_string_to_bytes,
)
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.message_utils import (
    send_message,
    delete_message,
    auto_delete_message,
    send_status_message,
    update_status_message,
    edit_message,
)
from ..helper.telegram_helper.button_build import ButtonMaker


@new_task
async def task_status(_, message):
    async with task_dict_lock:
        count = len(task_dict)
    if count == 0:
        currentTime = get_readable_time(time() - bot_start_time)
        free = get_readable_file_size(disk_usage(DOWNLOAD_DIR).free)
        msg = (
            "<b>📊 Active Bot Status</b>\n\n"
            "<i>No active tasks running.</i>\n\n"
            "<b>🖥 System</b>\n"
            f"⚡ CPU: <b>{cpu_percent()}%</b>\n"
            f"💾 Free disk: <b>{free}</b> ({round(100 - disk_usage(DOWNLOAD_DIR).percent, 1)}%)\n"
            f"🧠 RAM: <b>{virtual_memory().percent}%</b>\n"
            f"⏱️ Uptime: <b>{currentTime}</b>\n\n"
            f"Use <code>/{BotCommands.StatusCommand[0]} me</code> for personal tasks or "
            f"<code>/{BotCommands.StatusCommand[0]} user_id</code> for a specific user."
        )
        reply_message = await send_message(message, msg)
        await auto_delete_message(message, reply_message)
    else:
        text = message.text.split()
        is_private = message.chat and message.chat.type == ChatType.PRIVATE
        u_id = message.from_user.id if message.from_user else 0

        if is_private:
            is_sudo = u_id == Config.OWNER_ID or (u_id in user_data and user_data[u_id].get("SUDO"))
            if len(text) > 1 and text[1].lstrip("-").isdigit() and is_sudo:
                target_user_id = int(text[1])
            else:
                target_user_id = u_id
        else:
            if len(text) > 1:
                if text[1] == "me":
                    target_user_id = u_id
                elif text[1].lstrip("-").isdigit():
                    target_user_id = int(text[1])
                else:
                    target_user_id = 0
            else:
                target_user_id = 0
                sid = message.chat.id
                if obj := intervals["status"].get(sid):
                    obj.cancel()
                    del intervals["status"][sid]

        await send_status_message(message, target_user_id, force_new=True)
        await delete_message(message)


async def get_download_status(download):
    eng = download.engine
    speed = (
        download.speed()
        if eng.startswith(("WzPyro", "yt-dlp", "RClone", "Google-API"))
        else 0
    )
    return (
        (
            await download.status()
            if iscoroutinefunction(download.status)
            else download.status()
        ),
        speed,
        eng,
    )


@new_task
async def status_pages(_, query):
    data = query.data.split()
    key = int(data[1])
    if data[2] == "ref":
        await update_status_message(key, force=True)
    elif data[2] in ["nex", "pre"]:
        async with task_dict_lock:
            if key in status_dict:
                if data[2] == "nex":
                    status_dict[key]["page_no"] += status_dict[key]["page_step"]
                else:
                    status_dict[key]["page_no"] -= status_dict[key]["page_step"]
    elif data[2] == "ps":
        async with task_dict_lock:
            if key in status_dict:
                status_dict[key]["page_step"] = int(data[3])
    elif data[2] == "st":
        async with task_dict_lock:
            if key in status_dict:
                status_dict[key]["status"] = data[3]
        await update_status_message(key, force=True)
    elif data[2] == "ov":
        message = query.message
        tasks = {
            "Download": 0,
            "Upload": 0,
            "Seed": 0,
            "Archive": 0,
            "Extract": 0,
            "Split": 0,
            "QueueDl": 0,
            "QueueUp": 0,
            "Clone": 0,
            "CheckUp": 0,
            "Pause": 0,
            "SamVid": 0,
            "ConvertMedia": 0,
            "FFmpeg": 0,
        }
        dl_speed = 0
        up_speed = 0
        seed_speed = 0

        async with task_dict_lock:
            status_results = await gather(
                *(get_download_status(download) for download in task_dict.values())
            )

        eng_status = EngineStatus()
        if any(
            eng in (eng_status.STATUS_ARIA2, eng_status.STATUS_QBIT)
            for _, __, eng in status_results
        ):
            dl_speed, seed_speed = await TorrentManager.overall_speed()

        if any(eng == eng_status.STATUS_SABNZBD for _, __, eng in status_results):
            if not Config.DISABLE_NZB and sabnzbd_client.LOGGED_IN:
                dl_speed += (
                    int(
                        float(
                            (await sabnzbd_client.get_downloads())["queue"].get(
                                "kbpersec", "0"
                            )
                        )
                    )
                    * 1024
                )

        if any(eng == eng_status.STATUS_JD for _, __, eng in status_results):
            if not Config.DISABLE_JD and jdownloader.is_connected:
                dl_speed += (
                    await jdownloader.device.downloadcontroller.get_speed_in_bytes()
                )

        for status, speed, _ in status_results:
            match status:
                case MirrorStatus.STATUS_DOWNLOAD:
                    tasks["Download"] += 1
                    if speed:
                        dl_speed += speed_string_to_bytes(speed)
                case MirrorStatus.STATUS_UPLOAD:
                    tasks["Upload"] += 1
                    up_speed += speed_string_to_bytes(speed)
                case MirrorStatus.STATUS_SEED:
                    tasks["Seed"] += 1
                case MirrorStatus.STATUS_ARCHIVE:
                    tasks["Archive"] += 1
                case MirrorStatus.STATUS_EXTRACT:
                    tasks["Extract"] += 1
                case MirrorStatus.STATUS_SPLIT:
                    tasks["Split"] += 1
                case MirrorStatus.STATUS_QUEUEDL:
                    tasks["QueueDl"] += 1
                case MirrorStatus.STATUS_QUEUEUP:
                    tasks["QueueUp"] += 1
                case MirrorStatus.STATUS_CLONE:
                    tasks["Clone"] += 1
                case MirrorStatus.STATUS_CHECK:
                    tasks["CheckUp"] += 1
                case MirrorStatus.STATUS_PAUSED:
                    tasks["Pause"] += 1
                case MirrorStatus.STATUS_SAMVID:
                    tasks["SamVid"] += 1
                case MirrorStatus.STATUS_CONVERT:
                    tasks["ConvertMedia"] += 1
                case MirrorStatus.STATUS_FFMPEG:
                    tasks["FFmpeg"] += 1
                case _:
                    tasks["Download"] += 1

        msg = (
            "<b>📊 System Tasks Overview</b>\n\n"
            "<b>Active work</b>\n"
            + "\n".join(f"• {k}: <b>{v}</b>" for k, v in tasks.items())
            + "\n\n"
            f"⚡ Download: <b>{get_readable_file_size(dl_speed)}/s</b>\n"
            f"⚡ Upload: <b>{get_readable_file_size(up_speed)}/s</b>\n"
            f"🌱 Seed: <b>{get_readable_file_size(seed_speed)}/s</b>"
        )
        button = ButtonMaker()
        button.data_button("◀️ Back", f"status {data[1]} ref")
        await edit_message(message, msg, button.build_menu())

    try:
        await query.answer()
    except QueryIdInvalid:
        pass
