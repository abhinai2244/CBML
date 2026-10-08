from asyncio import gather, iscoroutinefunction
from html import escape
from pyrogram.enums import ButtonStyle
from re import findall
from time import time

from psutil import cpu_percent, disk_usage, virtual_memory

from ... import (
    DOWNLOAD_DIR,
    bot_cache,
    bot_start_time,
    status_dict,
    task_dict,
    task_dict_lock,
)
from ...core.config_manager import Config
from ..telegram_helper.button_build import ButtonMaker

SIZE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


class MirrorStatus:
    STATUS_UPLOAD = "Uploading"
    STATUS_DOWNLOAD = "Downloading"
    STATUS_CLONE = "Cloning"
    STATUS_QUEUEDL = "Queued DL"
    STATUS_QUEUEUP = "Queued UP"
    STATUS_PAUSED = "Paused"
    STATUS_ARCHIVE = "Archiving"
    STATUS_EXTRACT = "Extracting"
    STATUS_SPLIT = "Splitting"
    STATUS_CHECK = "Checking"
    STATUS_SEED = "Seeding"
    STATUS_SAMVID = "Sample Video"
    STATUS_CONVERT = "Converting"
    STATUS_MERGE = "Merging"
    STATUS_ENCODE = "Encoding"
    STATUS_COMPRESS = "Compressing"
    STATUS_WATERMARK = "Applying Watermark"
    STATUS_FFMPEG = "FFmpeg Processing"
    STATUS_YT = "YouTube Uploading"
    STATUS_METADATA = "Applying Metadata"
    STATUS_TRACKMGR = "Track Manager"
    STATUS_SEEDR = "Seedr Downloading"
    STATUS_COMPLETED = "Completed"


class EngineStatus:
    def __init__(self):
        ver = bot_cache.get("eng_versions", {})
        get_v = lambda k, d: ver.get(k) if ver.get(k) and ver.get(k) != "N/A" else d
        self.STATUS_ARIA2 = f"Aria2 v{get_v('aria2', '1.37.0')}"
        self.STATUS_AIOHTTP = f"AioHttp v{get_v('aiohttp', '3.14.3')}"
        self.STATUS_GDAPI = f"Google-API v{get_v('gapi', '2.201.0')}"
        self.STATUS_QBIT = f"qBit v{get_v('qBittorrent', '5.2.3')}"
        self.STATUS_TGRAM = f"wzgram v{get_v('wzgram', '3.1.3')}"
        self.STATUS_MEGA = f"MegaSDK v{get_v('mega', '10.20.20')}"
        self.STATUS_YTDLP = f"yt-dlp v{get_v('yt-dlp', '2026.08.19')}"
        self.STATUS_FFMPEG = f"ffmpeg v{get_v('ffmpeg', '9.0.2')}"
        self.STATUS_7Z = f"7z v{get_v('7z', '26.03')}"
        self.STATUS_RCLONE = f"RClone v{get_v('rclone', '1.75.1')}"
        self.STATUS_SABNZBD = f"SABnzbd+ v{get_v('SABnzbd+', '4.2.2')}"
        self.STATUS_QUEUE = "QSystem v2"
        self.STATUS_JD = "JDownloader v2"
        self.STATUS_YT = "Youtube-Api"
        self.STATUS_METADATA = "Metadata"
        self.STATUS_UPHOSTER = "Uphoster"
        self.STATUS_SEEDR = "Seedr"


STATUSES = {
    "ALL": "All",
    "DL": MirrorStatus.STATUS_DOWNLOAD,
    "UP": MirrorStatus.STATUS_UPLOAD,
    "QD": MirrorStatus.STATUS_QUEUEDL,
    "QU": MirrorStatus.STATUS_QUEUEUP,
    "AR": MirrorStatus.STATUS_ARCHIVE,
    "EX": MirrorStatus.STATUS_EXTRACT,
    "SD": MirrorStatus.STATUS_SEED,
    "CL": MirrorStatus.STATUS_CLONE,
    "CM": MirrorStatus.STATUS_CONVERT,
    "SP": MirrorStatus.STATUS_SPLIT,
    "SV": MirrorStatus.STATUS_SAMVID,
    "MG": MirrorStatus.STATUS_MERGE,
    "FF": MirrorStatus.STATUS_FFMPEG,
    "PA": MirrorStatus.STATUS_PAUSED,
    "CK": MirrorStatus.STATUS_CHECK,
}


async def get_task_by_gid(gid: str):
    async with task_dict_lock:
        for tk in task_dict.values():
            if hasattr(tk, "seeding"):
                await tk.update()
            if tk.gid() == gid or tk.gid().startswith(gid):
                return tk
        return None


async def get_specific_tasks(status, user_id):
    if status == "All":
        if user_id:
            return [tk for tk in task_dict.values() if tk.listener.user_id == user_id]
        else:
            return list(task_dict.values())
    tasks_to_check = (
        [tk for tk in task_dict.values() if tk.listener.user_id == user_id]
        if user_id
        else list(task_dict.values())
    )
    coro_tasks = []
    coro_tasks.extend(tk for tk in tasks_to_check if iscoroutinefunction(tk.status))
    coro_statuses = await gather(*[tk.status() for tk in coro_tasks])
    result = []
    coro_index = 0
    for tk in tasks_to_check:
        if tk in coro_tasks:
            st = coro_statuses[coro_index]
            coro_index += 1
        else:
            st = tk.status()
        if (st == status) or (
            status == MirrorStatus.STATUS_DOWNLOAD and st not in STATUSES.values()
        ):
            result.append(tk)
    return result


async def get_all_tasks(req_status: str, user_id):
    async with task_dict_lock:
        return await get_specific_tasks(req_status, user_id)


def get_raw_file_size(size):
    num, unit = size.split()
    return int(float(num) * (1024 ** SIZE_UNITS.index(unit)))


def get_readable_file_size(size_in_bytes):
    if not size_in_bytes:
        return "0B"
    if size_in_bytes < 0:
        return "Unknown"

    index = 0
    while size_in_bytes >= 1024 and index < len(SIZE_UNITS) - 1:
        size_in_bytes /= 1024
        index += 1

    return f"{size_in_bytes:.2f}{SIZE_UNITS[index]}"


def get_readable_time(seconds: int):
    periods = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
    result = ""
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f"{int(period_value)}{period_name}"
    return result or "0s"


def get_raw_time(time_str: str) -> int:
    time_units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(
        int(value) * time_units[unit]
        for value, unit in findall(r"(\d+)([dhms])", time_str)
    )


def time_to_seconds(time_duration):
    try:
        parts = time_duration.split(":")
        if len(parts) == 3:
            hours, minutes, seconds = map(float, parts)
        elif len(parts) == 2:
            hours = 0
            minutes, seconds = map(float, parts)
        elif len(parts) == 1:
            hours = 0
            minutes = 0
            seconds = float(parts[0])
        else:
            return 0
        return hours * 3600 + minutes * 60 + seconds
    except Exception:
        return 0


def speed_string_to_bytes(size_text: str):
    size = 0
    size_text = size_text.lower()
    if "k" in size_text:
        size += float(size_text.split("k")[0]) * 1024
    elif "m" in size_text:
        size += float(size_text.split("m")[0]) * 1048576
    elif "g" in size_text:
        size += float(size_text.split("g")[0]) * 1073741824
    elif "t" in size_text:
        size += float(size_text.split("t")[0]) * 1099511627776
    elif "b" in size_text:
        size += float(size_text.split("b")[0])
    return size


def bar_wave(pct, width=10):
    try:
        p = float(str(pct).strip("%"))
    except Exception:
        p = 0.0
    p = min(max(p, 0), 100)
    heights = "▁▂▃▄▅▆▇█"
    n = int(p / 100 * width)
    bar = "".join(heights[min(7, int((i+1)/width*8))] if i < n else "▁" for i in range(width))
    return f"┃{bar}┃ {p:.2f}%"


def get_progress_bar_string(pct):
    return bar_wave(pct)


async def get_readable_message(sid, is_user, page_no=1, status="All", page_step=1):
    msg = ""
    button = None

    tasks = await get_specific_tasks(status, sid if is_user else None)

    STATUS_LIMIT = Config.STATUS_LIMIT
    tasks_no = len(tasks)
    pages = (max(tasks_no, 1) + STATUS_LIMIT - 1) // STATUS_LIMIT
    if page_no > pages:
        page_no = (page_no - 1) % pages + 1
        status_dict[sid]["page_no"] = page_no
    elif page_no < 1:
        page_no = pages - (abs(page_no) % pages)
        status_dict[sid]["page_no"] = page_no
    start_position = (page_no - 1) * STATUS_LIMIT

    for index, task in enumerate(
        tasks[start_position : STATUS_LIMIT + start_position], start=1
    ):
        if status != "All":
            tstatus = status
        elif iscoroutinefunction(task.status):
            tstatus = await task.status()
        else:
            tstatus = task.status()

        msg += f"📦 <b>{index + start_position}. {escape(f'{task.name()}')}</b>\n"
        if task.listener.subname:
            msg += f"┖ <b>Sub Name:</b> {task.listener.subname}\n"
        elapsed = time() - task.listener.message.date.timestamp()

        msg += f"👤 <b>User:</b> {task.listener.message.from_user.mention(style='html')} (<code>#ID{task.listener.message.from_user.id}</code>)"
        if task.listener.is_super_chat:
            msg += f" [<a href='{task.listener.message.link}'>Link</a>]"
        msg += "\n"

        task_details = ""
        if (
            tstatus not in [MirrorStatus.STATUS_SEED, MirrorStatus.STATUS_QUEUEUP]
            and task.listener.progress
        ):
            progress = task.progress()
            task_details += f"┟ {get_progress_bar_string(progress)}\n"
            if task.listener.subname:
                subsize = f" / {get_readable_file_size(task.listener.subsize)}"
                ac = len(task.listener.files_to_proceed)
                count = f" ({task.listener.proceed_count} / {ac or '?'})"
            else:
                subsize = ""
                count = ""
            task_details += f"┠ <b>Processed:</b> {task.processed_bytes()}{subsize} of {task.size()}\n"
            if count:
                task_details += f"┠ <b>Count:</b> {count}\n"
            task_details += f"┠ <b>Status:</b> <b>{tstatus}</b>\n"
            task_details += f"┠ <b>Speed:</b> {task.speed()}\n"
            task_details += f"┠ <b>ETA:</b> {task.eta()} (Elapsed: {get_readable_time(elapsed)})\n"
            if tstatus == MirrorStatus.STATUS_DOWNLOAD and (
                task.listener.is_torrent or task.listener.is_qbit
            ):
                try:
                    task_details += f"┠ <b>Seeders:</b> {task.seeders_num()} | <b>Leechers:</b> {task.leechers_num()}\n"
                except Exception:
                    pass
        elif tstatus == MirrorStatus.STATUS_SEED:
            task_details += f"┠ <b>Size:</b> {task.size()} | <b>Uploaded:</b> {task.uploaded_bytes()}\n"
            task_details += f"┠ <b>Status:</b> <b>{tstatus}</b>\n"
            task_details += f"┠ <b>Speed:</b> {task.seed_speed()}\n"
            task_details += f"┠ <b>Ratio:</b> {task.ratio()}\n"
            task_details += f"┠ <b>Time:</b> {task.seeding_time()} | <b>Elapsed:</b> {get_readable_time(elapsed)}\n"
        else:
            task_details += f"┠ <b>Size:</b> {task.size()}\n"

        task_details += f"┠ <b>Engine:</b> {task.engine}\n"
        task_details += f"┠ <b>Mode:</b> {task.listener.mode[0]} ➔ {task.listener.mode[1]}\n"

        from ..telegram_helper.bot_commands import BotCommands

        if tstatus in [
            MirrorStatus.STATUS_DOWNLOAD,
            MirrorStatus.STATUS_PAUSED,
            MirrorStatus.STATUS_QUEUEDL,
        ]:
            if (
                task.listener.is_torrent
                or task.listener.is_qbit
                or task.listener.is_nzb
            ):
                task_details += f"┠ <b>Select:</b> /{BotCommands.SelectCommand[1]}_{task.gid()[:8]}\n"

        task_details += f"┖ <b>Cancel:</b> /{BotCommands.CancelTaskCommand[1]}_{task.gid()[:8]}"
        msg += f"<blockquote>{task_details}</blockquote>\n\n"

    if len(msg) == 0:
        if status == "All":
            return None, None
        else:
            msg = f"<blockquote><b>No active {status} tasks right now!</b></blockquote>\n\n"

    msg += "<b>📊 Bot Status Summary</b>\n"
    buttons = ButtonMaker()
    if not is_user:
        buttons.data_button(
            "📜 TStats",
            f"status {sid} ov",
            position="header",
            style=ButtonStyle.PRIMARY,
        )
    if len(tasks) > STATUS_LIMIT:
        msg += f"<b>Page:</b> {page_no}/{pages} | <b>Tasks:</b> {tasks_no} | <b>Step:</b> {page_step}\n"
        buttons.data_button("<<", f"status {sid} pre", position="header")
        buttons.data_button(">>", f"status {sid} nex", position="header")
        if tasks_no > 30:
            for i in [1, 2, 4, 6, 8, 10, 15]:
                buttons.data_button(i, f"status {sid} ps {i}", position="footer")
    if status != "All" or tasks_no > 20:
        for label, status_value in list(STATUSES.items()):
            if status_value != status:
                buttons.data_button(label, f"status {sid} st {status_value}")
    buttons.data_button(
        "♻️ Refresh", f"status {sid} ref", position="header", style=ButtonStyle.PRIMARY
    )
    button = buttons.build_menu(8)
    msg += f"<blockquote>⚡ <b>CPU:</b> {cpu_percent()}% | 💾 <b>Free Disk:</b> {get_readable_file_size(disk_usage(DOWNLOAD_DIR).free)} [{round(100 - disk_usage(DOWNLOAD_DIR).percent, 1)}%]\n🧠 <b>RAM:</b> {virtual_memory().percent}% | ⏱️ <b>Uptime:</b> {get_readable_time(time() - bot_start_time)}</blockquote>"
    return msg, button
