from asyncio import sleep
from logging import getLogger
from os import path as ospath, walk
from re import match as re_match, sub as re_sub
from time import time

from aioshutil import rmtree
from natsort import natsorted
from pyrogram import StopTransmission
from pyrogram.enums import ChatType
from pyrogram.errors import FloodWait, RPCError

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:
    FloodPremiumWait = FloodWait

from aiofiles.os import (
    path as aiopath,
    remove,
    rename,
)
from pyrogram.types import (
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    ReplyParameters,
)

from ....core.config_manager import Config
from ....core.tg_client import TgClient
from ...ext_utils.bot_utils import sync_to_async
from ...ext_utils.files_utils import get_base_name, is_archive
from ...ext_utils.status_utils import get_readable_file_size, get_readable_time

from ...ext_utils.media_utils import get_md5_hash, get_media_info
from ...telegram_helper.message_utils import delete_message
from ...ext_utils.hyperul_utils import HypertgUpload

LOGGER = getLogger(__name__)


async def _call_with_flood_retry(method, *args, **kwargs):
    while True:
        try:
            return await method(*args, **kwargs)
        except (FloodWait, FloodPremiumWait) as f:
            LOGGER.warning(f"FloodWait {f.value}s, retrying {method.__name__}")
            await sleep(f.value + 1)


class TelegramUploader:
    def __init__(self, listener, path):
        self._processed_bytes = 0
        self._listener = listener
        self._path = path
        self._start_time = time()
        self._total_files = 0
        self._thumb = self._listener.thumb or listener.user_dict.get("THUMBNAIL") or f"thumbnails/{listener.user_id}.jpg"
        self._msgs_dict = {}
        self._corrupted = 0
        self._is_corrupted = False
        self._media_dict = {"videos": {}, "documents": {}}
        self._last_msg_in_group = False
        self._lprefix = ""
        self._lsuffix = ""
        self._lcaption = ""
        self._lfont = ""
        self._bot_pm = False
        self._media_group = False
        self._is_private = False
        self._sent_msg = None
        self._user_session = self._listener.transmission_mode in ("user", "both")
        self._user_client = None
        self._hu: HypertgUpload | None = None
        self._error = ""
        self._upload_seq = []
        self._msg_to_seq = {}

    async def _user_settings(self):
        settings_map = {
            "MEDIA_GROUP": ("_media_group", False),
            "BOT_PM": ("_bot_pm", False),
            "LEECH_PREFIX": ("_lprefix", ""),
            "LEECH_SUFFIX": ("_lsuffix", ""),
            "LEECH_CAPTION": ("_lcaption", ""),
            "LEECH_FONT": ("_lfont", ""),
        }

        for key, (attr, default) in settings_map.items():
            setattr(
                self,
                attr,
                self._listener.user_dict.get(key) or getattr(Config, key, default),
            )

        user_perm = self._listener.user_dict.get("THUMBNAIL") or f"thumbnails/{self._listener.user_id}.jpg"
        has_custom = await aiopath.exists(str(user_perm))
        thumb_mode = self._listener.user_dict.get("THUMBNAIL_MODE", "custom" if has_custom else "none")

        self._thumb = None
        if thumb_mode == "custom":
            user_thumb = self._listener.thumb or self._listener.user_dict.get("THUMBNAIL") or f"thumbnails/{self._listener.user_id}.jpg"
            if user_thumb and user_thumb != "none":
                if await aiopath.exists(str(user_thumb)):
                    self._thumb = user_thumb
                    self._listener.thumb = user_thumb
                elif isinstance(user_thumb, str) and user_thumb.startswith(("http://", "https://")):
                    from ...ext_utils.media_utils import download_image_thumb
                    downloaded = await download_image_thumb(user_thumb)
                    if downloaded and await aiopath.exists(downloaded):
                        self._thumb = downloaded
                        self._listener.thumb = downloaded

        if self._thumb and self._thumb != "none" and await aiopath.exists(str(self._thumb)):
            from ...ext_utils.media_utils import apply_thumbnail_watermark
            self._thumb = await apply_thumbnail_watermark(self._thumb, self._listener.user_dict)
            self._listener.thumb = self._thumb

        # Optional per-user Telegram session string for uploads.
        session_mode = self._listener.user_dict.get("TELEGRAM_SESSION_MODE", "disabled")
        if session_mode in ("upload", "both"):
            self._user_client = await TgClient.get_personal_user(
                self._listener.user_id,
                self._listener.user_dict.get("TELEGRAM_SESSION_STRING"),
            )
            if self._user_client:
                self._user_session = True
                self._listener.tg_user_client = self._user_client
            else:
                LOGGER.warning(
                    "Personal Telegram upload session unavailable; falling back to configured bot/user session"
                )
        if self._user_client is None and TgClient.user is not None and self._user_session:
            self._user_client = TgClient.user
        if self._user_client is not None:
            self._listener.tg_user_client = self._user_client

        # Check for user configured bot tokens first.
        user_tokens = self._listener.user_dict.get("BOT_TOKENS", [])
        if user_tokens and isinstance(user_tokens, list):
            ubots = await TgClient.get_user_bots(self._listener.user_id, user_tokens)
            if ubots:
                self._hu_clients = ubots
                self._listener.client = list(ubots.values())[0]

        # WZML HyperUP: use the globally started helper bots when available.
        # These are wzgram clients and are load-balanced by HypertgUpload.
        # Keep personal/user sessions isolated so their uploads are never
        # silently transferred through helper accounts.
        if not getattr(self, "_hu_clients", None) and getattr(TgClient, "helper_bots", None):
            self._hu_clients = dict(TgClient.helper_bots)
            LOGGER.info("HyperUP enabled with %d global helper client(s)", len(self._hu_clients))

    async def _msg_to_reply(self):
        from ...ext_utils.bot_utils import parse_dest
        if self._user_session and self._user_client is None:
            self._user_session = False

        if getattr(self._listener, "has_preset_dump", False) and self._listener.key_dump_dests:
            first_dump = self._listener.key_dump_dests[0]
            target_chat_id, _ = parse_dest(first_dump) if not isinstance(first_dump, int) else (first_dump, None)
        elif self._listener.leech_dest:
            target_chat_id, _ = parse_dest(self._listener.leech_dest) if not isinstance(self._listener.leech_dest, int) else (self._listener.leech_dest, self._listener.leech_thread_id)
        elif self._listener.up_dest:
            target_chat_id, _ = parse_dest(self._listener.up_dest) if not isinstance(self._listener.up_dest, int) else (self._listener.up_dest, self._listener.chat_thread_id)
        elif self._listener.user_dict.get("LEECH_DUMP_CHAT"):
            udump = self._listener.user_dict.get("LEECH_DUMP_CHAT")
            target_chat_id, _ = parse_dest(udump) if not isinstance(udump, int) else (udump, None)
        else:
            target_chat_id = self._listener.user_id

        if self._user_session:
            try:
                self._sent_msg = await _call_with_flood_retry(
                    self._user_client.get_messages,
                    chat_id=target_chat_id,
                    message_ids=self._listener.mid,
                )
            except Exception:
                self._sent_msg = None
            if self._sent_msg is None or self._sent_msg.chat is None:
                try:
                    self._sent_msg = await _call_with_flood_retry(
                        self._user_client.send_message,
                        chat_id=target_chat_id,
                        text="Starting upload...",
                        disable_web_page_preview=True,
                        disable_notification=True,
                    )
                except Exception:
                    self._sent_msg = self._listener.message
            if self._sent_msg is None or self._sent_msg.chat is None:
                self._sent_msg = self._listener.message
            self._is_private = self._sent_msg.chat.type == ChatType.PRIVATE
        else:
            if target_chat_id == self._listener.message.chat.id:
                self._sent_msg = self._listener.message
            else:
                try:
                    self._sent_msg = await _call_with_flood_retry(
                        self._user_client.send_message,
                        chat_id=target_chat_id,
                        text="Starting upload...",
                        disable_web_page_preview=True,
                        disable_notification=True,
                    )
                except Exception:
                    self._sent_msg = self._listener.message
            self._is_private = self._sent_msg.chat.type == ChatType.PRIVATE

        return True

    async def _prepare_file(self, pre_file_, dirpath):
        cap_file_ = file_ = pre_file_
        lprefix = self._lprefix
        lsuffix = self._lsuffix
        lcaption = self._lcaption

        if lprefix:
            cap_file_ = lprefix.replace(r"\s", " ") + file_
            lprefix = re_sub(r"<.*?>", "", lprefix).replace(r"\s", " ")
            if not file_.startswith(lprefix):
                file_ = f"{lprefix}{file_}"

        if lsuffix:
            name, ext = ospath.splitext(cap_file_)
            cap_file_ = name + lsuffix.replace(r"\s", " ") + ext
            lsuffix = re_sub(r"<.*?>", "", lsuffix).replace(r"\s", " ")

        lfont = self._lfont
        font_tag = "tg-spoiler" if lfont in ("tg-spoiler", "spoiler") else (lfont if (lfont and lfont != "none") else "")
        cap_mono = cap_file_

        if lcaption:
            lcaption = re_sub(
                r"(\\\||\\\{|\\\}|\\s)",
                lambda m: {r"\|": "%%", r"\{": "&%&", r"\}": "$%$", r"\s": " "}[
                    m.group(0)
                ],
                lcaption,
            )

            parts = lcaption.split("|")
            parts[0] = re_sub(
                r"\{([^}]+)\}", lambda m: f"{{{m.group(1).lower()}}}", parts[0]
            )
            up_path = ospath.join(dirpath, pre_file_)
            media_info_res = await get_media_info(up_path, True)
            if len(media_info_res) == 5:
                dur, qual, lang, subs, langr = media_info_res
            else:
                dur, qual, lang, subs = media_info_res[:4]
                langr = lang
            cap_mono = parts[0].format(
                filename=cap_file_,
                size=get_readable_file_size(await aiopath.getsize(up_path)),
                duration=get_readable_time(dur),
                quality=qual,
                languages=lang,
                languagesr=langr,
                subtitles=subs,
                md5_hash=await sync_to_async(get_md5_hash, up_path),
                mime_type=self._listener.file_details.get("mime_type", "text/plain"),
                prefilename=self._listener.file_details.get("filename", ""),
                precaption=self._listener.file_details.get("caption", ""),
            )

            for part in parts[1:]:
                args = part.split(":")
                cap_mono = cap_mono.replace(
                    args[0],
                    args[1] if len(args) > 1 else "",
                    int(args[2]) if len(args) == 3 else -1,
                )
            cap_mono = re_sub(
                r"%%|&%&|\$%\$",
                lambda m: {"%%": "|", "&%&": "{", "$%$": "}"}[m.group()],
                cap_mono,
            )

        if font_tag and not cap_mono.strip().startswith(f"<{font_tag}>"):
            cap_mono = f"<{font_tag}>{cap_mono}</{font_tag}>"

        if len(file_) > 60:
            if is_archive(file_):
                name = get_base_name(file_)
                ext = file_.split(name, 1)[1]
            elif match := re_match(r".+(?=\..+\.0*\d+$)|.+(?=\.part\d+\..+$)", file_):
                name = match.group(0)
                ext = file_.split(name, 1)[1]
            elif len(fsplit := ospath.splitext(file_)) > 1:
                name = fsplit[0]
                ext = fsplit[1]
            else:
                name = file_
                ext = ""
            if lsuffix:
                ext = f"{lsuffix}{ext}"
            name = name[: 64 - len(ext)]
            file_ = f"{name}{ext}"
        elif lsuffix:
            name, ext = ospath.splitext(file_)
            file_ = f"{name}{lsuffix}{ext}"

        old_path = ospath.join(dirpath, pre_file_)
        new_path = ospath.join(dirpath, file_)
        if old_path != new_path and not await aiopath.exists(new_path):
            try:
                await rename(old_path, new_path)
            except Exception as e:
                LOGGER.warning(f"Failed to rename {old_path} to {new_path}: {e}")
                new_path = old_path

        return new_path, cap_mono

    def _get_input_media(self, subkey, key):
        rlist = []
        for msg in self._media_dict[key][subkey]:
            caption = msg.caption.html if msg.caption else None
            if key == "videos":
                input_media = InputMediaVideo(media=msg.video.file_id, caption=caption)
            else:
                input_media = InputMediaDocument(
                    media=msg.document.file_id, caption=caption
                )
            rlist.append(input_media)
        return rlist

    async def _send_screenshots(self, dirpath, outputs):
        inputs = [
            InputMediaPhoto(ospath.join(dirpath, p), p.rsplit("/", 1)[-1])
            for p in outputs
        ]
        for i in range(0, len(inputs), 10):
            batch = inputs[i : i + 10]
            if Config.BOT_PM:
                await _call_with_flood_retry(
                    TgClient.bot.send_media_group,
                    chat_id=self._listener.user_id,
                    media=batch,
                    disable_notification=True,
                )
            self._sent_msg = (
                await _call_with_flood_retry(
                    self._sent_msg.reply_media_group,
                    media=batch,
                    reply_parameters=ReplyParameters(message_id=self._sent_msg.id),
                    disable_notification=True,
                )
            )[-1]

    async def _send_media_group(self, subkey, key, msgs):
        old_ids = [(msg[0], msg[1]) for msg in msgs]
        for index, msg in enumerate(msgs):
            if self._listener.transmission_mode == "both" or not self._user_session:
                msgs[index] = await _call_with_flood_retry(
                    self._listener.client.get_messages,
                    chat_id=msg[0],
                    message_ids=msg[1],
                )
            else:
                msgs[index] = await _call_with_flood_retry(
                    self._user_client.get_messages, chat_id=msg[0], message_ids=msg[1]
                )
        media = self._get_input_media(subkey, key)
        del self._media_dict[key][subkey]
        if reply_target := msgs[0].reply_to_message:
            msgs_list = await _call_with_flood_retry(
                reply_target.reply_media_group,
                media=media,
                reply_parameters=ReplyParameters(message_id=reply_target.id),
                disable_notification=True,
            )
        else:
            msgs_list = await _call_with_flood_retry(
                (
                    self._listener.client
                    if self._listener.transmission_mode == "both"
                    or not self._user_session
                    else self._user_client
                ).send_media_group,
                chat_id=msgs[0].chat.id,
                media=media,
                disable_notification=True,
                message_thread_id=(
                    self._listener.chat_thread_id
                    if msgs[0].chat.id == self._listener.up_dest
                    else None
                ),
            )
        for msg in msgs:
            if msg.link in self._msgs_dict:
                del self._msgs_dict[msg.link]
            await delete_message(msg)
        if self._listener.is_super_chat or self._listener.up_dest:
            for m in msgs_list:
                self._msgs_dict[m.link] = m.caption
        for i, (old_cid, old_mid) in enumerate(old_ids):
            old_key = (old_cid, old_mid)
            if old_key in self._msg_to_seq:
                seq_idx = self._msg_to_seq.pop(old_key)
                new_msg = msgs_list[i]
                self._upload_seq[seq_idx] = {
                    "chat_id": new_msg.chat.id,
                    "msg_id": new_msg.id,
                    "link": new_msg.link,
                    "file_": self._upload_seq[seq_idx]["file_"],
                }
                self._msg_to_seq[(new_msg.chat.id, new_msg.id)] = seq_idx
        self._sent_msg = msgs_list[-1]

    async def _copy_media(self):
        try:
            if self._bot_pm:
                await _call_with_flood_retry(
                    TgClient.bot.copy_message,
                    chat_id=self._listener.user_id,
                    from_chat_id=self._sent_msg.chat.id,
                    message_id=self._sent_msg.id,
                    reply_to_message_id=(
                        self._listener.pm_msg.id if self._listener.pm_msg else None
                    ),
                )
        except Exception as err:
            if not self._listener.is_cancelled:
                err_msg = str(err)
                if "Can't copy" in err_msg:
                    LOGGER.warning(
                        f"BotPM copy skipped (restricted content): {err_msg}"
                    )
                else:
                    LOGGER.error(f"Failed To Send in BotPM:\n{err_msg}")

    async def _sequence_copies(self, src_chat):
        from ...ext_utils.bot_utils import parse_dest
        destinations = []

        # AUTHORIZED_CHATS is an access-control list, never an implicit upload
        # destination. A chat is allowed here only when it is explicitly a
        # configured dump destination; otherwise uploads fall back to the user DM.
        raw_auth = str(getattr(Config, "AUTHORIZED_CHATS", "") or "")
        auth_ids = set()
        for raw in raw_auth.split():
            base = raw.split("|", 1)[0].strip()
            if base.lstrip("-").isdigit():
                auth_ids.add(int(base))

        allowed_dump_ids = set()
        for raw_dump in [
            self._listener.user_dict.get("LEECH_DUMP_CHAT"),
            getattr(Config, "LEECH_LOG_CHAT", ""),
        ]:
            if raw_dump:
                try:
                    d_chat, _ = parse_dest(raw_dump) if not isinstance(raw_dump, int) else (raw_dump, None)
                    if isinstance(d_chat, int):
                        allowed_dump_ids.add(d_chat)
                except Exception:
                    pass
        for raw_dump in (Config.LEECH_DUMP_CHATS or {}).values():
            if raw_dump:
                try:
                    d_chat, _ = parse_dest(raw_dump) if not isinstance(raw_dump, int) else (raw_dump, None)
                    if isinstance(d_chat, int):
                        allowed_dump_ids.add(d_chat)
                except Exception:
                    pass

        def add_dest(c_chat, c_thread):
            if c_chat is None:
                return
            if isinstance(c_chat, str) and c_chat.lstrip("-").isdigit():
                c_chat = int(c_chat)
            try:
                numeric_chat = int(c_chat) if str(c_chat).lstrip("-").isdigit() else None
            except (TypeError, ValueError):
                numeric_chat = None
            if numeric_chat in auth_ids and numeric_chat not in allowed_dump_ids:
                LOGGER.info("Skipping AUTHORIZED_CHATS upload target %s", numeric_chat)
                return
            if (c_chat, c_thread) not in destinations:
                destinations.append((c_chat, c_thread))

        has_preset = getattr(self._listener, "has_preset_dump", False) and bool(getattr(self._listener, "key_dump_dests", None))

        if has_preset:
            for k_dest in self._listener.key_dump_dests:
                if k_dest:
                    k_chat, k_thread = parse_dest(k_dest) if not isinstance(k_dest, int) else (k_dest, None)
                    add_dest(k_chat, k_thread)
        else:
            leech_dest_found = False
            if self._listener.leech_dest:
                d_chat, d_thread = parse_dest(self._listener.leech_dest) if not isinstance(self._listener.leech_dest, int) else (self._listener.leech_dest, self._listener.leech_thread_id)
                add_dest(d_chat, d_thread)
                leech_dest_found = True

            if self._listener.up_dest:
                g_chat, g_thread = parse_dest(self._listener.up_dest) if not isinstance(self._listener.up_dest, int) else (self._listener.up_dest, self._listener.chat_thread_id)
                add_dest(g_chat, g_thread)
                leech_dest_found = True

            user_dump = self._listener.user_dict.get("LEECH_DUMP_CHAT")
            if user_dump:
                u_chat, u_thread = parse_dest(user_dump) if not isinstance(user_dump, int) else (user_dump, None)
                add_dest(u_chat, u_thread)
                leech_dest_found = True

            if not leech_dest_found:
                add_dest(self._listener.user_id, None)

        user_dump = self._listener.user_dict.get("LEECH_DUMP_CHAT")
        if user_dump:
            u_chat, u_thread = parse_dest(user_dump) if not isinstance(user_dump, int) else (user_dump, None)
            add_dest(u_chat, u_thread)

        if Config.LEECH_LOG_CHAT:
            l_chat, l_thread = parse_dest(Config.LEECH_LOG_CHAT) if not isinstance(Config.LEECH_LOG_CHAT, int) else (Config.LEECH_LOG_CHAT, None)
            add_dest(l_chat, l_thread)

        if Config.LEECH_DUMP_CHATS and isinstance(Config.LEECH_DUMP_CHATS, dict):
            for d_val in Config.LEECH_DUMP_CHATS.values():
                if d_val:
                    c_chat, c_thread = parse_dest(d_val) if not isinstance(d_val, int) else (d_val, None)
                    add_dest(c_chat, c_thread)

        for entry in self._upload_seq:
            if entry is None:
                continue
            copy_from_chat = entry["chat_id"]
            copy_from_msg = entry["msg_id"]
            copied_to_user_dm = False

            # A blocked/invalid configured destination must never prevent delivery
            # to the requesting user. AUTHORIZED_CHATS is access control only;
            # only explicitly configured dump chats are eligible destinations.
            for dest_chat, thread_id in destinations:
                if dest_chat == copy_from_chat:
                    continue
                try:
                    kw = {}
                    if thread_id:
                        kw["message_thread_id"] = thread_id
                    await _call_with_flood_retry(
                        TgClient.bot.copy_message,
                        chat_id=dest_chat,
                        from_chat_id=copy_from_chat,
                        message_id=copy_from_msg,
                        **kw
                    )
                    if str(dest_chat) == str(self._listener.user_id):
                        copied_to_user_dm = True
                except Exception as err:
                    if not self._listener.is_cancelled:
                        LOGGER.error(
                            f"Failed to copy output message to dump destination {dest_chat}: {err}"
                        )

            # Always provide a DM fallback when no dump destination worked.
            if not copied_to_user_dm and not self._listener.is_cancelled:
                try:
                    await _call_with_flood_retry(
                        TgClient.bot.copy_message,
                        chat_id=self._listener.user_id,
                        from_chat_id=copy_from_chat,
                        message_id=copy_from_msg,
                    )
                except Exception as err:
                    LOGGER.error(
                        "Could not deliver output to user DM %s. "
                        "The user may need to start the bot: %s",
                        self._listener.user_id,
                        err,
                    )

    async def _upload_file_task(self, file_, f_path, dirpath, user_session, seq_idx):
        up_path = None
        try:
            up_path, cap_mono = await self._prepare_file(file_, dirpath)
            sent = await self._upload_file(
                cap_mono, up_path, file_, seq_idx, user_session=user_session
            )
            if sent and not self._is_corrupted:
                if self._listener.is_super_chat or self._listener.up_dest:
                    if not self._is_private:
                        entry = self._upload_seq[seq_idx]
                        if entry["msg_id"] == sent.id:
                            self._msgs_dict[sent.link] = file_
            return sent
        except StopTransmission:
            return None
        except Exception as err:
            LOGGER.error(f"{err}. Path: {f_path}", exc_info=True)
            self._error = str(err)
            self._corrupted += 1
            return None
        finally:
            path_to_clean = up_path or f_path
            if not self._listener.is_cancelled and await aiopath.exists(path_to_clean):
                await remove(path_to_clean)

    async def upload(self):
        await self._user_settings()
        res = await self._msg_to_reply()
        if not res:
            return
        upload_tasks = []
        seq_idx = 0
        for dirpath, _, files in natsorted(await sync_to_async(walk, self._path)):
            if dirpath.strip().endswith("/yt-dlp-thumb"):
                continue
            if dirpath.strip().endswith("_mltbss"):
                await self._send_screenshots(dirpath, files)
                await rmtree(dirpath, ignore_errors=True)
                continue
            for file_ in natsorted(files):
                self._error = ""
                f_path = ospath.join(dirpath, file_)
                if not await aiopath.exists(f_path):
                    LOGGER.error(f"{f_path} not exists! Continue uploading!")
                    continue
                try:
                    f_size = await aiopath.getsize(f_path)
                    self._total_files += 1
                    if f_size == 0:
                        LOGGER.warning(f"{f_path} size is zero, skipping")
                        self._corrupted += 1
                        if not self._listener.is_cancelled:
                            await remove(f_path)
                        continue
                    if self._listener.is_cancelled:
                        return
                    if self._last_msg_in_group:
                        group_lists = [
                            x for v in self._media_dict.values() for x in v.keys()
                        ]
                        match = re_match(r".+(?=\.0*\d+$)|.+(?=\.part\d+\..+$)", f_path)
                        if not match or match and match.group(0) not in group_lists:
                            for key, value in list(self._media_dict.items()):
                                for subkey, msgs in list(value.items()):
                                    if len(msgs) > 1:
                                        await self._send_media_group(subkey, key, msgs)
                    if self._user_client is not None:
                        self._user_session = True
                    elif self._listener.transmission_mode == "both":
                        self._user_session = f_size > 2097152000
                    elif (
                        not self._user_session
                        and f_size > 2097152000
                        and TgClient.user is not None
                    ):
                        self._user_session = True
                    self._last_msg_in_group = False
                    self._upload_seq.append(None)
                    sent = await self._upload_file_task(
                        file_, f_path, dirpath, self._user_session, seq_idx
                    )
                    upload_tasks.append(sent)
                    seq_idx += 1
                    if self._listener.is_cancelled:
                        return
                except Exception as err:
                    LOGGER.error(f"{err}. Path: {f_path}", exc_info=True)
                    self._error = str(err)
                    self._corrupted += 1
                    if self._listener.is_cancelled:
                        return
        await sleep(1)
        for key, value in list(self._media_dict.items()):
            for subkey, msgs in list(value.items()):
                if len(msgs) > 1:
                    try:
                        await self._send_media_group(subkey, key, msgs)
                    except Exception as e:
                        LOGGER.info(
                            f"While sending media group at the end of task. Error: {e}"
                        )
        if self._upload_seq:
            src_chat = self._listener.message.chat
            await self._sequence_copies(src_chat)
            self._msgs_dict = {
                e["link"]: e["file_"] for e in self._upload_seq if e is not None
            }
        if self._listener.is_cancelled:
            return
        if self._total_files == 0:
            await self._listener.on_upload_error(
                "No files to upload. In case you have filled EXCLUDED_EXTENSIONS, then check if all files have those extensions or not."
            )
            return
        if self._total_files <= self._corrupted:
            await self._listener.on_upload_error(
                f"Files Corrupted or unable to upload. {self._error or 'Check logs!'}"
            )
            return
        LOGGER.info(f"Leech Completed: {self._listener.name}")
        await self._listener.on_upload_complete(
            None, self._msgs_dict, self._total_files, self._corrupted
        )
        return

    async def _upload_file(
        self, cap_mono, o_path, file_, seq_idx, force_document=False, user_session=False
    ):
        if self._sent_msg is None:
            LOGGER.error("Cannot upload: _sent_msg is None")
            await self._listener.on_upload_error(
                "Upload failed: Message not initialized"
            )
            return

        if not hasattr(self._sent_msg, "chat") or self._sent_msg.chat is None:
            LOGGER.error("Cannot upload: _sent_msg.chat is None")
            await self._listener.on_upload_error(
                "Upload failed: Invalid message object"
            )
            return

        if (
            self._thumb is not None
            and not await aiopath.exists(self._thumb)
            and self._thumb != "none"
        ):
            self._thumb = None
        self._is_corrupted = False
        try:
            if self._hu is None:
                self._hu = HypertgUpload(self)

            sent_msg = await self._hu.upload(
                file_path=o_path,
                cap_mono=cap_mono,
                reply_target=self._sent_msg,
                reply_to_message_id=self._sent_msg.id,
                force_document=force_document,
                user_session=user_session,
                user_thumb=self._thumb,
            )

            if self._listener.is_cancelled:
                return

            self._sent_msg = sent_msg

            self._upload_seq[seq_idx] = {
                "chat_id": sent_msg.chat.id,
                "msg_id": sent_msg.id,
                "link": sent_msg.link,
                "file_": file_,
            }
            self._msg_to_seq[(sent_msg.chat.id, sent_msg.id)] = seq_idx

            if (
                not self._listener.is_cancelled
                and self._media_group
                and (sent_msg.video or sent_msg.document)
            ):
                key = "documents" if sent_msg.document else "videos"
                if match := re_match(r".+(?=\.0*\d+$)|.+(?=\.part\d+\..+$)", o_path):
                    pname = match.group(0)
                    if pname in self._media_dict[key].keys():
                        self._media_dict[key][pname].append(
                            [sent_msg.chat.id, sent_msg.id]
                        )
                    else:
                        self._media_dict[key][pname] = [[sent_msg.chat.id, sent_msg.id]]
                    msgs = self._media_dict[key][pname]
                    if len(msgs) == 10:
                        await self._send_media_group(pname, key, msgs)
                    else:
                        self._last_msg_in_group = True

            return sent_msg
        except StopTransmission:
            raise
        except Exception as err:
            err_type = "RPCError: " if isinstance(err, RPCError) else ""
            LOGGER.error(f"{err_type}{err}. Path: {o_path}", exc_info=True)
            raise err

    @property
    def speed(self):
        try:
            return self._processed_bytes / (time() - self._start_time)
        except ZeroDivisionError:
            return 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    async def cancel_task(self):
        self._listener.is_cancelled = True
        LOGGER.info(f"Cancelling Upload: {self._listener.name}")
        await self._listener.on_upload_error("your upload has been stopped!")
