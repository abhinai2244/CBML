from asyncio import Event, Lock, gather
from time import time
from ... import LOGGER

active_tasks = {}
active_tasks_lock = Lock()


def get_task_key(source, user_id=None):
    if not source:
        return f"task_{time()}_{user_id}"
    cleaned = str(source).strip().split("?bytes=")[0].split("?")[0].strip()
    return f"{cleaned}_{user_id}" if user_id else cleaned


async def check_and_register_task(key, state="QUEUED"):
    async with active_tasks_lock:
        if key in active_tasks:
            curr_state = active_tasks[key].get("state", "UNKNOWN")
            if curr_state in ("QUEUED", "DOWNLOADING", "PROCESSING", "UPLOADING", "COMPLETED"):
                LOGGER.info(f"Duplicate task detected and skipped: {key} (Current State: {curr_state})")
                return False, f"Duplicate task detected and skipped! (State: {curr_state})"
        active_tasks[key] = {"state": state, "time": time()}
        return True, None


async def update_task_state(key, state):
    async with active_tasks_lock:
        if key in active_tasks:
            active_tasks[key]["state"] = state
            active_tasks[key]["time"] = time()
        else:
            active_tasks[key] = {"state": state, "time": time()}


async def clear_task_state(key):
    async with active_tasks_lock:
        active_tasks.pop(key, None)

from ... import (
    LOGGER,
    bot_cache,
    non_queued_dl,
    non_queued_up,
    queue_dict_lock,
    queued_dl,
    queued_up,
    task_dict,
    task_dict_lock,
    user_data,
)
from ...core.config_manager import Config
from ..mirror_leech_utils.gdrive_utils.search import GoogleDriveSearch
from ..telegram_helper.filters import CustomFilters
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.tg_utils import check_botpm, forcesub, verify_token
from .bot_utils import get_telegraph_list, sync_to_async, safe_int
from .files_utils import get_base_name, check_storage_threshold
from .links_utils import is_gdrive_id
from .status_utils import get_readable_time, get_readable_file_size, get_specific_tasks


async def stop_duplicate_check(listener):
    if (
        isinstance(listener.up_dest, int)
        or listener.is_leech
        or listener.select
        or not is_gdrive_id(listener.up_dest)
        or (listener.up_dest.startswith("mtp:") and listener.stop_duplicate)
        or not listener.stop_duplicate
        or listener.same_dir
    ):
        return False, None

    name = listener.name
    LOGGER.info(f"Checking File/Folder if already in Drive: {name}")

    if listener.compress:
        name = f"{name}.zip"
    elif listener.extract:
        try:
            name = get_base_name(name)
        except Exception:
            name = None

    if name is not None:
        telegraph_content, contents_no = await sync_to_async(
            GoogleDriveSearch(stop_dup=True, no_multi=listener.is_clone).drive_list,
            name,
            listener.up_dest,
            listener.user_id,
        )
        if telegraph_content:
            msg = f"File/Folder is already available in Drive.\nHere are {contents_no} list results:"
            button = await get_telegraph_list(telegraph_content)
            return msg, button

    return False, None


def _effective_all_task_limit():
    """Return the active global task cap; 0 means unlimited.

    BOT_MAX_TASKS and QUEUE_ALL are both global concurrency controls.  The
    smaller positive value wins so one setting cannot silently bypass the other.
    """
    limits = [
        value
        for value in (safe_int(Config.BOT_MAX_TASKS), safe_int(Config.QUEUE_ALL))
        if value > 0
    ]
    return min(limits) if limits else 0


async def check_running_tasks(listener, state="dl"):
    all_limit = _effective_all_task_limit()
    state_limit = (
        safe_int(Config.QUEUE_DOWNLOAD)
        if state == "dl"
        else safe_int(Config.QUEUE_UPLOAD)
    )
    user_dict = user_data.get(listener.user_id, {})
    user_limit = safe_int(user_dict.get("maxtask", Config.USER_MAX_TASKS))

    event = None
    is_over_limit = False
    async with queue_dict_lock:
        if state == "up" and listener.mid in non_queued_dl:
            non_queued_dl.remove(listener.mid)

        if not listener.force_run and not (listener.force_upload and state == "up") and not (listener.force_download and state == "dl"):
            dl_count = len(non_queued_dl)
            up_count = len(non_queued_up)
            t_count = dl_count if state == "dl" else up_count

            if user_limit > 0:
                async with task_dict_lock:
                    user_running = sum(
                        1 for tk in task_dict.values()
                        if getattr(tk, "listener", None) and tk.listener.user_id == listener.user_id
                        and (tk.listener.mid in non_queued_dl or tk.listener.mid in non_queued_up)
                    )
                if user_running >= user_limit:
                    is_over_limit = True

            if not is_over_limit:
                is_over_limit = (
                    all_limit
                    and dl_count + up_count >= all_limit
                    and (not state_limit or t_count >= state_limit)
                ) or (state_limit and t_count >= state_limit)

            if is_over_limit:
                event = Event()
                if state == "dl":
                    queued_dl[listener.mid] = event
                else:
                    queued_up[listener.mid] = event

        if not is_over_limit:
            if state == "up":
                non_queued_up.add(listener.mid)
            else:
                non_queued_dl.add(listener.mid)

    return is_over_limit, event


async def start_dl_from_queued(mid: int):
    queued_dl[mid].set()
    del queued_dl[mid]
    non_queued_dl.add(mid)


async def start_up_from_queued(mid: int):
    queued_up[mid].set()
    del queued_up[mid]
    non_queued_up.add(mid)


async def _can_start_user_task(mid):
    async with task_dict_lock:
        task = task_dict.get(mid)
        if not task or not getattr(task, "listener", None):
            return True
        user_id = task.listener.user_id
        user_dict = user_data.get(user_id, {})
        user_limit = safe_int(user_dict.get("maxtask", Config.USER_MAX_TASKS))
        if user_limit <= 0:
            return True
        user_running = sum(
            1 for tk in task_dict.values()
            if getattr(tk, "listener", None) and tk.listener.user_id == user_id
            and (tk.listener.mid in non_queued_dl or tk.listener.mid in non_queued_up)
        )
        return user_running < user_limit


async def start_from_queued():
    if all_limit := _effective_all_task_limit():
        dl_limit = safe_int(Config.QUEUE_DOWNLOAD)
        up_limit = safe_int(Config.QUEUE_UPLOAD)
        async with queue_dict_lock:
            dl = len(non_queued_dl)
            up = len(non_queued_up)
            all_ = dl + up
            if all_ < all_limit:
                f_tasks = all_limit - all_
                if queued_up and (not up_limit or up < up_limit):
                    for mid in list(queued_up.keys()):
                        if await _can_start_user_task(mid):
                            await start_up_from_queued(mid)
                            f_tasks -= 1
                            up += 1
                            if f_tasks == 0 or (up_limit and up >= up_limit):
                                break
                if queued_dl and (not dl_limit or dl < dl_limit) and f_tasks != 0:
                    for mid in list(queued_dl.keys()):
                        if await _can_start_user_task(mid):
                            await start_dl_from_queued(mid)
                            f_tasks -= 1
                            dl += 1
                            if f_tasks == 0 or (dl_limit and dl >= dl_limit):
                                break
        return

    if up_limit := Config.QUEUE_UPLOAD:
        async with queue_dict_lock:
            up = len(non_queued_up)
            if queued_up and up < up_limit:
                for mid in list(queued_up.keys()):
                    if await _can_start_user_task(mid):
                        await start_up_from_queued(mid)
                        up += 1
                        if up >= up_limit:
                            break
    else:
        async with queue_dict_lock:
            if queued_up:
                for mid in list(queued_up.keys()):
                    if await _can_start_user_task(mid):
                        await start_up_from_queued(mid)

    if dl_limit := Config.QUEUE_DOWNLOAD:
        async with queue_dict_lock:
            dl = len(non_queued_dl)
            if queued_dl and dl < dl_limit:
                for mid in list(queued_dl.keys()):
                    if await _can_start_user_task(mid):
                        await start_dl_from_queued(mid)
                        dl += 1
                        if dl >= dl_limit:
                            break
    else:
        async with queue_dict_lock:
            if queued_dl:
                for mid in list(queued_dl.keys()):
                    if await _can_start_user_task(mid):
                        await start_dl_from_queued(mid)


async def limit_checker(listener, yt_playlist=0):
    LOGGER.info("Checking Size Limit...")
    if await CustomFilters.sudo("", listener.message):
        LOGGER.info("SUDO User. Skipping Size Limit...")
        return

    size = listener.size

    async def recurr_limits(limits):
        nonlocal yt_playlist, size
        limit_exceeded = ""
        for condition, attr, name in limits:
            if condition and (limit := getattr(Config, attr, 0)):
                if attr == "PLAYLIST_LIMIT":
                    if yt_playlist >= limit:
                        limit_exceeded = f"┠ <b>{name} Limit Count</b> → {limit}"
                else:
                    byte_limit = limit * 1024**3
                    if size >= byte_limit:
                        limit_exceeded = f"┠ <b>{name} Limit</b> → {get_readable_file_size(byte_limit)}"

                LOGGER.info(
                    f"{name} Limit Breached: {listener.name} & Size: {get_readable_file_size(size)}"
                )
                break
        return limit_exceeded

    limits = [
        (listener.is_torrent or listener.is_qbit, "TORRENT_LIMIT", "Torrent"),
        (listener.is_mega, "MEGA_LIMIT", "Mega"),
        (listener.is_gdrive, "GD_DL_LIMIT", "GDriveDL"),
        (listener.is_clone, "CLONE_LIMIT", "Clone"),
        (listener.is_jd, "JD_LIMIT", "JDownloader"),
        (listener.is_nzb, "NZB_LIMIT", "SABnzbd"),
        (listener.is_seedr, "SEEDR_LIMIT", "Seedr"),
        (listener.is_rclone, "RC_DL_LIMIT", "RCloneDL"),
        (listener.is_ytdlp, "YTDLP_LIMIT", "YT-DLP"),
        (bool(yt_playlist), "PLAYLIST_LIMIT", "Playlist"),
        (True, "DIRECT_LIMIT", "Direct"),
    ]
    limit_exceeded = await recurr_limits(limits)

    if not limit_exceeded:
        extra_limits = [
            (listener.is_leech, "LEECH_LIMIT", "Leech"),
            (listener.compress, "ARCHIVE_LIMIT", "Archive"),
            (listener.extract, "EXTRACT_LIMIT", "Extract"),
        ]
        limit_exceeded = await recurr_limits(extra_limits)

        if Config.STORAGE_LIMIT and not listener.is_clone:
            limit = Config.STORAGE_LIMIT * 1024**3
            if not await check_storage_threshold(
                size, limit, any([listener.compress, listener.extract])
            ):
                limit_exceeded = f"┠ <b>Threshold Storage Limit</b> → {get_readable_file_size(limit)}"

    if limit_exceeded:
        return limit_exceeded + f"\n┖ <b>Task By</b> → {listener.tag}"


"""
class UsageChecks: # TODO: Dynamic Check for All Task

class DailyUsageChecks:
"""


async def user_interval_check(user_id):
    bot_cache.setdefault("time_interval", {})
    if (time_interval := bot_cache["time_interval"].get(user_id, False)) and (
        time() - time_interval
    ) < (UTI := Config.USER_TIME_INTERVAL):
        return UTI - (time() - time_interval)
    bot_cache["time_interval"][user_id] = time()
    return None


async def pre_task_check(message):
    LOGGER.info("Running Pre Task Checks ...")
    msg = []
    button = None
    user_id = (message.from_user or message.sender_chat).id
    user_dict = user_data.get(user_id, {})

    def _format_result():
        username = message.from_user.mention
        parts = [f"⌬ <b>Task Checks :</b>\n│\n┟ <b>Name</b> → {username}\n┃\n"]
        for i, m_part in enumerate(msg, 1):
            parts.append(m_part)
        menu = button.build_menu(2) if button is not None else None
        return "\n".join(parts), menu

    if await CustomFilters.sudo("", message):
        if message.chat.type != message.chat.type.BOT:
            _msg, button = await check_botpm(message, ButtonMaker())
            if _msg:
                msg.append(_msg)
        if msg:
            return _format_result()
        return None, None

    if Config.RSS_CHAT and user_id == int(Config.RSS_CHAT):
        return None, None

    button = ButtonMaker()
    checks = []
    if message.chat.type != message.chat.type.BOT:
        if Config.FORCE_SUB_IDS:
            checks.append(forcesub(message, Config.FORCE_SUB_IDS, button))
        checks.append(check_botpm(message, button))
    checks.append(verify_token(user_id, button))

    results = await gather(*checks)
    for _msg, _ in results:
        if _msg:
            msg.append(_msg)

    if (uti := Config.USER_TIME_INTERVAL) and (
        ut := await user_interval_check(user_id)
    ):
        msg.append(
            f"┠ <b>Waiting Time</b> → {get_readable_time(ut)}\n┠ <i>User's Time Interval Restrictions</i> → {get_readable_time(uti)}"
        )

    # Do not hard-block a command because the global task cap is reached.
    # check_running_tasks() will place the task in the normal download/upload
    # queue and start it automatically when a slot is released.

    if msg:
        return _format_result()
    return None, None
