# ruff: noqa: E402
try:
    from uvloop import install

    install()
except ImportError:
    pass

from asyncio import new_event_loop, set_event_loop

bot_loop = new_event_loop()
set_event_loop(bot_loop)

from asyncio import Lock
from logging import (
    ERROR,
    INFO,
    WARNING,
    FileHandler,
    StreamHandler,
    basicConfig,
    getLogger,
)
from time import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .core.config_manager import Config
from sabnzbdapi import SabnzbdClient

getLogger("niquests").setLevel(WARNING)
getLogger("pyrogram").setLevel(ERROR)
getLogger("apscheduler").setLevel(ERROR)
getLogger("pymongo").setLevel(WARNING)
getLogger("aiohttp").setLevel(WARNING)


bot_start_time = time()

basicConfig(
    format="[%(asctime)s] [%(levelname)s] - %(message)s",  #  [%(filename)s:%(lineno)d]
    datefmt="%d-%b-%y %I:%M:%S %p",
    handlers=[FileHandler("log.txt"), StreamHandler()],
    level=INFO,
)

LOGGER = getLogger(__name__)

def patch_rsa_exception_syntax():
    import site
    import os
    import re

    site_pkgs = site.getsitepackages()
    for sp in site_pkgs:
        if not os.path.exists(sp):
            continue
        for root, _, files in os.walk(sp):
            for file_ in files:
                if file_.lower() == "rsa.py":
                    fp = os.path.join(root, file_)
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        if "except TypeError, ValueError:" in content or re.search(r"except\s+[A-Za-z0-9_.]+\s*,\s*[A-Za-z0-9_.]+\s*:", content):
                            new_content = re.sub(
                                r"except\s+([A-Za-z0-9_.]+)\s*,\s*([A-Za-z0-9_.]+)\s*:",
                                r"except (\1, \2):",
                                content
                            )
                            with open(fp, "w", encoding="utf-8") as f:
                                f.write(new_content)
                            LOGGER.info(f"Patched RSA exception syntax in {fp}")
                    except Exception as e:
                        LOGGER.warning(f"Failed to check/patch {fp}: {e}")

try:
    patch_rsa_exception_syntax()
except Exception as e:
    LOGGER.warning(f"RSA syntax patch error: {e}")

bot_cache = {}
DOWNLOAD_DIR = "/usr/src/app/downloads/"
intervals = {"status": {}, "qb": "", "jd": "", "nzb": "", "stopAll": False}
qb_torrents = {}
jd_downloads = {}
nzb_jobs = {}
user_data = {}
aria2_options = {}
qbit_options = {}
nzb_options = {}
queued_dl = {}
queued_up = {}
status_dict = {}
task_dict = {}
planner_tasks = {}
active_range_tasks = {}
rss_dict = {}
shortener_dict = {}
categories_dict = {}
list_drives_dict = {}
var_list = [
    "BOT_TOKEN",
    "TELEGRAM_API",
    "TELEGRAM_HASH",
    "OWNER_ID",
    "DATABASE_URL",
    "BASE_URL",
    "UPSTREAM_REPO",
    "UPSTREAM_BRANCH",
]
auth_chats = {}
excluded_extensions = ["aria2", "!qB"]
drives_names = []
drives_ids = []
index_urls = []
sudo_users = []
non_queued_dl = set()
non_queued_up = set()
multi_tags = set()
task_dict_lock = Lock()
queue_dict_lock = Lock()
qb_listener_lock = Lock()
nzb_listener_lock = Lock()
jd_listener_lock = Lock()
same_directory_lock = Lock()


def _sabnzbd_key():
    from bot.helper.ext_utils.bot_utils import derive_service_password

    return derive_service_password(
        (Config.BOT_TOKEN or "").split(":", 1)[0] or "0",
        "sabnzbd",
    )


def _update_sabnzbd_ini(api_key):
    from re import compile as _re, MULTILINE

    pat_key = _re(r"^api_key\s*=.*$", MULTILINE)
    pat_pwd = _re(r"^password\s*=.*$", MULTILINE)
    try:
        with open("configs/sabnzbd/SABnzbd.ini", "r+") as f:
            content = f.read()
            new = content
            new = pat_key.sub(f"api_key = {api_key}", new)
            new = pat_pwd.sub(f"password = {api_key}", new)
            if new == content:
                return
            f.seek(0)
            f.truncate()
            f.write(new)
            LOGGER.info("SABnzbd.ini Updated with derived api_key")
    except FileNotFoundError:
        LOGGER.warning("SABnzbd.ini not found, skipping patch")
    except Exception as e:
        LOGGER.error(f"SABnzbd.ini patch failed: {e}")


if not Config.WEB_ACCESS_PASSWORD:
    from secrets import token_hex

    Config.WEB_ACCESS_PASSWORD = token_hex(32)

_sabnzbd_api_key = _sabnzbd_key()

sabnzbd_client = SabnzbdClient(
    host="http://localhost",
    api_key=_sabnzbd_api_key,
    port="8070",
    RETRIES=1,
)

scheduler = AsyncIOScheduler(event_loop=bot_loop)
