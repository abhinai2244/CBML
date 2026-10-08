from asyncio import gather, sleep, wait_for, TimeoutError
from pyrogram.enums import ButtonStyle
from platform import platform, version
from re import search as research
from time import time

from aiofiles.os import path as aiopath
from psutil import (
    Process,
    boot_time,
    cpu_count,
    cpu_freq,
    cpu_percent,
    disk_io_counters,
    disk_usage,
    getloadavg,
    net_io_counters,
    swap_memory,
    virtual_memory,
    process_iter,
    NoSuchProcess,
    AccessDenied,
)

from .. import LOGGER, bot_cache, bot_start_time, bot_loop
from ..core.config_manager import Config, BinConfig
from ..helper.ext_utils.bot_lock import get_system_resources_cached
from ..helper.ext_utils.bot_utils import (
    cmd_exec,
    compare_versions,
    git_info,
    new_task,
)
from ..helper.ext_utils.status_utils import (
    get_progress_bar_string,
    get_readable_file_size,
    get_readable_time,
)
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)
from ..version import get_version

commands = {
    "aria2": ([BinConfig.ARIA2_NAME, "--version"], r"aria2 version ([\d.]+)"),
    "qBittorrent": ([BinConfig.QBIT_NAME, "--version"], r"qBittorrent v([\d.]+)"),
    "SABnzbd+": (
        [BinConfig.SABNZBD_NAME, "--version"],
        rf"{BinConfig.SABNZBD_NAME}-([\d.]+)",
    ),
    "python": (["python3", "--version"], r"Python ([\d.]+)"),
    "rclone": ([BinConfig.RCLONE_NAME, "--version"], r"rclone v([\d.]+)"),
    "yt-dlp": (["yt-dlp", "--version"], r"([\d.]+)"),
    "ffmpeg": (
        [BinConfig.FFMPEG_NAME, "-version"],
        r"ffmpeg version ([\d.]+(-\w+)?).*",
    ),
    "7z": (["7z", "i"], r"7-Zip ([\d.]+)"),
    "aiohttp": (
        [
            "python3",
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('aiohttp'))",
        ],
        r"([\d.]+)",
    ),
    "wzgram": (
        [
            "python3",
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('wzgram'))",
        ],
        r"([\d.]+)",
    ),
    "gapi": (
        [
            "python3",
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('google-api-python-client'))",
        ],
        r"([\d.]+)",
    ),
    "mega": (
        [
            "python3",
            "-c",
            "try:\n from mega import MegaApi\n v = MegaApi('test').getVersion()\n print(v if v else '10.20.20')\nexcept Exception:\n try:\n  from megasdk import MegaApi\n  v = MegaApi('test').getVersion()\n  print(v if v else '10.20.20')\n except Exception:\n  print('10.20.20')",
        ],
        r"v?([\d.]+)",
    ),
}


async def get_stats(event, key="home"):
    user_id = event.from_user.id
    btns = ButtonMaker()
    if key == "home":
        btns = ButtonMaker()
        btns.data_button("🤖 Bot Stats", f"stats {user_id} stbot")
        btns.data_button("💻 OS Stats", f"stats {user_id} stsys")
        btns.data_button("📦 Repo Stats", f"stats {user_id} strepo")
        btns.data_button("⚙️ Pkgs Stats", f"stats {user_id} stpkgs")
        btns.data_button("🛑 Task Limits", f"stats {user_id} tlimits")
        btns.data_button("⚡ Sys Tasks", f"stats {user_id} systasks")
        msg = "<b>📊 Bot & OS System Dashboard</b>\n\n<blockquote>Select an option below to view details.</blockquote>"
    elif key == "stbot":
        total, used, free, disk = disk_usage("/")
        swap = swap_memory()
        memory = virtual_memory()
        disk_io = disk_io_counters()
        res = get_system_resources_cached()
        bot_ram_mb = res["ram_mb"]
        bot_ram_total = bot_ram_mb * 1024 * 1024
        user = Process().username()
        bot_ram_used = sum(
            p.memory_info().rss for p in process_iter() if p.username() == user
        )
        bot_ram_free = max(0, bot_ram_total - bot_ram_used)
        bot_ram_pct = (
            round((bot_ram_used / bot_ram_total * 100), 2) if bot_ram_total > 0 else 0
        )
        instance_cpu = res["cpu_count"]
        sys_cpu = cpu_count(logical=True)
        p_cores = cpu_count(logical=False)
        v_cores = (sys_cpu or 0) - (p_cores or 0)
        msg = f"""<b>🤖 Bot Performance Statistics</b>

<blockquote>⏱️ <b>Uptime:</b> {get_readable_time(time() - bot_start_time)}

🧠 <b>Instance RAM Usage:</b>
{get_progress_bar_string(bot_ram_pct)} {bot_ram_pct}%
• <b>Used:</b> {get_readable_file_size(bot_ram_used)} | <b>Free:</b> {get_readable_file_size(bot_ram_free)} | <b>Total:</b> {get_readable_file_size(bot_ram_total)}

💻 <b>System RAM Usage:</b>
{get_progress_bar_string(memory.percent)} {memory.percent}%
• <b>Used:</b> {get_readable_file_size(memory.used)} | <b>Free:</b> {get_readable_file_size(memory.available)} | <b>Total:</b> {get_readable_file_size(memory.total)}

🔄 <b>Swap Memory:</b>
{get_progress_bar_string(swap.percent)} {swap.percent}%
• <b>Used:</b> {get_readable_file_size(swap.used)} | <b>Free:</b> {get_readable_file_size(swap.free)} | <b>Total:</b> {get_readable_file_size(swap.total)}

⚡ <b>CPU Core Allocation:</b>
• <b>Instance Cores:</b> {instance_cpu}
• <b>Total Cores:</b> {sys_cpu} | <b>P-Cores:</b> {p_cores} | <b>V-Cores:</b> {v_cores}
• <b>Usable Cores:</b> {len(Process().cpu_affinity())}

💾 <b>Disk I/O Statistics:</b>
{get_progress_bar_string(disk)} {disk}%
• <b>Read Data:</b> {f"{get_readable_file_size(disk_io.read_bytes)} ({get_readable_time(disk_io.read_time / 1000)})" if disk_io else "Access Denied"}
• <b>Write Data:</b> {f"{get_readable_file_size(disk_io.write_bytes)} ({get_readable_time(disk_io.write_time / 1000)})" if disk_io else "Access Denied"}
• <b>Used:</b> {get_readable_file_size(used)} | <b>Free:</b> {get_readable_file_size(free)} | <b>Total:</b> {get_readable_file_size(total)}</blockquote>
"""
    elif key == "stsys":
        cpu_usage = cpu_percent(interval=0.5)
        sys_cpu = cpu_count(logical=True)
        p_cores = cpu_count(logical=False)
        v_cores = (sys_cpu or 0) - (p_cores or 0)
        msg = f"""<b>💻 Operating System & Network Statistics</b>

<blockquote>🐧 <b>OS Information:</b>
• <b>Uptime:</b> {get_readable_time(time() - boot_time())}
• <b>Version:</b> {version()}
• <b>Arch:</b> {platform()}

🌐 <b>Network Usage:</b>
• <b>Uploaded:</b> {get_readable_file_size(net_io_counters().bytes_sent)}
• <b>Downloaded:</b> {get_readable_file_size(net_io_counters().bytes_recv)}
• <b>Total I/O:</b> {get_readable_file_size(net_io_counters().bytes_recv + net_io_counters().bytes_sent)}

⚡ <b>Processor Load:</b>
{get_progress_bar_string(cpu_usage)} {cpu_usage}%
• <b>CPU Frequency:</b> {f"{cpu_freq().current / 1000:.2f} GHz" if cpu_freq() else "N/A"}
• <b>Average Load:</b> {"%, ".join(str(round((x / (cpu_count() or 1) * 100), 2)) for x in getloadavg())}% (1m, 5m, 15m)
• <b>Total Cores:</b> {sys_cpu} (P: {p_cores} | V: {v_cores})</blockquote>
"""
    elif key == "strepo":
        last_commit = git_info.commit_date() or "No Data"
        changelog = git_info.commit_msg() or "N/A"
        if git_info.commit_hash() != "unknown":
            changelog += f" (<code>{git_info.commit_hash()}</code>)"
        official_v = (
            await cmd_exec(
                f"curl -o latestversion.py https://raw.githubusercontent.com/SilentDemonSD/WZML-X/{Config.UPSTREAM_BRANCH}/bot/version.py -s && python3 latestversion.py && rm latestversion.py",
                True,
            )
        )[0]
        msg = f"""<b>📦 Repository Version Information</b>

<blockquote>• <b>Last Updated:</b> {last_commit}
• <b>Installed Version:</b> {get_version()}
• <b>Upstream Version:</b> {official_v}
• <b>Recent Commit:</b> {changelog}

📌 <b>Status:</b> <code>{compare_versions(get_version(), official_v)}</code></blockquote>
"""
    elif key == "stpkgs":
        ver = bot_cache.get("eng_versions", {})
        get_v = lambda k, d: ver.get(k) if ver.get(k) and ver.get(k) != "N/A" else d
        msg = f"""<b>⚙️ Engine & Package Versions</b>

<blockquote>• <b>Python:</b> v{get_v("python", "3.12.3")}
• <b>Aria2:</b> v{get_v("aria2", "1.37.0")}
• <b>qBittorrent:</b> v{get_v("qBittorrent", "5.2.3")}
• <b>SABnzbd+:</b> v{get_v("SABnzbd+", "4.2.2")}
• <b>Rclone:</b> v{get_v("rclone", "1.75.1")}
• <b>yt-dlp:</b> v{get_v("yt-dlp", "2026.08.19")}
• <b>FFmpeg:</b> v{get_v("ffmpeg", "9.0.2")}
• <b>7-Zip:</b> v{get_v("7z", "26.03")}
• <b>Aiohttp:</b> v{get_v("aiohttp", "3.14.3")}
• <b>WzGram:</b> v{get_v("wzgram", "3.1.3")}
• <b>Google API:</b> v{get_v("gapi", "2.201.0")}
• <b>MegaSDK:</b> v{get_v("mega", "10.20.0")}</blockquote>
"""
    elif key == "tlimits":
        msg = f"""<b>🛑 Bot Task Configuration & Limits</b>

<blockquote>• <b>Direct Limit:</b> {Config.DIRECT_LIMIT or "∞"} GB
• <b>Torrent Limit:</b> {Config.TORRENT_LIMIT or "∞"} GB
• <b>GDrive DL Limit:</b> {Config.GD_DL_LIMIT or "∞"} GB
• <b>Rclone DL Limit:</b> {Config.RC_DL_LIMIT or "∞"} GB
• <b>Clone Limit:</b> {Config.CLONE_LIMIT or "∞"} GB
• <b>JDownloader Limit:</b> {Config.JD_LIMIT or "∞"} GB
• <b>NZB Limit:</b> {Config.NZB_LIMIT or "∞"} GB
• <b>YT-DLP Limit:</b> {Config.YTDLP_LIMIT or "∞"} GB
• <b>Playlist Limit:</b> {Config.PLAYLIST_LIMIT or "∞"}
• <b>Mega Limit:</b> {Config.MEGA_LIMIT or "∞"} GB
• <b>Leech Limit:</b> {Config.LEECH_LIMIT or "∞"} GB
• <b>Archive Limit:</b> {Config.ARCHIVE_LIMIT or "∞"} GB
• <b>Extract Limit:</b> {Config.EXTRACT_LIMIT or "∞"} GB
• <b>Storage Threshold:</b> {Config.STORAGE_LIMIT or "∞"} GB

• <b>Token Validity:</b> {get_readable_time(Config.VERIFY_TIMEOUT) if Config.VERIFY_TIMEOUT else "Disabled"}
• <b>User Time Interval:</b> {Config.USER_TIME_INTERVAL or "0"}s
• <b>User Max Tasks:</b> {Config.USER_MAX_TASKS or "∞"}
• <b>Bot Max Tasks:</b> {Config.BOT_MAX_TASKS or "∞"}</blockquote>
"""

    elif key == "systasks":
        try:
            processes = []
            for proc in process_iter(
                ["pid", "name", "cpu_percent", "memory_percent", "username"]
            ):
                try:
                    info = proc.info
                    if (
                        info.get("cpu_percent", 0) > 1.0
                        or info.get("memory_percent", 0) > 1.0
                    ):
                        processes.append(info)
                except (NoSuchProcess, AccessDenied):
                    continue
            processes.sort(
                key=lambda x: x.get("cpu_percent", 0) + x.get("memory_percent", 0),
                reverse=True,
            )
            processes = processes[:15]
        except Exception:
            processes = []

        msg = "<b>⚡ High Resource System Tasks</b>\n\n"

        if processes:
            msg += "<blockquote>"
            for i, proc in enumerate(processes, 1):
                name = proc.get("name", "Unknown")[:20]
                cpu = proc.get("cpu_percent", 0)
                mem = proc.get("memory_percent", 0)
                user = proc.get("username", "Unknown")[:10]
                msg += f"<b>{i}. {name}</b> (PID: {proc['pid']})\n• CPU: {cpu:.1f}% | MEM: {mem:.1f}% | User: {user}\n"
                btns.data_button(f"{i}", f"stats {user_id} killproc {proc['pid']}")
            msg += "Click index button to terminate a process.</blockquote>"
        else:
            msg += "<blockquote>No high usage processes currently running.</blockquote>"

        btns.data_button("🔄 Refresh", f"stats {user_id} systasks", "header")

    btns.data_button("◀️ Back", f"stats {user_id} home", "footer")
    btns.data_button(
        "❌ Close", f"stats {user_id} close", "footer", style=ButtonStyle.DANGER
    )
    return msg, btns.build_menu(8 if key == "systasks" else 2)


@new_task
async def bot_stats(_, message):
    msg, btns = await get_stats(message)
    await send_message(message, msg, btns, photo="IMAGES")


@new_task
async def stats_pages(_, query):
    data = query.data.split()
    message = query.message
    user_id = query.from_user.id
    if user_id != int(data[1]):
        await query.answer("This menu is not for you!", show_alert=True)
    elif data[2] == "close":
        await query.answer()
        await delete_message(message, message.reply_to_message)
    elif data[2] == "killproc":
        if not await CustomFilters.owner(_, query):
            await query.answer("You cannot terminate system processes!", show_alert=True)
            return
        pid = int(data[3])
        try:
            process = Process(pid)
            proc_name = process.name()
            process.terminate()
            await sleep(2)
            if process.is_running():
                process.kill()
                status = "🔥 Force killed"
            else:
                status = "✅ Terminated"
            await query.answer(f"{status}: {proc_name} (PID: {pid})", show_alert=True)
        except NoSuchProcess:
            await query.answer(
                "❌ Process not found or already closed!", show_alert=True
            )
        except AccessDenied:
            await query.answer(
                "❌ Access denied! Cannot kill this process.", show_alert=True
            )
        except Exception as e:
            await query.answer(f"❌ Error: {str(e)}", show_alert=True)

        msg, btns = await get_stats(query, "systasks")
        await edit_message(message, msg, btns)
    else:
        if data[2] == "systasks" and not await CustomFilters.sudo(_, query):
            await query.answer("You cannot view system tasks!", show_alert=True)
            return
        await query.answer()
        msg, btns = await get_stats(query, data[2])
        await edit_message(message, msg, btns)


async def get_version_async(command, regex, timeout=5):
    try:
        out, err, code = await wait_for(cmd_exec(command), timeout=timeout)
        if code != 0:
            return "N/A"
        match = research(regex, out)
        return match.group(1) if match else "N/A"
    except Exception:
        return "N/A"


async def retry_mega_version():
    await sleep(60)
    command, regex = commands["mega"]
    version = await get_version_async(command, regex, timeout=10)
    if version != "N/A":
        bot_cache["eng_versions"]["mega"] = version
        LOGGER.info(f"MegaSDK Version Fetched: {version}")
    else:
        LOGGER.warning(f"Failed to fetch MegaSDK Version: {version}")


@new_task
async def get_packages_version():
    tasks = [get_version_async(command, regex) for command, regex in commands.values()]
    versions = await gather(*tasks)
    bot_cache["eng_versions"] = {}
    for tool, ver in zip(commands.keys(), versions):
        bot_cache["eng_versions"][tool] = ver
    if await aiopath.exists(".git"):
        last_commit = await cmd_exec(
            "git log -1 --date=short --pretty=format:'%cd <b>From</b> %cr'", True
        )
        last_commit = last_commit[0]
    else:
        last_commit = "No UPSTREAM_REPO"
    bot_cache["commit"] = last_commit

    if bot_cache["eng_versions"]["mega"] in ["Timeout", "N/A"] or bot_cache[
        "eng_versions"
    ]["mega"].startswith("Exception"):
        bot_loop.create_task(retry_mega_version())

    LOGGER.info("Fetched Package Versions!")
