from asyncio import TimeoutError, create_subprocess_exec, gather, sleep
from contextlib import suppress
from inspect import iscoroutinefunction
from pathlib import Path
from os import getcwd
from time import time

from aioaria2 import Aria2WebsocketClient
from aiohttp import ClientError
from aioqbt.client import create_client
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .. import LOGGER, aria2_options
from ..helper.ext_utils.bot_utils import derive_service_password
from .config_manager import BinConfig, Config


def wrap_with_retry(obj, max_retries=3):
    for attr_name in dir(obj):
        if attr_name.startswith("_"):
            continue

        attr = getattr(obj, attr_name)
        if iscoroutinefunction(attr):
            retry_policy = retry(
                stop=stop_after_attempt(max_retries),
                wait=wait_exponential(multiplier=1, min=1, max=5),
                retry=retry_if_exception_type(
                    (ClientError, TimeoutError, RuntimeError)
                ),
            )
            wrapped = retry_policy(attr)
            setattr(obj, attr_name, wrapped)
    return obj


def _qbit_password():
    return derive_service_password(
        (Config.BOT_TOKEN or "").split(":", 1)[0] or "0",
        "qbit",
    )


async def _connect_aria2(retries=5, delay=2):
    from aioaria2.exceptions import Aria2rpcException

    for i in range(retries):
        try:
            return await Aria2WebsocketClient.new("http://localhost:6800/jsonrpc")
        except Aria2rpcException:
            if i == retries - 1:
                raise
            await sleep(delay)


class TorrentManager:
    aria2 = None
    qbittorrent = None
    _qbit_process = None
    _last_qbit_restart = 0
    _restart_debounce = 60

    @classmethod
    async def _auth_qbit(cls):
        if cls.qbittorrent is None:
            return False
        pwd = _qbit_password()
        try:
            await cls.qbittorrent.auth.login("admin", pwd)
            return True
        except Exception:
            return False

    @classmethod
    async def initiate(cls):
        if cls.aria2:
            return
        try:
            cls.aria2 = await _connect_aria2()
            LOGGER.info("Aria2 initialized successfully.")

            if Config.DISABLE_TORRENTS:
                LOGGER.info("Torrents are disabled.")
                return

            cls._qbit_process = await create_subprocess_exec(
                BinConfig.QBIT_NAME, "-d", f"--profile={getcwd()}/configs/qbittorrent"
            )
            await sleep(2)
            LOGGER.info("qBittorrent started !")

            cls.qbittorrent = await create_client("http://localhost:8090/api/v2/")
            cls.qbittorrent = wrap_with_retry(cls.qbittorrent)
            await cls._auth_qbit()

        except Exception as e:
            LOGGER.error(f"Error during initialization: {e}")
            await cls.close_all()
            raise

    @classmethod
    async def close_all(cls):
        close_tasks = []
        if cls.aria2:
            close_tasks.append(cls.aria2.close())
            cls.aria2 = None
        if cls.qbittorrent:
            close_tasks.append(cls.qbittorrent.close())
            cls.qbittorrent = None
        if close_tasks:
            await gather(*close_tasks)

    @classmethod
    async def ensure_qbit(cls):
        if cls.qbittorrent is None:
            return await cls._start_qbit()
        try:
            await cls.qbittorrent.app.version()
            return True
        except Exception:
            return await cls._start_qbit()

    @classmethod
    async def _start_qbit(cls):
        now = time()
        if now - cls._last_qbit_restart < cls._restart_debounce:
            return False
        cls._last_qbit_restart = now
        LOGGER.info("(Re)starting qBittorrent...")
        try:
            if cls.qbittorrent:
                try:
                    await cls.qbittorrent.close()
                except Exception:
                    pass
                cls.qbittorrent = None
            cls._qbit_process = await create_subprocess_exec(
                BinConfig.QBIT_NAME, "-d", f"--profile={getcwd()}/configs/qbittorrent"
            )
            await sleep(3)
            cls.qbittorrent = await create_client("http://localhost:8090/api/v2/")
            cls.qbittorrent = wrap_with_retry(cls.qbittorrent)
            await cls._auth_qbit()
            LOGGER.info("qBittorrent (re)started successfully")
            return True
        except Exception as e:
            LOGGER.error(f"Failed to (re)start qBittorrent: {e}")
            return False

    @classmethod
    async def aria2_remove(cls, download):
        if download.get("status", "") in ["active", "paused", "waiting"]:
            await cls.aria2.forceRemove(download.get("gid", ""))
        else:
            with suppress(Exception):
                await cls.aria2.removeDownloadResult(download.get("gid", ""))

    @classmethod
    async def remove_all(cls):
        await cls.pause_all()
        if cls.qbittorrent:
            await gather(
                cls.qbittorrent.torrents.delete("all", False),
                cls.aria2.purgeDownloadResult(),
            )
        else:
            await gather(
                cls.aria2.purgeDownloadResult(),
            )
        downloads = []
        results = await gather(cls.aria2.tellActive(), cls.aria2.tellWaiting(0, 1000))
        for res in results:
            downloads.extend(res)
        tasks = []
        tasks.extend(
            cls.aria2.forceRemove(download.get("gid")) for download in downloads
        )
        with suppress(Exception):
            await gather(*tasks)

    @classmethod
    async def overall_speed(cls):
        aria2_speed = await cls.aria2.getGlobalStat()
        download_speed = int(aria2_speed.get("downloadSpeed", "0"))
        upload_speed = int(aria2_speed.get("uploadSpeed", "0"))

        if cls.qbittorrent:
            qb_speed = await cls.qbittorrent.transfer.info()
            download_speed += qb_speed.dl_info_speed
            upload_speed += qb_speed.up_info_speed

        return download_speed, upload_speed

    @classmethod
    async def pause_all(cls):
        pause_tasks = [cls.aria2.forcePauseAll()]
        if cls.qbittorrent:
            pause_tasks.append(cls.qbittorrent.torrents.stop("all"))
        await gather(*pause_tasks)

    @classmethod
    async def change_aria2_option(cls, key, value):
        downloads = []
        results = await gather(cls.aria2.tellActive(), cls.aria2.tellWaiting(0, 1000))
        for res in results:
            downloads.extend(res)
        tasks = [
            cls.aria2.changeOption(download.get("gid"), {key: value})
            for download in downloads
            if download.get("status", "") != "complete"
        ]
        if tasks:
            try:
                await gather(*tasks)
            except Exception as e:
                LOGGER.error(e)
        if key not in ["checksum", "index-out", "out", "pause", "select-file"]:
            await cls.aria2.changeGlobalOption({key: value})
            aria2_options[key] = value


def aria2_name(download_info):
    if "bittorrent" in download_info and download_info["bittorrent"].get("info"):
        return download_info["bittorrent"]["info"]["name"]
    elif download_info.get("files"):
        if download_info["files"][0]["path"].startswith("[METADATA]"):
            return download_info["files"][0]["path"]
        file_path = download_info["files"][0]["path"]
        dir_path = download_info["dir"]
        if file_path.startswith(dir_path):
            return Path(file_path[len(dir_path) + 1 :]).parts[0]
        else:
            return ""
    else:
        return ""


def is_metadata(download_info):
    return any(
        f["path"].startswith("[METADATA]") for f in download_info.get("files", [])
    )
