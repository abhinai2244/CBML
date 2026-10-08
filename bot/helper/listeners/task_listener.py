from asyncio import gather, sleep
from html import escape
from time import time
from mimetypes import guess_type
from contextlib import suppress
from os import path as ospath, walk
from pyrogram.enums import ButtonStyle

from aiofiles.os import listdir, remove, path as aiopath
from niquests import utils as rutils

from ... import (
    bot_loop,
    intervals,
    task_dict,
    task_dict_lock,
    LOGGER,
    non_queued_up,
    non_queued_dl,
    queued_up,
    queued_dl,
    queue_dict_lock,
    same_directory_lock,
    DOWNLOAD_DIR,
)
from ...modules.metadata import apply_metadata_title
from ..common import TaskConfig
from ..ext_utils.task_manager import clear_task_state
from ...core.tg_client import TgClient
from ...core.config_manager import Config
from ...core.torrent_manager import TorrentManager
from ..ext_utils.bot_utils import sync_to_async, parse_dest
from ..ext_utils.links_utils import encode_slink
from ..ext_utils.db_handler import database
from ..ext_utils.files_utils import (
    clean_download,
    clean_target,
    create_recursive_symlink,
    get_path_size,
    join_files,
    remove_excluded_files,
    move_and_merge,
)
from ..ext_utils.links_utils import is_gdrive_id
from ..ext_utils.status_utils import get_readable_file_size, get_readable_time
from ..ext_utils.task_manager import check_running_tasks, start_from_queued
from ..mirror_leech_utils.uphoster_utils.multi_upload import MultiUphosterUpload
from ..mirror_leech_utils.gdrive_utils.upload import GoogleDriveUpload
from ..mirror_leech_utils.rclone_utils.transfer import RcloneTransferHelper
from ..mirror_leech_utils.upload_utils.mega_upload import add_mega_upload
from ..mirror_leech_utils.status_utils.uphoster_status import UphosterStatus
from ..mirror_leech_utils.status_utils.gdrive_status import (
    GoogleDriveStatus,
)
from ..mirror_leech_utils.status_utils.queue_status import QueueStatus
from ..mirror_leech_utils.status_utils.rclone_status import RcloneStatus
from ..mirror_leech_utils.status_utils.telegram_status import TelegramStatus
from ..mirror_leech_utils.status_utils.yt_status import YtStatus
from ..mirror_leech_utils.upload_utils.telegram_uploader import TelegramUploader
from ..mirror_leech_utils.youtube_utils.youtube_upload import YouTubeUpload
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.message_utils import (
    delete_links,
    delete_message,
    delete_status,
    send_message,
    update_status_message,
)


class TaskListener(TaskConfig):
    def __init__(self):
        super().__init__()

    async def clean(self):
        with suppress(Exception):
            if st := intervals["status"]:
                for intvl in list(st.values()):
                    intvl.cancel()
            intervals["status"].clear()
            await gather(TorrentManager.aria2.purgeDownloadResult(), delete_status())

    def clear(self):
        self.subname = ""
        self.subsize = 0
        self.files_to_proceed = []
        self.proceed_count = 0
        self.progress = True

    async def remove_from_same_dir(self):
        async with task_dict_lock:
            if (
                self.folder_name
                and self.same_dir
                and self.mid in self.same_dir[self.folder_name]["tasks"]
            ):
                self.same_dir[self.folder_name]["tasks"].remove(self.mid)
                self.same_dir[self.folder_name]["total"] -= 1

    async def on_download_start(self):
        mode_name = "Leech" if self.is_leech else "Mirror"
        if self.bot_pm and self.is_super_chat:
            self.pm_msg = await send_message(
                self.user_id,
                f"<b>🚀 Task Started</b>\n\n<blockquote>• <b>Source Link:</b> <a href='{self.source_url}'>Click Here</a></blockquote>",
            )
        if Config.LINKS_LOG_ID:
            await send_message(
                Config.LINKS_LOG_ID,
                f"<b>🚀 {mode_name} Task Started</b>\n\n<blockquote>• <b>User:</b> {self.tag} (<code>#ID{self.user_id}</code>)\n• <b>Message Link:</b> <a href='{self.message.link}'>Click Here</a>\n• <b>Source Link:</b> <a href='{self.source_url}'>Click Here</a></blockquote>",
            )
        start_dump_msg = f"<b>🚀 {mode_name} Task Started</b>\n\n<blockquote>• <b>User:</b> {self.tag} (<code>#ID{self.user_id}</code>)\n• <b>Message Link:</b> <a href='{self.message.link}'>Click Here</a>\n• <b>Source Link:</b> <a href='{self.source_url}'>Click Here</a></blockquote>"

        start_dests = []
        if self.up_dest:
            c_chat, c_thread = parse_dest(self.up_dest) if not isinstance(self.up_dest, int) else (self.up_dest, self.chat_thread_id)
            if isinstance(c_chat, int) or (isinstance(c_chat, str) and (c_chat.startswith("@") or c_chat.lstrip("-").isdigit())):
                c_chat = int(c_chat) if isinstance(c_chat, str) and c_chat.lstrip("-").isdigit() else c_chat
                start_dests.append((c_chat, c_thread))

        if self.leech_dest:
            l_chat, l_thread = parse_dest(self.leech_dest) if not isinstance(self.leech_dest, int) else (self.leech_dest, self.leech_thread_id)
            if isinstance(l_chat, int) or (isinstance(l_chat, str) and (l_chat.startswith("@") or l_chat.lstrip("-").isdigit())):
                l_chat = int(l_chat) if isinstance(l_chat, str) and l_chat.lstrip("-").isdigit() else l_chat
                if (l_chat, l_thread) not in start_dests:
                    start_dests.append((l_chat, l_thread))

        if hasattr(self, "key_dump_dests") and self.key_dump_dests:
            for k_dest in self.key_dump_dests:
                if k_dest:
                    k_chat, k_thread = parse_dest(k_dest) if not isinstance(k_dest, int) else (k_dest, None)
                    if isinstance(k_chat, int) or (isinstance(k_chat, str) and (k_chat.startswith("@") or k_chat.lstrip("-").isdigit())):
                        k_chat = int(k_chat) if isinstance(k_chat, str) and k_chat.lstrip("-").isdigit() else k_chat
                        if (k_chat, k_thread) not in start_dests:
                            start_dests.append((k_chat, k_thread))

        universal_dump = self.user_dict.get("LEECH_DUMP_CHAT") or Config.LEECH_LOG_CHAT or ""
        if universal_dump:
            u_chat, u_thread = parse_dest(universal_dump) if not isinstance(universal_dump, int) else (universal_dump, None)
            if isinstance(u_chat, int) or (isinstance(u_chat, str) and (u_chat.startswith("@") or u_chat.lstrip("-").isdigit())):
                u_chat = int(u_chat) if isinstance(u_chat, str) and u_chat.lstrip("-").isdigit() else u_chat
                if (u_chat, u_thread) not in start_dests:
                    start_dests.append((u_chat, u_thread))

        if self.is_leech and Config.LEECH_DUMP_CHATS:
            for d_val in Config.LEECH_DUMP_CHATS.values():
                if d_val:
                    g_chat, g_thread = parse_dest(d_val) if not isinstance(d_val, int) else (d_val, None)
                    if isinstance(g_chat, int) or (isinstance(g_chat, str) and (g_chat.startswith("@") or g_chat.lstrip("-").isdigit())):
                        g_chat = int(g_chat) if isinstance(g_chat, str) and g_chat.lstrip("-").isdigit() else g_chat
                        if (g_chat, g_thread) not in start_dests:
                            start_dests.append((g_chat, g_thread))

        # Exclude task started notifications from dump chats
        if (
            self.is_super_chat
            and (Config.INC_TASK_NOTIFY or Config.INC_TASK_RESUME)
            and Config.DATABASE_URL
        ):
            await database.add_incomplete_task(
                self.message.chat.id,
                self.message.link,
                self.tag,
                self.message.text or "",
                self.user_id,
                self.message.reply_to_message.id
                if self.message.reply_to_message
                else 0,
                self.dump_msg_id,
            )

    async def on_download_complete(self):
        try:
            await self._on_download_complete()
        except Exception as err:
            LOGGER.error(f"Post-download failure: {err}", exc_info=True)
            await self.on_upload_error(f"Post-download failure: {err}")

    async def _on_download_complete(self):
        await sleep(2)
        if self.is_cancelled:
            return
        if self.dump_msg_id and Config.DATABASE_URL:
            await database.update_task_dump_msg(
                self.message.link, self.dump_chat, self.dump_msg_id
            )
        multi_links = False
        if (
            self.folder_name
            and self.same_dir
            and self.mid in self.same_dir[self.folder_name]["tasks"]
        ):
            async with same_directory_lock:
                while True:
                    async with task_dict_lock:
                        if self.mid not in self.same_dir[self.folder_name]["tasks"]:
                            return
                        if (
                            self.same_dir[self.folder_name]["total"] <= 1
                            or len(self.same_dir[self.folder_name]["tasks"]) > 1
                        ):
                            if self.same_dir[self.folder_name]["total"] > 1:
                                self.same_dir[self.folder_name]["tasks"].remove(
                                    self.mid
                                )
                                self.same_dir[self.folder_name]["total"] -= 1
                                spath = f"{self.dir}{self.folder_name}"
                                des_id = list(self.same_dir[self.folder_name]["tasks"])[
                                    0
                                ]
                                des_path = f"{DOWNLOAD_DIR}{des_id}{self.folder_name}"
                                LOGGER.info(f"Moving files from {self.mid} to {des_id}")
                                await move_and_merge(spath, des_path, self.mid)
                                multi_links = True
                            break
                    await sleep(1)
        async with task_dict_lock:
            if self.is_cancelled:
                return
            if self.mid not in task_dict:
                return
            download = task_dict[self.mid]
            self.name = download.name()
            gid = download.gid()
        LOGGER.info(f"Download completed: {self.name}")

        if not (self.is_torrent or self.is_qbit):
            self.seed = False

        if multi_links:
            self.seed = False
            await self.on_upload_error(
                f"{self.name} Downloaded!\n\nWaiting for other tasks to finish..."
            )
            return
        elif self.same_dir:
            self.seed = False

        if self.folder_name:
            self.name = self.folder_name.strip("/").split("/", 1)[0]

        if not await aiopath.exists(f"{self.dir}/{self.name}"):
            try:
                files = await listdir(self.dir)
                self.name = files[-1]
                if self.name == "yt-dlp-thumb":
                    self.name = files[0]
            except Exception as e:
                await self.on_upload_error(str(e))
                return

        dl_path = f"{self.dir}/{self.name}"
        self.size = await get_path_size(dl_path)
        self.is_file = await aiopath.isfile(dl_path)

        if self.seed:
            up_dir = self.up_dir = f"{self.dir}10000"
            up_path = f"{self.up_dir}/{self.name}"
            await create_recursive_symlink(self.dir, self.up_dir)
            LOGGER.info(f"Shortcut created: {dl_path} -> {up_path}")
        else:
            up_dir = self.dir
            up_path = dl_path

        await remove_excluded_files(self.up_dir or self.dir, self.excluded_extensions)

        if not Config.QUEUE_ALL:
            async with queue_dict_lock:
                if self.mid in non_queued_dl:
                    non_queued_dl.remove(self.mid)
            await start_from_queued()

        if self.join and not self.is_file:
            await join_files(up_path)

        if self.extract and not self.is_nzb:
            up_path = await self.proceed_extract(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if getattr(self, "track_manager", False):
            from ..ext_utils.track_manager import proceed_track_manager
            up_path = await proceed_track_manager(self, up_path, gid)
            if self.is_cancelled or not up_path:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if getattr(self, "manual_reorder", False) or getattr(self, "manual_rm_stream", False) or getattr(self, "reorder_aud", None) or getattr(self, "reorder_sub", None):
            up_path = await self.proceed_reorder(up_path, gid)
            if self.is_cancelled or not up_path:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        # Automatic Pipeline Order: Encode -> Compress -> Watermark -> Merge -> Track Manager
        from ..telegram_helper.filters import CustomFilters
        is_sudo_user = await CustomFilters.sudo("", self.message)

        enable_encode = Config.ENABLE_ENCODE and (self.user_dict.get("ENABLE_ENCODE") if "ENABLE_ENCODE" in self.user_dict else True) if is_sudo_user else False
        enable_compress = Config.ENABLE_COMPRESS and (self.user_dict.get("ENABLE_COMPRESS") if "ENABLE_COMPRESS" in self.user_dict else True) if is_sudo_user else False
        enable_watermark = Config.ENABLE_WATERMARK and (self.user_dict.get("ENABLE_WATERMARK") if "ENABLE_WATERMARK" in self.user_dict else True) if is_sudo_user else False

        if enable_encode:
            try:
                up_path = await self.proceed_encode(up_path, gid)
            except Exception as e:
                LOGGER.error(f"Encode processing error: {e}")
            if self.is_cancelled or not up_path:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if enable_compress:
            try:
                up_path = await self.proceed_compress_video(up_path, gid)
            except Exception as e:
                LOGGER.error(f"Compress processing error: {e}")
            if self.is_cancelled or not up_path:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if enable_watermark:
            try:
                up_path = await self.proceed_watermark(up_path, gid)
            except Exception as e:
                LOGGER.error(f"Watermark processing error: {e}")
            if self.is_cancelled or not up_path:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()
            await remove_excluded_files(up_dir, self.excluded_extensions)

        if getattr(self, "auto_merge", False) or getattr(self, "manual_merge", False):
            up_path = await self.proceed_merge(
                up_path, gid, getattr(self, "merge_custom_name", "")
            )
            if self.is_cancelled or not up_path:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

            self.clear()

        if getattr(self, "manual_trim", False):
            up_path = await self.proceed_trim(up_path, gid)
            if self.is_cancelled or not up_path:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if getattr(self, "manual_extract", False):
            up_path = await self.proceed_extract_content(up_path, gid)
            if self.is_cancelled or not up_path:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.ffmpeg_cmds:
            up_path = await self.proceed_ffmpeg(
                up_path,
                gid,
            )
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        has_meta_dicts = any(
            [
                (hasattr(self, "metadata_dict") and self.metadata_dict),
                (hasattr(self, "audio_metadata_dict") and self.audio_metadata_dict),
                (hasattr(self, "video_metadata_dict") and self.video_metadata_dict),
                (hasattr(self, "subtitle_metadata_dict") and self.subtitle_metadata_dict),
            ]
        )
        strip_meta = self.user_dict.get("STRIP_METADATA_ENABLE", False) or getattr(Config, "STRIP_METADATA_ENABLE", False)

        if has_meta_dicts or strip_meta:
            up_path = await apply_metadata_title(
                self,
                up_path,
                gid,
                getattr(self, "metadata_dict", {}),
                getattr(self, "audio_metadata_dict", {}),
                getattr(self, "video_metadata_dict", {}),
                getattr(self, "subtitle_metadata_dict", {}),
                strip_metadata=strip_meta,
            )
            if self.is_cancelled:
                return

            self.name = up_path.replace(f"{up_dir.rstrip('/')}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_path)
            self.clear()

        if self.is_leech and self.is_file:
            fname = ospath.basename(up_path)
            self.file_details["filename"] = fname
            self.file_details["mime_type"] = (guess_type(fname))[
                0
            ] or "application/octet-stream"

        up_path = await self.auto_rename(up_path)
        if self.is_cancelled:
            return
        self.is_file = await aiopath.isfile(up_path)
        self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]

        if self.name_swap:
            up_path = await self.substitute(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]

        if self.screen_shots:
            up_path = await self.generate_screenshots(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)

        if self.convert_audio or self.convert_video:
            up_path = await self.convert_media(
                up_path,
                gid,
            )
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.sample_video:
            up_path = await self.generate_sample_video(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.compress:
            up_path = await self.proceed_compress(
                up_path,
                gid,
            )
            self.is_file = await aiopath.isfile(up_path)
            if self.is_cancelled:
                return
            self.clear()

        self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
        self.size = await get_path_size(up_dir)

        if self.is_leech and not self.compress:
            await self.proceed_split(up_path, gid)
            if self.is_cancelled:
                return
            self.clear()

        self.subproc = None

        add_to_queue, event = await check_running_tasks(self, "up")
        await start_from_queued()
        if add_to_queue:
            LOGGER.info(f"Added to Queue/Upload: {self.name}")
            async with task_dict_lock:
                task_dict[self.mid] = QueueStatus(self, gid, "Up")
            await event.wait()
            if self.is_cancelled:
                return
            LOGGER.info(f"Start from Queued/Upload: {self.name}")

        self.size = await get_path_size(up_dir)

        if self.is_yt:
            LOGGER.info(f"Up to yt Name: {self.name}")
            yt = YouTubeUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = YtStatus(self, yt, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                sync_to_async(yt.upload),
            )
            del yt
        elif self.is_leech:
            LOGGER.info(f"Leech Name: {self.name}")
            if not self.thumb or not await aiopath.exists(self.thumb):
                user_thumb = self.user_dict.get("THUMBNAIL") or f"thumbnails/{self.user_id}.jpg"
                if await aiopath.exists(user_thumb):
                    self.thumb = user_thumb
            tg = TelegramUploader(self, up_dir)
            async with task_dict_lock:
                task_dict[self.mid] = TelegramStatus(
                    self,
                    tg,
                    gid,
                    "up",
                    "hul" if Config.USE_HYPER and TgClient.helper_bots else "",
                )
            user_seq = self.user_dict.get("LEECH_SEQUENCE", False)
            if user_seq:
                from asyncio import Lock
                if not hasattr(TaskListener, "_target_upload_locks"):
                    TaskListener._target_upload_locks = {}
                target_key = (
                    self.user_id,
                    self.up_dest or self.user_id,
                    getattr(self, "chat_thread_id", None),
                )
                if target_key not in TaskListener._target_upload_locks:
                    TaskListener._target_upload_locks[target_key] = Lock()
                u_lock = TaskListener._target_upload_locks[target_key]
                async with u_lock:
                    await gather(
                        update_status_message(self.message.chat.id),
                        tg.upload(),
                    )
            else:
                await gather(
                    update_status_message(self.message.chat.id),
                    tg.upload(),
                )
            del tg
        elif self.is_uphoster:
            LOGGER.info(f"Uphoster Upload Name: {self.name}")
            uphoster_service = self.user_dict.get("UPHOSTER_SERVICE", "gofile")
            services = uphoster_service.split(",")
            ddl = MultiUphosterUpload(
                self, up_path, services, self.folder_name.strip("/")
            )
            async with task_dict_lock:
                task_dict[self.mid] = UphosterStatus(self, ddl, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                ddl.upload(),
            )
            del ddl
        elif is_gdrive_id(self.up_dest):
            LOGGER.info(f"Gdrive Upload Name: {self.name}")
            drive = GoogleDriveUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = GoogleDriveStatus(self, drive, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                sync_to_async(drive.upload),
            )
            del drive
        elif self.up_dest == "mega:":
            LOGGER.info(f"Mega Upload Name: {self.name}")
            mega_email = self.user_dict.get("MEGA_EMAIL") or Config.MEGA_EMAIL or ""
            mega_password = self.user_dict.get("MEGA_PASSWORD") or Config.MEGA_PASSWORD or ""
            await add_mega_upload(self, up_path, mega_email, mega_password, gid)
        else:
            LOGGER.info(f"Rclone Upload Name: {self.name}")
            RCTransfer = RcloneTransferHelper(self)
            async with task_dict_lock:
                task_dict[self.mid] = RcloneStatus(self, RCTransfer, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                RCTransfer.upload(up_path),
            )
            del RCTransfer
        return

    async def on_upload_complete(
        self, link, files, folders, mime_type, rclone_path="", dir_id=""
    ):
        if (
            self.is_super_chat
            and (Config.INC_TASK_NOTIFY or Config.INC_TASK_RESUME)
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)
        msg = (
            f"<b>📦 {escape(self.name)}</b>\n\n"
            f"<blockquote>• <b>Task Size:</b> {get_readable_file_size(self.size)}\n"
            f"• <b>Time Elapsed:</b> {get_readable_time(time() - self.message.date.timestamp())}\n"
            f"• <b>In Mode:</b> {self.mode[0]}\n"
            f"• <b>Out Mode:</b> {self.mode[1]}</blockquote>"
        )
        LOGGER.info(f"Task Done: {self.name}")
        if self.is_leech:
            msg += f"\n<blockquote>• <b>Total Files:</b> {folders}\n"
            if mime_type != 0:
                msg += f"• <b>Corrupted Files:</b> {mime_type}\n"
            msg += f"• <b>User:</b> {self.tag}</blockquote>\n\n"

            targets = [self.user_id]

            for dm_target in targets:
                if not files:
                    await send_message(dm_target, msg)
                else:
                    full_msg = msg + "<b>📁 Files List:</b>\n"
                    fmsg = ""
                    for index, (link, name) in enumerate(files.items(), start=1):
                        fmsg += f"{index}. <a href='{link}'>{name}</a>"
                        if Config.MEDIA_STORE:
                            parts = link.split("/")[-2:]
                            if len(parts) == 2:
                                chat_id, msg_id = parts
                                if chat_id.isdigit():
                                    chat_id = f"-100{chat_id}"
                                flink = f"https://t.me/{TgClient.BNAME}?start={encode_slink('file' + chat_id + '&&' + msg_id)}"
                                fmsg += f"\n  ↳ <a href='{flink}'>Store Link</a> | <a href='https://t.me/share/url?url={flink}'>Share Link</a>"
                                from ...modules.stream import gen_stream_link

                                slinks = await gen_stream_link(chat_id, msg_id)
                                if slinks:
                                    fmsg += f"\n  ↳ <a href='{slinks[0]}'>Stream</a> | <a href='{slinks[1]}'>Download</a>"
                        fmsg += "\n"
                        if len(fmsg.encode() + full_msg.encode()) > 4000:
                            await send_message(dm_target, full_msg + fmsg)
                            await sleep(1)
                            fmsg = ""
                    if fmsg != "":
                        await send_message(dm_target, full_msg + fmsg)

            if self.is_super_chat and self.message.chat.id != self.user_id:
                group_msg = (
                    f"<b>📦 {escape(self.name)}</b>\n\n"
                    f"<blockquote>• <b>Task Size:</b> {get_readable_file_size(self.size)}\n"
                    f"• <b>Time Elapsed:</b> {get_readable_time(time() - self.message.date.timestamp())}\n"
                    f"• <b>Total Files:</b> {folders}\n"
                    f"• <b>User:</b> {self.tag}</blockquote>\n\n"
                    "<b>✅ Task Completed!</b>\n"
                    "<blockquote>Files/videos have been delivered to your Direct Messages (DM) / Dump.</blockquote>"
                )
                await send_message(self.message, group_msg)
        else:
            msg += f"\n<blockquote>• <b>Type:</b> {mime_type}"
            if mime_type == "Folder":
                msg += f"\n• <b>Subfolders:</b> {folders}"
                msg += f"\n• <b>Files:</b> {files}"
            msg += "</blockquote>"

            multi_link_msg = ""
            multi_links = []
            if isinstance(link, dict) and not self.is_yt:
                for service, result in link.items():
                    if "error" in result:
                        multi_link_msg += (
                            f"{service.capitalize()}: Error - {result['error']}\n"
                        )
                    elif result.get("link"):
                        multi_links.append(
                            (f"{service.capitalize()} Link", result["link"])
                        )
                multi_link_msg = multi_link_msg.strip()
                link = None

            if (
                link
                or rclone_path
                and Config.RCLONE_SERVE_URL
                and not self.private_link
                or multi_links
            ):
                buttons = ButtonMaker()
                if link and Config.SHOW_CLOUD_LINK:
                    if "mega.nz" in link:
                        btn_label = "🔗 Mega Link"
                    else:
                        btn_label = "☁️ Cloud Link"
                    buttons.url_button(btn_label, link, style=ButtonStyle.PRIMARY)
                elif multi_links:
                    for name, url in multi_links:
                        buttons.url_button(name, url)
                else:
                    msg += f"\n\nPath: <code>{rclone_path}</code>"
                if rclone_path and Config.RCLONE_SERVE_URL and not self.private_link:
                    remote, rpath = rclone_path.split(":", 1)
                    url_path = rutils.quote(f"{rpath}")
                    share_url = f"{Config.RCLONE_SERVE_URL}/{remote}/{url_path}"
                    if mime_type == "Folder":
                        share_url += "/"
                    buttons.url_button(
                        "🔗 Rclone Link", share_url, style=ButtonStyle.PRIMARY
                    )
                if not rclone_path and dir_id:
                    INDEX_URL = self.user_dict.get("INDEX_URL", "") or ""
                    if not INDEX_URL:
                        INDEX_URL = Config.INDEX_URL or ""
                    if INDEX_URL and self.name:
                        safe_name = rutils.quote(self.name.strip("/"))
                        share_url = f"{INDEX_URL}/{safe_name}"
                        if mime_type == "Folder":
                            share_url += "/"
                        buttons.url_button(
                            "⚡ Index Link", share_url, style=ButtonStyle.PRIMARY
                        )
                        if mime_type.startswith(("image", "video", "audio")):
                            share_urls = f"{share_url}?a=view"
                            buttons.url_button(
                                "🌐 View Link", share_urls, style=ButtonStyle.PRIMARY
                            )
                button = buttons.build_menu(2)
            else:
                if not multi_link_msg and rclone_path:
                    msg += f"\n<blockquote>• <b>Path:</b> <code>{rclone_path}</code></blockquote>"
                button = None
            msg += f"\n\n<b>User:</b> {self.tag}"
            group_msg = (
                msg + "\n\n<b>✅ Action Performed:</b>\n"
                "<blockquote>Cloud link(s) sent to User PM.</blockquote>"
            )

            if multi_link_msg:
                group_msg += multi_link_msg + "\n"
                msg += multi_link_msg + "\n"

            if self.bot_pm and self.is_super_chat:
                await send_message(self.user_id, msg, button)

            if hasattr(Config, "MIRROR_LOG_ID") and Config.MIRROR_LOG_ID:
                await send_message(Config.MIRROR_LOG_ID, msg, button)

            await send_message(self.message, group_msg, button)
        if self.seed:
            await clean_target(self.up_dir)
            async with queue_dict_lock:
                if self.mid in non_queued_up:
                    non_queued_up.remove(self.mid)
            await start_from_queued()
            return

        if self.pm_msg and not Config.DELETE_LINKS:
            await delete_message(self.pm_msg)

        await delete_links(self.message)

        await clean_download(self.dir)
        if hasattr(self, "task_key") and self.task_key:
            await clear_task_state(self.task_key)
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        async with queue_dict_lock:
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        if hasattr(self, "done_event") and self.done_event and not self.done_event.done():
            self.done_event.set_result(True)

        await start_from_queued()

    async def on_download_error(self, error, button=None, is_limit=False):
        if (
            not self.is_cancelled
            and not is_limit
            and "Requested format is not available" not in str(error)
            and getattr(self, "_retry_count", 0) < 2
        ):
            self._retry_count = getattr(self, "_retry_count", 0) + 1
            LOGGER.warning(
                f"Download failed for {self.name or self.link}: {error}. Retrying attempt {self._retry_count}/2 silently..."
            )
            await clean_download(self.dir)
            if self.up_dir:
                await clean_download(self.up_dir)
            await sleep(2)
            bot_loop.create_task(self.new_event())
            return

        if hasattr(self, "task_key") and self.task_key:
            await clear_task_state(self.task_key)
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        await self.remove_from_same_dir()
        if magnet_id := getattr(self, "_alldebrid_magnet_id", 0) or 0:
            from ..mirror_leech_utils.download_utils.alldebrid_resolver import (
                delete_magnet,
            )

            await delete_magnet(magnet_id)
            self._alldebrid_magnet_id = 0
        msg = (
            f"<b>⚠️ Task Size Limit Exceeded</b>\n\n"
            f"<blockquote>• <b>Task Size:</b> {get_readable_file_size(self.size)}\n"
            f"• <b>In Mode:</b> {self.mode[0]}\n"
            f"• <b>Out Mode:</b> {self.mode[1]}\n\n"
            f"{error}</blockquote>"
            if is_limit
            else f"<b>🛑 Task Download Stopped</b>\n\n"
            f"<blockquote>• <b>Reason:</b> {escape(str(error))}\n"
            f"• <b>Task Size:</b> {get_readable_file_size(self.size)}\n"
            f"• <b>Time Elapsed:</b> {get_readable_time(time() - self.message.date.timestamp())}\n"
            f"• <b>In Mode:</b> {self.mode[0]}\n"
            f"• <b>Out Mode:</b> {self.mode[1]}\n"
            f"• <b>User:</b> {self.tag}</blockquote>"
        )

        await send_message(self.message, msg, button)
        await delete_links(self.message)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        if (
            self.is_super_chat
            and (Config.INC_TASK_NOTIFY or Config.INC_TASK_RESUME)
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)

        async with queue_dict_lock:
            if self.mid in queued_dl:
                queued_dl[self.mid].set()
                del queued_dl[self.mid]
            if self.mid in queued_up:
                queued_up[self.mid].set()
                del queued_up[self.mid]
            if self.mid in non_queued_dl:
                non_queued_dl.remove(self.mid)
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        if hasattr(self, "done_event") and self.done_event and not self.done_event.done():
            self.done_event.set_result(False)

        await start_from_queued()
        await sleep(3)
        await clean_download(self.dir)
        if self.up_dir:
            await clean_download(self.up_dir)
        if self.thumb and await aiopath.exists(self.thumb):
            user_perm_thumb = self.user_dict.get("THUMBNAIL") or f"thumbnails/{self.user_id}.jpg"
            if self.thumb != user_perm_thumb and self.thumb != f"thumbnails/{self.user_id}.jpg":
                await remove(self.thumb)

    async def on_upload_error(self, error):
        if hasattr(self, "task_key") and self.task_key:
            await clear_task_state(self.task_key)
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        await send_message(self.message, f"{self.tag} {escape(str(error))}")
        await delete_links(self.message)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        if (
            self.is_super_chat
            and (Config.INC_TASK_NOTIFY or Config.INC_TASK_RESUME)
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)

        async with queue_dict_lock:
            if self.mid in queued_dl:
                queued_dl[self.mid].set()
                del queued_dl[self.mid]
            if self.mid in queued_up:
                queued_up[self.mid].set()
                del queued_up[self.mid]
            if self.mid in non_queued_dl:
                non_queued_dl.remove(self.mid)
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()
        await sleep(3)
        await clean_download(self.dir)
        if self.up_dir:
            await clean_download(self.up_dir)
        if self.thumb and await aiopath.exists(self.thumb):
            user_perm_thumb = self.user_dict.get("THUMBNAIL") or f"thumbnails/{self.user_id}.jpg"
            if self.thumb != user_perm_thumb and self.thumb != f"thumbnails/{self.user_id}.jpg":
                await remove(self.thumb)
