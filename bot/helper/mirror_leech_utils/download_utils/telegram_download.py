import re
from asyncio import Lock, sleep
from os import path as ospath
from time import time
from secrets import token_hex
from aiofiles.os import makedirs
from pyrogram.errors import FloodWait, PeerIdInvalid, ChannelInvalid

from bot.helper.ext_utils.hyperdl_utils import HypertgDownload

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:
    FloodPremiumWait = FloodWait

from .... import (
    LOGGER,
    task_dict,
    task_dict_lock,
)
from ....core.tg_client import TgClient
from ....core.config_manager import Config
from ...ext_utils.task_manager import check_running_tasks, stop_duplicate_check
from ...mirror_leech_utils.status_utils.queue_status import QueueStatus
from ...mirror_leech_utils.status_utils.telegram_status import TelegramStatus
from ...telegram_helper.message_utils import send_status_message

global_lock = Lock()
GLOBAL_GID = dict()


def clean_caption_filename(caption: str, fallback_filename: str) -> str:
    if not caption or not caption.strip():
        return fallback_filename

    ext = ospath.splitext(fallback_filename)[1] if fallback_filename and "." in fallback_filename else ""
    lines = [line.strip() for line in caption.split("\n") if line.strip()]
    cleaned_title = ""

    for line in lines:
        line_clean = re.sub(r"[^\w\s\.\-\_\(\)\[\]]", "", line).strip()
        if not line_clean:
            continue

        if re.search(r"\b(size|duration|languages|language|audio|subtitles|subtitle|quality|codec|fps)\b\s*:", line_clean, re.IGNORECASE):
            continue

        cleaned_title = line_clean
        break

    if not cleaned_title:
        return fallback_filename

    if ext and not cleaned_title.lower().endswith(ext.lower()):
        if not re.search(r"\.[a-zA-Z0-9]{2,4}$", cleaned_title):
            cleaned_title += ext

    return cleaned_title


class TelegramDownloadHelper:
    def __init__(self, listener):
        self._processed_bytes = 0
        self._start_time = 1
        self._listener = listener
        self._id = ""
        self.session = ""
        self._user_client = None
        tm = self._listener.transmission_mode
        self._dump_chat = (
            self._listener.up_dest if self._listener.is_leech else None
        ) or Config.LEECH_LOG_CHAT
        personal_mode = self._listener.user_dict.get("TELEGRAM_SESSION_MODE", "disabled")
        self._hyper_dl = (
            Config.USE_HYPER
            and personal_mode not in ("telegram", "both")
            and self._dump_chat
            and (
                (tm in ("bot", "both") and len(TgClient.helper_bots) != 0)
                or (
                    tm in ("user", "both")
                    and (len(TgClient.helper_users) != 0 or TgClient.user is not None)
                )
            )
        )
        self._hyper_dl_instance = None

    @property
    def speed(self):
        return self._processed_bytes / (time() - self._start_time)

    @property
    def processed_bytes(self):
        return self._processed_bytes

    async def _on_download_start(self, file_id, gid, from_queue):
        async with global_lock:
            GLOBAL_GID[file_id] = gid
        self._id = file_id
        async with task_dict_lock:
            task_dict[self._listener.mid] = TelegramStatus(
                self._listener, self, gid, "dl", "hdl" if self._hyper_dl else ""
            )
        if not from_queue:
            await self._listener.on_download_start()
            if self._listener.multi <= 1:
                await send_status_message(self._listener.message)
            LOGGER.info(f"Download from Telegram: {self._listener.name}")
        else:
            LOGGER.info(f"Start Queued Download from Telegram: {self._listener.name}")

    async def _on_download_progress(self, current, _):
        if self._listener.is_cancelled:
            if self.session == "user":
                self._user_client.stop_transmission()
            elif self.session == "hbots":
                for hbot in TgClient.helper_bots.values():
                    hbot.stop_transmission()
            else:
                TgClient.bot.stop_transmission()
        self._processed_bytes = current

    async def _on_download_error(self, error):
        async with global_lock:
            if self._id in GLOBAL_GID:
                GLOBAL_GID.pop(self._id)
        await self._listener.on_download_error(error)

    async def _on_download_complete(self):
        await self._listener.on_download_complete()
        async with global_lock:
            GLOBAL_GID.pop(self._id)
        return

    async def _download_file(self, message, path):
        try:
            if dir_path := ospath.dirname(path):
                await makedirs(dir_path, exist_ok=True)
            if self._hyper_dl:
                try:
                    self._hyper_dl_instance = HypertgDownload(self)
                    download = await self._hyper_dl_instance.download_media(
                        message,
                        file_name=path,
                        dump_chat=self._dump_chat,
                    )
                    if (
                        self._hyper_dl_instance is not None
                        and self._hyper_dl_instance.dump_chat
                        and self._hyper_dl_instance.message
                        and hasattr(self._hyper_dl_instance.message, "id")
                    ):
                        self._listener.dump_chat = self._hyper_dl_instance.dump_chat
                        self._listener.dump_msg_id = self._hyper_dl_instance.message.id
                    self._hyper_dl_instance = None
                except Exception as e:
                    LOGGER.warning(f"Hyper download failed, using normal: {e}")
                    self._hyper_dl_instance = None
                    if self._listener.transmission_mode in ("user", "both"):
                        self.session = "user"
                        try:
                            user_message = await self._user_client.get_messages(
                                chat_id=message.chat.id, message_ids=message.id
                            )
                            download = await user_message.download(
                                file_name=path, progress=self._on_download_progress
                            )
                        except Exception:
                            download = await message.download(
                                file_name=path, progress=self._on_download_progress
                            )
                    else:
                        self.session = "bot"
                        download = await message.download(
                            file_name=path, progress=self._on_download_progress
                        )
            else:
                download = await message.download(
                    file_name=path, progress=self._on_download_progress
                )
            if self._listener.is_cancelled:
                return False
            return download is not None
        except (FloodWait, FloodPremiumWait) as f:
            LOGGER.warning(str(f))
            await sleep(f.value)
            return await self._download_file(message, path)
        except Exception as e:
            LOGGER.error(str(e), exc_info=True)
            return False

    async def _download(self, message, path):
        success = await self._download_file(message, path)
        if success:
            await self._on_download_complete()
        elif not self._listener.is_cancelled:
            await self._on_download_error("Internal error occurred")
        return

    async def _download_direct_url(self, url, path):
        try:
            import aiohttp
            from aiofiles import open as aiopen
            async with aiohttp.ClientSession() as session:
                async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=1800)) as resp:
                    if resp.status == 200:
                        filename = None
                        if "Content-Disposition" in resp.headers:
                            cd = resp.headers["Content-Disposition"]
                            fname_match = re.findall(r'filename="?([^";]+)"?', cd)
                            if fname_match:
                                filename = fname_match[0]
                        if not filename:
                            filename = url.rsplit("/", 1)[-1].split("?")[0] or f"file_{self._listener.mid}"
                        if ospath.isdir(path) or path.endswith("/"):
                            await makedirs(path, exist_ok=True)
                            dest_file = ospath.join(path, filename)
                        else:
                            dest_file = path
                            await makedirs(ospath.dirname(dest_file), exist_ok=True)
                        async with aiopen(dest_file, "wb") as f:
                            async for chunk in resp.content.iter_chunked(1024 * 1024):
                                await f.write(chunk)
                        return True
        except Exception as e:
            LOGGER.warning(f"Error downloading direct URL {url}: {e}")
        return False

    async def _process_text_links(self, msg_text, path):
        if not msg_text:
            return False
        urls = re.findall(r"(?:https?:\/\/|magnet:\?|tg:\/\/)\S+", msg_text)
        if not urls:
            return False
        found_any = False
        for url in urls:
            if self._listener.is_cancelled:
                break
            url = url.rstrip(".,)]}>\"'")
            if not url:
                continue
            from ...ext_utils.links_utils import (
                is_telegram_link,
                is_url,
                is_magnet,
                is_gdrive_link,
                is_gdrive_id,
                is_mega_link,
            )
            if is_telegram_link(url):
                try:
                    from ...telegram_helper.message_utils import get_tg_link_message
                    user_range_mode = self._listener.user_dict.get("RANGE_LINK_MODE") or getattr(Config, "RANGE_LINK_MODE", "normal")
                    tg_msg, s_sess = await get_tg_link_message(url, range_mode=user_range_mode, user_id=self._listener.user_id, user_dict=self._listener.user_dict)
                    if isinstance(tg_msg, list):
                        for tm in tg_msg:
                            if isinstance(tm, str):
                                sub_msg, _ = await get_tg_link_message(tm, range_mode="normal", user_id=self._listener.user_id, user_dict=self._listener.user_dict)
                                tm = sub_msg[0] if isinstance(sub_msg, list) and sub_msg else sub_msg
                            if getattr(tm, "media", None):
                                m_obj = getattr(tm, tm.media.value)
                                f_name = (
                                    m_obj.file_name.rsplit("/", 1)[-1]
                                    if hasattr(m_obj, "file_name") and m_obj.file_name
                                    else f"file_{getattr(tm, 'id', self._listener.mid)}"
                                )
                                await self._download_file(tm, ospath.join(path, f_name))
                                found_any = True
                            elif getattr(tm, "text", None) or getattr(tm, "caption", None):
                                sub_res = await self._process_text_links(tm.text or tm.caption, path)
                                if sub_res:
                                    found_any = True
                    elif tg_msg and getattr(tg_msg, "media", None):
                        m_obj = getattr(tg_msg, tg_msg.media.value)
                        f_name = (
                            m_obj.file_name.rsplit("/", 1)[-1]
                            if hasattr(m_obj, "file_name") and m_obj.file_name
                            else f"file_{getattr(tg_msg, 'id', self._listener.mid)}"
                        )
                        await self._download_file(tg_msg, ospath.join(path, f_name))
                        found_any = True
                    elif tg_msg and (getattr(tg_msg, "text", None) or getattr(tg_msg, "caption", None)):
                        sub_res = await self._process_text_links(tg_msg.text or tg_msg.caption, path)
                        if sub_res:
                            found_any = True
                except Exception as e:
                    LOGGER.warning(f"Error fetching nested TG link {url}: {e}")
            elif is_gdrive_link(url) or is_gdrive_id(url):
                try:
                    from ..download_utils.gd_download import add_gd_download
                    orig_link = self._listener.link
                    self._listener.link = url
                    await add_gd_download(self._listener, path)
                    self._listener.link = orig_link
                    found_any = True
                except Exception as e:
                    LOGGER.warning(f"Error downloading GD link {url}: {e}")
            elif is_mega_link(url):
                try:
                    from ..download_utils.mega_download import add_mega_download
                    orig_link = self._listener.link
                    self._listener.link = url
                    await add_mega_download(self._listener, path)
                    self._listener.link = orig_link
                    found_any = True
                except Exception as e:
                    LOGGER.warning(f"Error downloading Mega link {url}: {e}")
            elif is_magnet(url) or (is_url(url) and (url.endswith(".torrent") or "magnet:" in url)):
                try:
                    from ..download_utils.aria2_download import add_aria2_download
                    orig_link = self._listener.link
                    self._listener.link = url
                    await add_aria2_download(self._listener, path, "", None, None)
                    self._listener.link = orig_link
                    found_any = True
                except Exception as e:
                    LOGGER.warning(f"Error downloading torrent/magnet link {url}: {e}")
            elif is_url(url):
                res = await self._download_direct_url(url, path)
                if res:
                    found_any = True
        return found_any

    async def add_download(self, message, path, session):
        self.session = session
        session_mode = self._listener.user_dict.get("TELEGRAM_SESSION_MODE", "disabled")
        if session_mode in ("telegram", "both"):
            self._user_client = await TgClient.get_personal_user(
                self._listener.user_id,
                self._listener.user_dict.get("TELEGRAM_SESSION_STRING"),
            )
            if self._user_client:
                self.session = "user"
            else:
                LOGGER.warning(
                    "Personal Telegram session unavailable, falling back to bot/helper session"
                )
        if self._user_client is None and TgClient.user is not None:
            self._user_client = TgClient.user
        if not self.session:
            if self._hyper_dl:
                self.session = "hbots"
            elif (
                self._listener.transmission_mode in ("user", "both")
                and self._listener.is_super_chat
            ):
                if not self._user_client:
                    LOGGER.warning(
                        "User session not available, downloading with bot session"
                    )
                    self.session = "bot"
                else:
                    self.session = "user"
                    try:
                        message = await self._user_client.get_messages(
                            chat_id=message.chat.id, message_ids=message.id
                        )
                    except (PeerIdInvalid, ChannelInvalid):
                        LOGGER.warning(
                            "User session is not in this chat, downloading with bot session"
                        )
                        self.session = "bot"
            else:
                self.session = "bot"
        media = getattr(message, message.media.value) if message.media else None

        if media is not None:
            async with global_lock:
                download = media.file_unique_id not in GLOBAL_GID

            if download:
                fallback_name = (
                    media.file_name.rsplit("/", 1)[-1]
                    if hasattr(media, "file_name") and media.file_name
                    else f"file_{self._listener.mid}"
                )
                name_source = self._listener.user_dict.get("NAME_SOURCE", "caption")
                if name_source == "caption" and message.caption:
                    self._listener.name = clean_caption_filename(message.caption, fallback_name)
                elif not self._listener.name:
                    self._listener.name = fallback_name

                if path.endswith("/"):
                    path = path + self._listener.name
                self._listener.size = media.file_size
                gid = token_hex(5)

                add_to_queue, event = await check_running_tasks(self._listener)
                if add_to_queue:
                    LOGGER.info(f"Added to Queue/Download: {self._listener.name}")
                    async with task_dict_lock:
                        task_dict[self._listener.mid] = QueueStatus(
                            self._listener, gid, "dl"
                        )
                    await self._listener.on_download_start()
                    if self._listener.multi <= 1:
                        await send_status_message(self._listener.message)
                    await event.wait()
                    if self.session == "bot":
                        message = await self._listener.client.get_messages(
                            chat_id=message.chat.id, message_ids=message.id
                        )
                    elif self._user_client:
                        try:
                            message = await self._user_client.get_messages(
                                chat_id=message.chat.id, message_ids=message.id
                            )
                        except (PeerIdInvalid, ChannelInvalid):
                            message = await self._listener.client.get_messages(
                                chat_id=message.chat.id, message_ids=message.id
                            )
                    else:
                        message = await self._listener.client.get_messages(
                            chat_id=message.chat.id, message_ids=message.id
                        )
                    if self._listener.is_cancelled:
                        async with global_lock:
                            if self._id in GLOBAL_GID:
                                GLOBAL_GID.pop(self._id)
                        return
                self._start_time = time()
                await self._on_download_start(media.file_unique_id, gid, add_to_queue)
                await self._download(message, path)
                msg_text = message.text or message.caption or ""
                if msg_text:
                    await self._process_text_links(msg_text, ospath.dirname(path) if ospath.isfile(path) else path)
            else:
                await self._on_download_error("File already being downloaded!")
        else:
            msg_text = message.text or message.caption or ""
            if msg_text:
                gid = token_hex(5)
                self._start_time = time()
                await self._on_download_start(f"txt_{self._listener.mid}", gid, False)
                res = await self._process_text_links(msg_text, path)
                if res and not self._listener.is_cancelled:
                    await self._on_download_complete()
                elif not self._listener.is_cancelled:
                    await self._on_download_error("No valid downloadable link found in message text!")
            else:
                await self._on_download_error(
                    "No document or link found in the replied message!"
                )

    async def add_range_download(self, messages, path, session):
        self.session = session or "bot"
        if not self._listener.name:
            self._listener.name = f"Telegram_Range_{self._listener.mid}"

        total_size = 0
        for msg in messages:
            if msg.media:
                media = getattr(msg, msg.media.value, None)
                if media and hasattr(media, "file_size") and media.file_size:
                    total_size += media.file_size
        self._listener.size = total_size

        gid = token_hex(5)
        add_to_queue, event = await check_running_tasks(self._listener)
        if add_to_queue:
            LOGGER.info(f"Added to Queue/Download: {self._listener.name}")
            async with task_dict_lock:
                task_dict[self._listener.mid] = QueueStatus(
                    self._listener, gid, "dl"
                )
            await self._listener.on_download_start()
            if self._listener.multi <= 1:
                await send_status_message(self._listener.message)
            await event.wait()
            if self._listener.is_cancelled:
                async with global_lock:
                    if self._id in GLOBAL_GID:
                        GLOBAL_GID.pop(self._id)
                return

        self._start_time = time()
        await self._on_download_start(f"range_{self._listener.mid}", gid, add_to_queue)

        for message in messages:
            if self._listener.is_cancelled:
                break

            if isinstance(message, str):
                try:
                    from ...telegram_helper.message_utils import get_tg_link_message
                    sub_msg, _ = await get_tg_link_message(message, range_mode="normal", user_id=self._listener.user_id, user_dict=self._listener.user_dict)
                    if isinstance(sub_msg, list):
                        message = sub_msg[0]
                    else:
                        message = sub_msg
                except Exception as e:
                    LOGGER.warning(f"Error resolving TG link string {message}: {e}")
                    continue

            media = getattr(message, message.media.value) if hasattr(message, "media") and message.media else None
            if media is not None:
                fallback_name = (
                    media.file_name.rsplit("/", 1)[-1]
                    if hasattr(media, "file_name") and media.file_name
                    else f"file_{getattr(message, 'id', self._listener.mid)}"
                )
                name_source = self._listener.user_dict.get("NAME_SOURCE", "caption")
                if name_source == "caption" and getattr(message, "caption", None):
                    file_name = clean_caption_filename(message.caption, fallback_name)
                else:
                    file_name = fallback_name

                file_path = ospath.join(path, file_name)
                await self._download_file(message, file_path)

            msg_text = (getattr(message, "text", "") or getattr(message, "caption", "")) if hasattr(message, "text") or hasattr(message, "caption") else ""
            if msg_text:
                await self._process_text_links(msg_text, path)

        if not self._listener.is_cancelled:
            await self._on_download_complete()

    async def cancel_task(self):
        self._listener.is_cancelled = True
        LOGGER.info(
            f"Cancelling download on user request: name: {self._listener.name} id: {self._id}"
        )
        if self._hyper_dl_instance:
            try:
                await self._hyper_dl_instance.cancel()
            except Exception:
                pass
            self._hyper_dl_instance = None
        await self._on_download_error("Stopped by user!")
