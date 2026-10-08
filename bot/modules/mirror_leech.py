from ast import literal_eval
from asyncio import sleep
from base64 import b64encode
from html import escape
from os import path as ospath
from re import match as re_match, search as re_search
from time import time

from aiofiles import open as aiopen
from aiofiles.os import makedirs, listdir, path as aiopath
from bot.core.config_manager import Config

from .. import DOWNLOAD_DIR, LOGGER, bot_loop, task_dict_lock, user_data
from ..core.seedr_client import SeedrClient
from ..helper.ext_utils.bot_utils import (
    COMMAND_USAGE,
    arg_parser,
    get_content_type,
    new_task,
    sync_to_async,
)
from ..helper.ext_utils.status_utils import (
    get_readable_file_size,
    get_readable_time,
)
from ..helper.ext_utils.exceptions import DirectDownloadLinkException
from ..helper.ext_utils.links_utils import (
    is_gdrive_id,
    is_gdrive_link,
    is_mega_link,
    is_magnet,
    is_rclone_path,
    is_telegram_link,
    is_url,
    is_youtube_link,
)
from ..helper.ext_utils.task_manager import pre_task_check
from ..helper.listeners.task_listener import TaskListener
from ..helper.mirror_leech_utils.download_utils.alldebrid_resolver import (
    alldebrid_resolve,
    alldebrid_resolve_magnet,
    alldebrid_resolve_torrent,
)
from ..helper.mirror_leech_utils.download_utils.aria2_download import (
    add_aria2_download,
)
from ..helper.mirror_leech_utils.download_utils.direct_downloader import (
    add_direct_download,
)
from ..helper.mirror_leech_utils.download_utils.direct_link_generator import (
    direct_link_generator,
)
from ..helper.mirror_leech_utils.download_utils.gd_download import add_gd_download
from ..helper.mirror_leech_utils.download_utils.jd_download import add_jd_download
from ..helper.mirror_leech_utils.download_utils.mega_download import add_mega_download
from ..helper.mirror_leech_utils.download_utils.nzb_downloader import add_nzb
from ..helper.mirror_leech_utils.download_utils.qbit_download import add_qb_torrent
from ..helper.mirror_leech_utils.download_utils.rclone_download import (
    add_rclone_download,
)
from ..helper.mirror_leech_utils.download_utils.seedr_download import (
    _build_contents,
    _delete_seedr_folder,
    _match_folder,
    add_seedr_download,
)
from ..helper.mirror_leech_utils.download_utils.telegram_download import (
    TelegramDownloadHelper,
)
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.ext_utils.files_utils import clean_download
from ..helper.telegram_helper.message_utils import (
    auto_delete_message,
    delete_links,
    delete_message,
    edit_message,
    get_tg_link_message,
    send_message,
)

ht_tasks = {}
ht_lock = bot_loop.create_task if False else None


class Mirror(TaskListener):
    def __init__(
        self,
        client,
        message,
        is_qbit=False,
        is_leech=False,
        is_jd=False,
        is_nzb=False,
        is_seedr=False,
        is_uphoster=False,
        same_dir=None,
        bulk=None,
        multi_tag=None,
        options="",
        **kwargs,
    ):
        if same_dir is None:
            same_dir = {}
        if bulk is None:
            bulk = []
        self.message = message
        self.client = client
        self.multi_tag = multi_tag
        self.options = options
        self.same_dir = same_dir
        self.bulk = bulk
        super().__init__()
        self.is_qbit = is_qbit
        self.is_leech = is_leech
        self.is_jd = is_jd
        self.is_nzb = is_nzb
        self.is_seedr = is_seedr
        self.is_uphoster = is_uphoster

    async def new_event(self):
        if self.is_leech:
            if Config.DISABLE_LEECH:
                await send_message(
                    self.message, "<blockquote>The Leech command is currently disabled.</blockquote>"
                )
                return
        elif Config.DISABLE_MIRROR and not self.is_uphoster:
            await send_message(
                self.message, "<blockquote>The Mirror command is currently disabled.</blockquote>"
            )
            return
        msg_text = self.message.text or self.message.caption or ""
        text = msg_text.split("\n")
        input_list = text[0].split(" ") if text[0] else []

        check_msg, check_button = await pre_task_check(self.message)
        if check_msg:
            await delete_links(self.message)
            await auto_delete_message(
                await send_message(self.message, check_msg, check_button)
            )
            return

        args = {
            "-doc": False,
            "-med": False,
            "-d": False,
            "-j": False,
            "-s": False,
            "-b": False,
            "-e": False,
            "-z": False,
            "-sv": False,
            "-ss": False,
            "-f": False,
            "-fd": False,
            "-fu": False,
            "-hl": False,
            "-bt": False,
            "-ut": False,
            "-ad": False,
            "-yt": False,
            "-seedr": False,
            "-ht": False,
            "-trackmanager": False,
            "-tr": False,
            "-track": False,
            "-tm": False,
            "-i": 0,
            "-sp": 0,
            "link": "",
            "-n": "",
            "-m": "",
            "-meta": "",
            "-up": "",
            "-ud": "",
            "-gc": "",
            "-rcf": "",
            "-au": "",
            "-ap": "",
            "-h": "",
            "-t": "",
            "-ca": "",
            "-cv": "",
            "-ns": "",
            "-tl": "",
            "-ff": set(),
        }

        if input_list and input_list[0].startswith("/"):
            arg_parser(input_list[1:], args)
        else:
            arg_parser(input_list, args)

        if Config.DISABLE_BULK and args.get("-b", False):
            await send_message(self.message, "<blockquote>Bulk downloads are currently disabled.</blockquote>")
            return

        if Config.DISABLE_MULTI and int(args.get("-i", 1)) > 1:
            await send_message(
                self.message,
                "<blockquote>Multi-downloads are currently disabled.</blockquote>",
            )
            return

        if Config.DISABLE_SEED and args.get("-d", False):
            await send_message(
                self.message,
                "<blockquote>Seeding is currently disabled.</blockquote>",
            )
            return

        if Config.DISABLE_FF_MODE and args.get("-ff"):
            await send_message(self.message, "<blockquote>FFmpeg commands are currently disabled.</blockquote>")
            return

        self.select = args["-s"]
        self.seed = args["-d"]
        self.name = args["-n"]
        self.up_dest = args["-up"]
        self.dump_dest = args["-ud"]
        self.category = args["-gc"]
        self.rc_flags = args["-rcf"]
        self.link = args["link"]
        self.compress = args["-z"]
        self.extract = args["-e"]
        self.join = args["-j"]
        self.thumb = args["-t"]
        self.split_size = args["-sp"]
        self.sample_video = args["-sv"]
        self.screen_shots = args["-ss"]
        self.force_run = args["-f"]
        self.force_download = args["-fd"]
        self.force_upload = args["-fu"]
        self.convert_audio = args["-ca"]
        self.convert_video = args["-cv"]
        self.name_swap = args["-ns"]
        self.hybrid_leech = args["-hl"]
        self.thumbnail_layout = args["-tl"]
        self.as_doc = args["-doc"]
        self.as_med = args["-med"]
        self.folder_name = f"/{args['-m']}".rstrip("/") if len(args["-m"]) > 0 else ""
        if args["-m"] or "-m" in self.options:
            self.manual_merge = True
            m_val = args["-m"]
            self.merge_custom_name = m_val if isinstance(m_val, str) else ""
        self.bot_trans = args["-bt"]
        self.user_trans = args["-ut"]
        self.is_alldebrid = args["-ad"]
        self.is_seedr = args["-seedr"] or self.is_seedr
        self.is_yt = args["-yt"]

        user_auto_merge = self.user_dict.get("AUTO_MERGE", False) or (
            "AUTO_MERGE" not in self.user_dict and getattr(Config, "AUTO_MERGE", False)
        )
        if user_auto_merge:
            self.auto_merge = True
            self.merge_mode = self.user_dict.get("AUTO_MERGE_MODE", "normal")


        self.ht_flag = bool(args["-ht"] or "-ht" in self.options)
        self.track_manager = bool(
            args["-trackmanager"]
            or args["-tr"]
            or args["-track"]
            or args["-tm"]
            or any(
                f in self.options
                for f in ("-trackmanager", "-tr", "-track", "-tm")
            )
        )

        from ..helper.ext_utils.task_manager import get_task_key
        task_source = self.link or (self.message.reply_to_message.text if self.message.reply_to_message and self.message.reply_to_message.text else "") or self.name
        self.task_key = get_task_key(task_source, self.user_id)

        if self.is_seedr and not await seedr_guard(self.message, self.user_id):
            return

        self.metadata_dict = self.default_metadata_dict.copy()
        self.audio_metadata_dict = self.audio_metadata_dict.copy()
        self.video_metadata_dict = self.video_metadata_dict.copy()
        self.subtitle_metadata_dict = self.subtitle_metadata_dict.copy()
        if args["-meta"]:
            meta = self.metadata_processor.parse_string(args["-meta"])
            self.metadata_dict = self.metadata_processor.merge_dicts(
                self.metadata_dict, meta
            )

        headers = args["-h"]
        is_bulk = args["-b"]

        bulk_start = 0
        bulk_end = 0
        ratio = None
        seed_time = None
        reply_to = None
        file_ = None
        session = ""

        try:
            self.multi = int(args["-i"])
        except Exception:
            self.multi = 0

        try:
            if args["-ff"]:
                if isinstance(args["-ff"], (set, list, tuple)):
                    self.ffmpeg_cmds = args["-ff"]
                else:
                    raw_val = str(args["-ff"]).strip()
                    if raw_val.startswith(("[", "{", "(")):
                        value = literal_eval(raw_val)
                        if not isinstance(value, (dict, set, list, tuple)):
                            raise ValueError("ffmpeg_cmds must be a dict/set/list/tuple")
                        self.ffmpeg_cmds = value
                    else:
                        self.ffmpeg_cmds = raw_val
        except Exception as e:
            self.ffmpeg_cmds = None
            LOGGER.error(e)

        if not isinstance(self.seed, bool):
            dargs = self.seed.split(":")
            ratio = dargs[0] or None
            if len(dargs) == 2:
                seed_time = dargs[1] or None
            self.seed = True

        if not isinstance(is_bulk, bool):
            dargs = is_bulk.split(":")
            bulk_start = dargs[0] or 0
            if len(dargs) == 2:
                bulk_end = dargs[1] or 0
            is_bulk = True

        if not is_bulk:
            if self.multi > 0:
                if self.folder_name:
                    async with task_dict_lock:
                        if self.folder_name in self.same_dir:
                            self.same_dir[self.folder_name]["tasks"].add(self.mid)
                            for fd_name in self.same_dir:
                                if fd_name != self.folder_name:
                                    self.same_dir[fd_name]["total"] -= 1
                        elif self.same_dir:
                            self.same_dir[self.folder_name] = {
                                "total": self.multi,
                                "tasks": {self.mid},
                            }
                            for fd_name in self.same_dir:
                                if fd_name != self.folder_name:
                                    self.same_dir[fd_name]["total"] -= 1
                        else:
                            self.same_dir = {
                                self.folder_name: {
                                    "total": self.multi,
                                    "tasks": {self.mid},
                                }
                            }
                elif self.same_dir:
                    async with task_dict_lock:
                        for fd_name in self.same_dir:
                            self.same_dir[fd_name]["total"] -= 1
        else:
            await self.init_bulk(input_list, bulk_start, bulk_end, Mirror)
            return

        if len(self.bulk) != 0:
            del self.bulk[0]

        await self.run_multi(input_list, Mirror)

        await self.get_tag(text)

        if self.ht_flag:
            user_id = self.user_id
            saved_ht = None
            if getattr(self, "same_dir", None) and "_ht_config" in self.same_dir:
                saved_ht = self.same_dir["_ht_config"]
            elif self.multi_tag and self.multi_tag in ht_tasks and "saved_ht" in ht_tasks[self.multi_tag]:
                saved_ht = ht_tasks[self.multi_tag]["saved_ht"]

            if not saved_ht:
                event_done = bot_loop.create_future()
                ht_tasks[self.mid] = {
                    "merge": self.auto_merge or self.manual_merge,
                    "merge_mode": getattr(self, "merge_mode", self.user_dict.get("AUTO_MERGE_MODE", "normal")),
                    "rm_stream": False,
                    "reorder": False,
                    "reorder_aud": [],
                    "reorder_sub": [],
                    "trim": False,
                    "trim_range": "",
                    "extract": False,
                    "extract_types": [],
                    "user_id": user_id,
                    "future": event_done,
                }

                def build_ht_menu(mid):
                    t_info = ht_tasks.get(mid, {})
                    m_on = "✓ ON" if t_info.get("merge") else "OFF"
                    m_mode = t_info.get("merge_mode", "normal")
                    tr_on = "✓ ON" if t_info.get("trim") else "OFF"
                    ex_on = "✓ ON" if t_info.get("extract") else "OFF"

                    buttons = ButtonMaker()
                    buttons.data_button(f"Merge: {m_on}", f"htmerge merge {mid}", position="header")
                    if t_info.get("merge"):
                        n_st = "✓ " if m_mode == "normal" else ""
                        a_st = "✓ " if m_mode == "advanced" else ""
                        buttons.data_button(f"{n_st}Normal Mode", f"htmerge setmode {mid} normal")
                        buttons.data_button(f"{a_st}Advanced Mode", f"htmerge setmode {mid} advanced")

                    buttons.data_button(f"Trim: {tr_on}", f"htmerge trim {mid}")
                    buttons.data_button(f"Extract: {ex_on}", f"htmerge extract {mid}")
                    buttons.data_button("Done", f"htmerge done {mid}", position="footer")
                    return buttons

                initial_merge = "✓ ON (Normal Mode)" if self.auto_merge or self.manual_merge else "OFF"
                prompt_msg = await send_message(
                    self.message,
                    f"<b>Task Received with -ht flag.</b>\nChoose pre-upload options:\n\n• <b>Merge:</b> {initial_merge}\n• <b>Trim:</b> OFF\n• <b>Extract:</b> OFF",
                    build_ht_menu(self.mid).build_menu(2),
                )
                try:
                    await event_done
                except Exception:
                    pass

                saved_ht = ht_tasks.get(self.mid, {})
                if getattr(self, "same_dir", None) is not None:
                    self.same_dir["_ht_config"] = saved_ht.copy()
                if self.multi_tag:
                    if self.multi_tag not in ht_tasks:
                        ht_tasks[self.multi_tag] = {}
                    ht_tasks[self.multi_tag]["saved_ht"] = saved_ht.copy()

                await delete_message(prompt_msg)

            ht_merge = saved_ht.get("merge", False)
            self.manual_merge = ht_merge
            self.auto_merge = ht_merge
            if ht_merge:
                self.merge_mode = saved_ht.get("merge_mode", getattr(self, "merge_mode", "normal"))
            self.manual_rm_stream = saved_ht.get("rm_stream", False)
            self.manual_reorder = saved_ht.get("reorder", False)
            self.reorder_aud = saved_ht.get("reorder_aud", [])
            self.reorder_sub = saved_ht.get("reorder_sub", [])
            self.aud_select = saved_ht.get("aud_select", None)
            self.sub_select = saved_ht.get("sub_select", None)
            self.aud_order = saved_ht.get("aud_order", None)
            self.sub_order = saved_ht.get("sub_order", None)
            self.manual_trim = saved_ht.get("trim", False)
            self.trim_range = saved_ht.get("trim_range", "")
            self.manual_extract = saved_ht.get("extract", False)
            self.extract_types = saved_ht.get("extract_types", [])

            ht_tasks.pop(self.mid, None)

        path = f"{DOWNLOAD_DIR}{self.mid}{self.folder_name}"

        if not self.link and (reply_to := self.message.reply_to_message):
            if reply_to.text:
                self.link = reply_to.text.split("\n", 1)[0].strip()
        if is_telegram_link(self.link):
            try:
                user_range_mode = self.user_dict.get("RANGE_LINK_MODE") or getattr(Config, "RANGE_LINK_MODE", "normal")
                reply_to, session = await get_tg_link_message(self.link, range_mode=user_range_mode, user_id=self.user_id, user_dict=self.user_dict)
            except Exception as e:
                await send_message(self.message, f"ERROR: {e}")
                await self.remove_from_same_dir()
                await delete_links(self.message)
                return

        if isinstance(reply_to, list) and len(reply_to) > 0 and isinstance(reply_to[0], str):
            await self._process_range_each_sequentially(reply_to)
            return

        if not reply_to:
            reply_to = self.message

        if isinstance(reply_to, list):
            file_ = "tg_range"
            self.file_details = {"caption": reply_to[0].caption if reply_to and hasattr(reply_to[0], "caption") else ""}
        elif reply_to:
            file_ = (
                reply_to.document
                or reply_to.photo
                or reply_to.video
                or reply_to.audio
                or reply_to.voice
                or reply_to.video_note
                or reply_to.sticker
                or reply_to.animation
                or None
            )
            self.file_details = {"caption": reply_to.caption}

            if file_ is None:
                if reply_text := reply_to.text:
                    if not self.link:
                        self.link = reply_text.split("\n", 1)[0].strip()
                else:
                    reply_to = None
            elif reply_to.document and (
                file_.mime_type == "application/x-bittorrent"
                or file_.file_name.endswith((".torrent", ".dlc", ".nzb"))
            ):
                self.link = await reply_to.download()
                file_ = None

        if (
            not self.link
            and file_ is None
            or is_telegram_link(self.link)
            and reply_to is None
            or file_ is None
            and not is_url(self.link)
            and not is_magnet(self.link)
            and not await aiopath.exists(self.link)
            and not is_rclone_path(self.link)
            and not is_gdrive_id(self.link)
            and not is_gdrive_link(self.link)
            and not is_mega_link(self.link)
        ):
            await send_message(
                self.message, COMMAND_USAGE["mirror"][0], COMMAND_USAGE["mirror"][1]
            )
            await self.remove_from_same_dir()
            await delete_links(self.message)
            return

        if len(self.link) > 0:
            LOGGER.info(self.link)

        try:
            await self.before_start()
        except Exception as e:
            await send_message(self.message, e)
            await self.remove_from_same_dir()
            await delete_links(self.message)
            return

        if self.is_leech and (not self.thumb or not await aiopath.exists(self.thumb)):
            from ..helper.ext_utils.media_utils import create_thumb
            if self.message.photo or (self.message.document and self.message.document.mime_type and self.message.document.mime_type.startswith("image/")):
                self.thumb = await create_thumb(self.message, self.user_id)
            elif self.message.reply_to_message and (
                self.message.reply_to_message.photo
                or (
                    self.message.reply_to_message.document
                    and self.message.reply_to_message.document.mime_type
                    and self.message.reply_to_message.document.mime_type.startswith("image/")
                )
            ):
                self.thumb = await create_thumb(self.message.reply_to_message, self.user_id)
            elif reply_to and (
                reply_to.photo
                or (
                    reply_to.document
                    and reply_to.document.mime_type
                    and reply_to.document.mime_type.startswith("image/")
                )
            ):
                self.thumb = await create_thumb(reply_to, self.user_id)

        if (is_youtube_link(self.link) or self.is_yt) and not (
            self.is_seedr or self.is_jd or self.is_nzb or self.is_alldebrid
        ):
            from .ytdlp import YtDlp
            bot_loop.create_task(
                YtDlp(
                    self.client,
                    self.message,
                    is_leech=self.is_leech,
                    same_dir=self.same_dir,
                    bulk=self.bulk,
                    multi_tag=self.multi_tag,
                    options=self.options,
                ).new_event()
            )
            return

        self._set_mode_engine()

        if self.is_alldebrid and (
            is_magnet(self.link) or self.link.endswith(".torrent")
        ):
            try:
                if is_magnet(self.link):
                    LOGGER.info("AllDebrid magnet route")
                    resolved = await alldebrid_resolve_magnet(
                        self.link,
                        is_cancelled=lambda: self.is_cancelled,
                    )
                else:
                    LOGGER.info(f"AllDebrid torrent file route: {self.link}")
                    async with aiopen(self.link, "rb") as fh:
                        torrent_bytes = await fh.read()
                    resolved = await alldebrid_resolve_torrent(
                        torrent_bytes,
                        ospath.basename(self.link),
                        is_cancelled=lambda: self.is_cancelled,
                    )
            except DirectDownloadLinkException as e:
                e = str(e)
                LOGGER.info(e)
                if e.startswith("ERROR:"):
                    await send_message(self.message, e)
                    await self.remove_from_same_dir()
                    await delete_links(self.message)
                    return
                resolved = None
            except Exception as e:
                await send_message(self.message, e)
                await self.remove_from_same_dir()
                await delete_links(self.message)
                return
            if isinstance(resolved, dict):
                self._alldebrid_magnet_id = resolved.get("magnet_id", 0)
                self.link = resolved
                self.is_jd = False
                self.is_qbit = False

        if (
            isinstance(self.link, str)
            and not self.is_jd
            and not self.is_nzb
            and not self.is_seedr
            and not self.is_qbit
            and not is_magnet(self.link)
            and not is_rclone_path(self.link)
            and not is_gdrive_link(self.link)
            and not self.link.endswith(".torrent")
            and file_ is None
            and not is_gdrive_id(self.link)
            and not is_mega_link(self.link)
        ):
            if self.is_alldebrid:
                try:
                    self.link = await alldebrid_resolve(self.link)
                    if isinstance(self.link, str):
                        LOGGER.info(f"AllDebrid link: {self.link}")
                except DirectDownloadLinkException as e:
                    e = str(e)
                    LOGGER.info(e)
                    if e.startswith("ERROR:"):
                        await send_message(self.message, e)
                        await self.remove_from_same_dir()
                        await delete_links(self.message)
                        return
                except Exception as e:
                    await send_message(self.message, e)
                    await self.remove_from_same_dir()
                    await delete_links(self.message)
                    return

            if isinstance(self.link, str) and (
                (content_type := await get_content_type(self.link)) is None
                or re_match(r"text/html|text/plain", content_type)
            ):
                try:
                    self.link = await sync_to_async(direct_link_generator, self.link)
                    if isinstance(self.link, tuple):
                        self.link, headers = self.link
                    elif isinstance(self.link, str):
                        LOGGER.info(f"Generated link: {self.link}")
                except DirectDownloadLinkException as e:
                    e = str(e)
                    if "This link requires a password!" not in e:
                        LOGGER.info(e)
                    if e.startswith("ERROR:"):
                        await send_message(self.message, e)
                        await self.remove_from_same_dir()
                        await delete_links(self.message)
                        return
                except Exception as e:
                    await send_message(self.message, e)
                    await self.remove_from_same_dir()
                    await delete_links(self.message)
                    return

        if isinstance(reply_to, list):
            await TelegramDownloadHelper(self).add_range_download(
                reply_to, f"{path}/", session
            )
        elif file_ is not None:
            await TelegramDownloadHelper(self).add_download(
                reply_to, f"{path}/", session
            )
        elif isinstance(self.link, dict):
            await add_direct_download(self, path)
        elif self.is_jd:
            await add_jd_download(self, path)
        elif self.is_qbit:
            await add_qb_torrent(self, path, ratio, seed_time)
        elif self.is_nzb:
            await add_nzb(self, path)
        elif self.is_seedr:
            await add_seedr_download(self, path)
        elif is_rclone_path(self.link):
            await add_rclone_download(self, f"{path}/")
        elif is_gdrive_link(self.link) or is_gdrive_id(self.link):
            await add_gd_download(self, path)
        elif is_mega_link(self.link):
            await add_mega_download(self, f"{path}/")
        else:
            ussr = args["-au"]
            pssw = args["-ap"]
            if ussr or pssw:
                auth = f"{ussr}:{pssw}"
                headers += (
                    f" authorization: Basic {b64encode(auth.encode()).decode('ascii')}"
                )
            await add_aria2_download(self, path, headers, ratio, seed_time)

    async def resume_range_task(self, range_data):
        range_id = range_data["range_id"]
        start_idx = range_data.get("current_idx", 1)
        range_links = range_data.get("links", [])
        await self._process_range_each_sequentially(range_links, start_idx=start_idx, range_id=range_id)

    async def _process_range_each_sequentially(self, range_links, start_idx=1, range_id=None):
        from bot import active_range_tasks
        from ..helper.ext_utils.range_utils import save_range_tasks_to_file

        total_items = len(range_links)
        if not range_id:
            range_id = f"rl_{self.mid}"

        listener_dict = {
            "mid": self.mid,
            "user_id": self.user_id,
            "tag": self.tag,
            "is_qbit": self.is_qbit,
            "is_leech": self.is_leech,
            "is_jd": self.is_jd,
            "is_nzb": self.is_nzb,
            "is_seedr": self.is_seedr,
            "is_uphoster": self.is_uphoster,
            "options": getattr(self, "options", {}),
            "as_doc": self.as_doc,
            "as_med": self.as_med,
            "compress": self.compress,
            "extract": self.extract,
            "name": self.name,
            "folder_name": self.folder_name,
            "manual_merge": self.manual_merge,
            "auto_merge": self.auto_merge,
            "merge_custom_name": getattr(self, "merge_custom_name", ""),
            "merge_mode": getattr(self, "merge_mode", "normal"),
            "up_dest": self.up_dest,
            "dump_dest": self.dump_dest,
            "category": self.category,
            "rc_flags": self.rc_flags,
            "thumb": self.thumb,
            "split_size": self.split_size,
            "sample_video": self.sample_video,
            "screen_shots": self.screen_shots,
            "convert_audio": self.convert_audio,
            "convert_video": self.convert_video,
            "name_swap": self.name_swap,
            "hybrid_leech": self.hybrid_leech,
            "thumbnail_layout": self.thumbnail_layout,
            "ffmpeg_cmds": self.ffmpeg_cmds,
            "ht_flag": self.ht_flag,
            "track_manager": getattr(self, "track_manager", False),
            "manual_rm_stream": getattr(self, "manual_rm_stream", False),
            "manual_reorder": getattr(self, "manual_reorder", False),
            "reorder_aud": getattr(self, "reorder_aud", []),
            "reorder_sub": getattr(self, "reorder_sub", []),
            "aud_select": getattr(self, "aud_select", None),
            "sub_select": getattr(self, "sub_select", None),
            "aud_order": getattr(self, "aud_order", None),
            "sub_order": getattr(self, "sub_order", None),
            "manual_trim": getattr(self, "manual_trim", False),
            "trim_range": getattr(self, "trim_range", ""),
            "manual_extract": getattr(self, "manual_extract", False),
            "extract_types": getattr(self, "extract_types", []),
            "metadata_dict": getattr(self, "metadata_dict", {}),
            "audio_metadata_dict": getattr(self, "audio_metadata_dict", {}),
            "video_metadata_dict": getattr(self, "video_metadata_dict", {}),
            "subtitle_metadata_dict": getattr(self, "subtitle_metadata_dict", {}),
            "chat_id": self.message.chat.id if self.message and getattr(self.message, "chat", None) else None,
            "message_id": getattr(self.message, "id", None),
        }

        range_info = {
            "range_id": range_id,
            "mid": self.mid,
            "user_id": self.user_id,
            "tag": self.tag,
            "total_links": total_items,
            "current_idx": start_idx,
            "current_sub_task": None,
            "is_cancelled": False,
            "links": range_links,
            "listener_dict": listener_dict,
        }
        active_range_tasks[range_id] = range_info
        await save_range_tasks_to_file()
        LOGGER.info(f"Processing range link in 'each' mode: {total_items} items continuously (starting at index {start_idx}).")

        try:
            for idx in range(start_idx, total_items + 1):
                item_url = range_links[idx - 1]
                if range_info.get("is_cancelled") or self.is_cancelled:
                    LOGGER.info("Sequential range link processing cancelled by user.")
                    break

                range_info["current_idx"] = idx
                await save_range_tasks_to_file()

                try:
                    sub_msg, sub_session = await get_tg_link_message(item_url, range_mode="normal", user_id=self.user_id, user_dict=self.user_dict)
                    tg_message = sub_msg[0] if isinstance(sub_msg, list) and sub_msg else sub_msg

                    if not tg_message:
                        continue

                    sub_task = Mirror(
                        client=self.client,
                        message=self.message,
                        is_qbit=self.is_qbit,
                        is_leech=self.is_leech,
                        is_jd=self.is_jd,
                        is_nzb=self.is_nzb,
                        is_seedr=self.is_seedr,
                        is_uphoster=self.is_uphoster,
                        options=self.options,
                    )
                    sub_task.link = item_url
                    sub_task.as_doc = self.as_doc
                    sub_task.as_med = self.as_med
                    sub_task.compress = self.compress
                    sub_task.extract = self.extract
                    sub_task.name = self.name
                    sub_task.folder_name = self.folder_name
                    sub_task.manual_merge = self.manual_merge
                    sub_task.auto_merge = self.auto_merge
                    sub_task.merge_custom_name = getattr(self, "merge_custom_name", "")
                    sub_task.merge_mode = getattr(self, "merge_mode", "normal")
                    sub_task.up_dest = self.up_dest
                    sub_task.dump_dest = self.dump_dest
                    sub_task.category = self.category
                    sub_task.rc_flags = self.rc_flags
                    sub_task.thumb = self.thumb
                    sub_task.split_size = self.split_size
                    sub_task.sample_video = self.sample_video
                    sub_task.screen_shots = self.screen_shots
                    sub_task.convert_audio = self.convert_audio
                    sub_task.convert_video = self.convert_video
                    sub_task.name_swap = self.name_swap
                    sub_task.hybrid_leech = self.hybrid_leech
                    sub_task.thumbnail_layout = self.thumbnail_layout
                    sub_task.ffmpeg_cmds = self.ffmpeg_cmds
                    sub_task.ht_flag = self.ht_flag
                    sub_task.track_manager = getattr(self, "track_manager", False)
                    sub_task.manual_rm_stream = getattr(self, "manual_rm_stream", False)
                    sub_task.manual_reorder = getattr(self, "manual_reorder", False)
                    sub_task.reorder_aud = getattr(self, "reorder_aud", [])
                    sub_task.reorder_sub = getattr(self, "reorder_sub", [])
                    sub_task.aud_select = getattr(self, "aud_select", None)
                    sub_task.sub_select = getattr(self, "sub_select", None)
                    sub_task.aud_order = getattr(self, "aud_order", None)
                    sub_task.sub_order = getattr(self, "sub_order", None)
                    sub_task.manual_trim = getattr(self, "manual_trim", False)
                    sub_task.trim_range = getattr(self, "trim_range", "")
                    sub_task.manual_extract = getattr(self, "manual_extract", False)
                    sub_task.extract_types = getattr(self, "extract_types", [])
                    sub_task.metadata_dict = getattr(self, "metadata_dict", {}).copy()
                    sub_task.audio_metadata_dict = getattr(self, "audio_metadata_dict", {}).copy()
                    sub_task.video_metadata_dict = getattr(self, "video_metadata_dict", {}).copy()
                    sub_task.subtitle_metadata_dict = getattr(self, "subtitle_metadata_dict", {}).copy()

                    range_info["current_sub_task"] = sub_task
                    sub_task.done_event = bot_loop.create_future()
                    try:
                        await sub_task._run_single_range_item(tg_message, item_url, sub_session)
                        from asyncio import wait_for
                        await wait_for(sub_task.done_event, timeout=7200)
                    except Exception as te:
                        LOGGER.warning(f"Range task timeout or error for {item_url}: {te}")
                    finally:
                        if hasattr(sub_task, "done_event") and not sub_task.done_event.done():
                            sub_task.done_event.set_result(False)
                except Exception as e:
                    LOGGER.error(f"Error processing range item {idx}/{total_items} ({item_url}): {e}")
                    continue

                await sleep(1)
        finally:
            active_range_tasks.pop(range_id, None)
            await save_range_tasks_to_file()

    async def _run_single_range_item(self, reply_to, item_url, session):
        path = f"{DOWNLOAD_DIR}{self.mid}{self.folder_name}"
        self.link = item_url
        await self.before_start()
        self._set_mode_engine()

        file_ = (
            reply_to.document
            or reply_to.photo
            or reply_to.video
            or reply_to.audio
            or reply_to.voice
            or reply_to.video_note
            or reply_to.sticker
            or reply_to.animation
            or None
        )
        self.file_details = {"caption": reply_to.caption if hasattr(reply_to, "caption") else ""}

        if file_ is not None or reply_to.text:
            await TelegramDownloadHelper(self).add_download(
                reply_to, f"{path}/", session
            )




@new_task
async def ht_merge_callback(client, query):
    data = query.data.split()
    mid = int(data[2])
    task_info = ht_tasks.get(mid)
    if not task_info:
        return await query.answer("Task expired or already started!", show_alert=True)
    if query.from_user.id != task_info["user_id"]:
        return await query.answer("This menu is not for you!", show_alert=True)

    def render_ht_menu(mid):
        t_info = ht_tasks.get(mid, {})
        m_on = "✓ ON" if t_info.get("merge") else "OFF"
        m_mode = t_info.get("merge_mode", "normal")
        tr_on = "✓ ON" if t_info.get("trim") else "OFF"
        ex_on = "✓ ON" if t_info.get("extract") else "OFF"

        buttons = ButtonMaker()
        buttons.data_button(f"Merge: {m_on}", f"htmerge merge {mid}", position="header")
        if t_info.get("merge"):
            n_st = "✓ " if m_mode == "normal" else ""
            a_st = "✓ " if m_mode == "advanced" else ""
            buttons.data_button(f"{n_st}Normal Mode", f"htmerge setmode {mid} normal")
            buttons.data_button(f"{a_st}Advanced Mode", f"htmerge setmode {mid} advanced")

        buttons.data_button(f"Trim: {tr_on}", f"htmerge trim {mid}")
        buttons.data_button(f"Extract: {ex_on}", f"htmerge extract {mid}")
        buttons.data_button("Done", f"htmerge done {mid}", position="footer")
        return buttons

    def render_ht_text(mid):
        t_info = ht_tasks.get(mid, {})
        if not t_info.get("merge"):
            m_disp = "OFF"
        else:
            m_disp = f"ON ({t_info.get('merge_mode', 'normal').title()} Mode)"
        return (
            f"<b>Task Received with -ht flag.</b>\nChoose pre-upload options:\n\n"
            f"• <b>Merge:</b> {m_disp}\n"
            f"• <b>Trim:</b> {'✓ ON' if t_info.get('trim') else 'OFF'} ({t_info.get('trim_range') or 'Not Set'})\n"
            f"• <b>Extract:</b> {'✓ ON' if t_info.get('extract') else 'OFF'} ({', '.join(t_info.get('extract_types', [])) or 'Not Set'})"
        )

    if data[1] == "merge":
        task_info["merge"] = not task_info.get("merge")
        if task_info["merge"] and "merge_mode" not in task_info:
            task_info["merge_mode"] = "normal"
        await query.answer(f"Merge {'ON' if task_info['merge'] else 'OFF'}")
        await edit_message(query.message, render_ht_text(mid), render_ht_menu(mid).build_menu(2))
    elif data[1] == "setmode":
        mode = data[3]
        task_info["merge"] = True
        task_info["merge_mode"] = mode
        await query.answer(f"Selected {mode.title()} Merge Mode")
        await edit_message(query.message, render_ht_text(mid), render_ht_menu(mid).build_menu(2))
    elif data[1] == "trim":
        await query.answer()
        buttons = ButtonMaker()
        buttons.data_button("◀️ Back", f"htmerge back {mid}", position="footer")
        prompt = "<b>✂️ Trim Media:</b>\nPlease send trim range in format: <code>HH:MM:SS - HH:MM:SS</code>\nExample: <code>00:20:07 - 00:30:08</code>\n⏱️ <i>Timeout: 30s</i>"
        await edit_message(query.message, prompt, buttons.build_menu(1))

        event_done = bot_loop.create_future()
        user_input = []

        async def trim_filter(_, __, event):
            u = event.from_user or event.sender_chat
            return bool(u and u.id == task_info["user_id"] and event.chat.id == query.message.chat.id and event.text)

        async def trim_handler(_, msg):
            user_input.append(msg.text.strip())
            await delete_message(msg)
            if not event_done.done():
                event_done.set_result(True)

        from pyrogram.handlers import MessageHandler
        from pyrogram.filters import create
        from asyncio import wait_for
        h = client.add_handler(MessageHandler(trim_handler, filters=create(trim_filter)), group=-1)
        try:
            await wait_for(event_done, timeout=30)
            if user_input and "-" in user_input[0]:
                task_info["trim"] = True
                task_info["trim_range"] = user_input[0]
        except Exception:
            pass
        finally:
            client.remove_handler(*h)
            await edit_message(query.message, render_ht_text(mid), render_ht_menu(mid).build_menu(2))
    elif data[1] == "chorder":
        await query.answer()
        buttons = ButtonMaker()
        buttons.data_button("◀️ Back", f"htmerge back {mid}", position="footer")
        prompt = (
            "<b>🔀 Send new track order format:</b>\n"
            "• <code>aud=1:2</code> — Swap audio track 1 with track 2\n"
            "• <code>sub=1:2</code> — Swap subtitle track 1 with track 2\n"
            "• Multiple: <code>aud=1:2,3:4, sub=1:2</code>\n⏱️ <i>Timeout: 30s</i>"
        )
        await edit_message(query.message, prompt, buttons.build_menu(1))

        event_done = bot_loop.create_future()
        user_input = []

        async def reorder_filter(_, __, event):
            u = event.from_user or event.sender_chat
            return bool(u and u.id == task_info["user_id"] and event.chat.id == query.message.chat.id and event.text)

        async def reorder_handler(_, msg):
            user_input.append(msg.text.strip())
            await delete_message(msg)
            if not event_done.done():
                event_done.set_result(True)

        from pyrogram.handlers import MessageHandler
        from pyrogram.filters import create
        from asyncio import wait_for
        h = client.add_handler(MessageHandler(reorder_handler, filters=create(reorder_filter)), group=-1)
        try:
            await wait_for(event_done, timeout=30)
            if user_input:
                inp = user_input[0]
                aud_swaps, sub_swaps = [], []
                for item in inp.split(","):
                    item = item.strip()
                    if item.startswith("aud="):
                        val = item.split("=", 1)[1]
                        nums = [int(x) for x in val.split(":") if x.isdigit()]
                        for k in range(0, len(nums) - 1, 2):
                            aud_swaps.append([nums[k], nums[k+1]])
                    elif item.startswith("sub="):
                        val = item.split("=", 1)[1]
                        nums = [int(x) for x in val.split(":") if x.isdigit()]
                        for k in range(0, len(nums) - 1, 2):
                            sub_swaps.append([nums[k], nums[k+1]])
                task_info["reorder"] = True
                task_info["reorder_aud"] = aud_swaps
                task_info["reorder_sub"] = sub_swaps
        except Exception:
            pass
        finally:
            client.remove_handler(*h)
            await edit_message(query.message, render_ht_text(mid), render_ht_menu(mid).build_menu(2))
    elif data[1] == "extract":
        await query.answer()
        selected_ext = task_info.get("extract_types", [])

        if len(data) > 3:
            ex_type = data[3]
            if ex_type == "all":
                selected_ext = ["video", "audio", "subtitle"]
            elif ex_type in selected_ext:
                selected_ext.remove(ex_type)
            else:
                selected_ext.append(ex_type)
            task_info["extract_types"] = selected_ext
            task_info["extract"] = bool(selected_ext)

        buttons = ButtonMaker()
        v_st = "✓ " if "video" in selected_ext else ""
        a_st = "✓ " if "audio" in selected_ext else ""
        s_st = "✓ " if "subtitle" in selected_ext else ""

        buttons.data_button(f"{v_st}Video/File", f"htmerge extract {mid} video")
        buttons.data_button(f"{a_st}Audio", f"htmerge extract {mid} audio")
        buttons.data_button(f"{s_st}Subtitle", f"htmerge extract {mid} subtitle")
        buttons.data_button("All", f"htmerge extract {mid} all")
        buttons.data_button("Done", f"htmerge back {mid}", position="footer")

        caption = f"<b>📦 Select Extraction Types:</b>\nActive: {', '.join(selected_ext) or 'None'}"
        await edit_message(query.message, caption, buttons.build_menu(2))
    elif data[1] == "dummy":
        await query.answer()
    elif data[1] == "back":
        await query.answer()
        await edit_message(query.message, render_ht_text(mid), render_ht_menu(mid).build_menu(2))
    elif data[1] == "done":
        await query.answer("Starting task...")
        fut = task_info.get("future")
        if fut and not fut.done():
            fut.set_result(True)




@new_task
async def planner_callback(client, query):
    data = query.data.split()
    cmd = data[1] if len(data) > 1 else ""

    if cmd == "dummy":
        return await query.answer()

    user_id = query.from_user.id
    from bot import planner_tasks
    from web.wserver import planner_store

    mid = data[2] if len(data) > 2 else ""
    key = f"{mid}_{user_id}"
    p_data = planner_tasks.get(key) or planner_store.get(key)

    if not p_data:
        for k, v in list(planner_tasks.items()) + list(planner_store.items()):
            if str(v.get("mid")) == str(mid):
                p_data = v
                key = k
                break

    if not p_data:
        return await query.answer("Planner session expired or not found!", show_alert=True)

    elif cmd == "page":
        target_page = int(data[3])
        p_data["page"] = target_page
        planner_tasks[key] = p_data
        planner_store[key] = p_data
        await query.answer(f"Page {target_page}")
        if "format_ui" in p_data and "msg" in p_data:
            msg_text, markup = p_data["format_ui"](p_data, is_dm=True, page=target_page)
            await edit_message(p_data["msg"], msg_text, markup)

    elif cmd == "rmfile":
        idx = int(data[3])
        curr_page = int(data[4]) if len(data) > 4 else p_data.get("page", 1)
        files = p_data.get("files", [])
        if 0 <= idx < len(files):
            removed_file = files.pop(idx)
            if len(files) < 2:
                p_data["files"] = files
                await query.answer(f"Removed '{removed_file[:20]}'. Need at least 2 files to merge!", show_alert=True)
            else:
                p_data["files"] = files
                await query.answer(f"Removed '{removed_file[:20]}'")
            planner_tasks[key] = p_data
            planner_store[key] = p_data
            if "format_ui" in p_data and "msg" in p_data:
                msg_text, markup = p_data["format_ui"](p_data, is_dm=True, page=curr_page)
                await edit_message(p_data["msg"], msg_text, markup)

    elif cmd == "move":
        idx = int(data[3])
        direction = int(data[4])
        curr_page = int(data[5]) if len(data) > 5 else p_data.get("page", 1)
        target_idx = idx + direction
        files = p_data.get("files", [])
        if 0 <= idx < len(files) and 0 <= target_idx < len(files):
            files[idx], files[target_idx] = files[target_idx], files[idx]
            p_data["files"] = files
            p_data["page"] = curr_page
            planner_tasks[key] = p_data
            planner_store[key] = p_data
            await query.answer("File reordered")
            if "format_ui" in p_data and "msg" in p_data:
                msg_text, markup = p_data["format_ui"](p_data, is_dm=True, page=curr_page)
                await edit_message(p_data["msg"], msg_text, markup)

    elif cmd == "reset":
        p_data["files"] = list(p_data.get("orig_files", []))
        curr_page = p_data.get("page", 1)
        planner_tasks[key] = p_data
        planner_store[key] = p_data
        await query.answer("Order reset to default")
        if "format_ui" in p_data and "msg" in p_data:
            msg_text, markup = p_data["format_ui"](p_data, is_dm=True, page=curr_page)
            await edit_message(p_data["msg"], msg_text, markup)

    elif cmd == "name":
        await query.answer()
        prompt_str = f"<b>✏️ Edit Output Filename:</b>\nPlease send the new output filename (e.g., <code>my_merged_video.mkv</code>)\n⏱️ <i>Timeout: 30s</i>"
        try:
            prompt_msg = await client.send_message(chat_id=user_id, text=prompt_str)
        except Exception as e:
            LOGGER.warning(f"Failed to send output filename prompt to user {user_id}: {e}")
            prompt_msg = None

        if prompt_msg and hasattr(prompt_msg, "chat"):
            from asyncio import get_running_loop
            loop = get_running_loop()
            event_done = loop.create_future()
            user_input = []

            async def name_filter(_, __, event):
                u = event.from_user or event.sender_chat
                return bool(u and u.id == user_id and event.chat.id == prompt_msg.chat.id and event.text)

            async def name_handler(_, msg):
                user_input.append(msg.text.strip())
                await delete_message(msg)
                if not event_done.done():
                    event_done.set_result(True)

            from pyrogram.handlers import MessageHandler
            from pyrogram.filters import create
            from asyncio import wait_for
            h = client.add_handler(MessageHandler(name_handler, filters=create(name_filter)), group=-1)
            try:
                await wait_for(event_done, timeout=30)
                if user_input and user_input[0]:
                    new_name = user_input[0]
                    p_data["output_filename"] = new_name
                    planner_tasks[key] = p_data
                    planner_store[key] = p_data
                    curr_page = p_data.get("page", 1)
                    if "format_ui" in p_data and "msg" in p_data:
                        msg_text, markup = p_data["format_ui"](p_data, is_dm=True, page=curr_page)
                        await edit_message(p_data["msg"], msg_text, markup)
            except Exception:
                pass
            finally:
                client.remove_handler(*h)
                await delete_message(prompt_msg)

    elif cmd == "save":
        await query.answer("Saving order...")
        p_data["saved"] = True
        planner_tasks[key] = p_data
        planner_store[key] = p_data
        fut = p_data.get("future")
        if fut and not fut.done():
            fut.set_result(True)
        if "on_save_cb" in p_data and callable(p_data["on_save_cb"]):
            try:
                await p_data["on_save_cb"](p_data)
            except Exception as e:
                LOGGER.error(f"Error executing on_save_cb in plcb save: {e}")

    elif cmd == "delete":
        await query.answer("Session deleted")
        planner_tasks.pop(key, None)
        planner_store.pop(key, None)
        fut = p_data.get("future")
        if fut and not fut.done():
            fut.set_result(False)
        if "on_delete_cb" in p_data and callable(p_data["on_delete_cb"]):
            try:
                await p_data["on_delete_cb"](p_data)
            except Exception as e:
                LOGGER.error(f"Error executing on_delete_cb in plcb delete: {e}")


@new_task
async def start_merge_callback(client, query):
    data = query.data.split()
    mid = data[1] if len(data) > 1 else ""
    user_id = query.from_user.id
    key = f"{mid}_{user_id}"
    from bot import planner_tasks
    from web.wserver import planner_store
    p_data = planner_tasks.get(key) or planner_store.get(key)

    if not p_data:
        all_sessions = list(planner_tasks.items()) + list(planner_store.items())
        for k, v in all_sessions:
            if str(v.get("mid")) == str(mid):
                p_data = v
                key = k
                break

    if not p_data:
        return await query.answer("Planner session expired or not found!", show_alert=True)

    p_data["saved"] = True
    planner_tasks[key] = p_data
    planner_store[key] = p_data

    await query.answer("Starting merge...")
    fut = p_data.get("future")
    if fut and not fut.done():
        fut.set_result(True)
    curr_text = query.message.text or query.message.caption or ""
    await edit_message(query.message, f"{curr_text}\n\n<b>🚀 Merging Started...</b>")




async def mirror(client, message):
    bot_loop.create_task(Mirror(client, message).new_event())


async def qb_mirror(client, message):
    bot_loop.create_task(Mirror(client, message, is_qbit=True).new_event())


async def jd_mirror(client, message):
    if Config.DISABLE_JD:
        await message.reply("JDownloader is currently disabled by the Bot Owner.")
        return
    bot_loop.create_task(Mirror(client, message, is_jd=True).new_event())


def hydra_nzb_id(message, cmd, force_extract=True):
    text_parts = message.text.split()
    if len(text_parts) > 1 and not text_parts[1].startswith(("http", "ftp", "/")):
        potential_id = text_parts[1]
        clean = potential_id.lstrip("-").replace("_", "")
        if clean.isalnum() and not (potential_id.startswith("-") and clean.isalpha()):
            nzb_url = f"{Config.HYDRA_IP.rstrip('/')}/getnzb/api/{potential_id}?apikey={Config.HYDRA_API_KEY}"
            extra = " ".join(text_parts[2:])
            message.text = f"{cmd} {nzb_url} -e {extra}".strip()
            return potential_id
    elif force_extract and "-e" not in message.text:
        message.text += " -e"
    return None


async def nzb_mirror(client, message):
    if Config.DISABLE_NZB:
        await message.reply("SABnzbd is currently disabled by the Bot Owner.")
        return
    nzb_id = hydra_nzb_id(message, "/nzbmirror")
    mirror_task = Mirror(client, message, is_nzb=True)
    if nzb_id:
        mirror_task.nzb_id = nzb_id
    bot_loop.create_task(mirror_task.new_event())


@new_task
async def auto_task_handler(client, message):
    from .users_settings import handler_dict

    user_id = message.from_user.id if message.from_user else (message.sender_chat.id if message.sender_chat else 0)
    if not user_id or handler_dict.get(user_id, False):
        return

    msg_text = message.text or message.caption or ""
    if msg_text.strip().startswith("/"):
        return

    user_dict = user_data.get(user_id, {})
    auto_leech = user_dict.get("AUTO_LEECH", False)
    auto_mirror = user_dict.get("AUTO_MIRROR", False)
    auto_ddl = user_dict.get("AUTO_DDL", False)

    if not (auto_leech or auto_mirror or auto_ddl):
        return

    file_ = (
        message.document
        or message.photo
        or message.video
        or message.audio
        or message.voice
        or message.video_note
        or message.sticker
        or message.animation
        or None
    )

    reply_to = message.reply_to_message
    if not file_ and reply_to:
        file_ = (
            reply_to.document
            or reply_to.photo
            or reply_to.video
            or reply_to.audio
            or reply_to.voice
            or reply_to.video_note
            or reply_to.sticker
            or reply_to.animation
            or None
        )

    has_link = bool(
        is_url(msg_text)
        or is_magnet(msg_text)
        or is_telegram_link(msg_text)
        or is_rclone_path(msg_text)
        or is_gdrive_link(msg_text)
        or is_gdrive_id(msg_text)
        or is_mega_link(msg_text)
        or ("http://" in msg_text or "https://" in msg_text or "magnet:" in msg_text)
    )

    if not file_ and not has_link and reply_to and reply_to.text:
        rtext = reply_to.text
        has_link = bool(
            is_url(rtext)
            or is_magnet(rtext)
            or is_telegram_link(rtext)
            or is_rclone_path(rtext)
            or is_gdrive_link(rtext)
            or is_gdrive_id(rtext)
            or is_mega_link(rtext)
            or ("http://" in rtext or "https://" in rtext or "magnet:" in rtext)
        )

    if not file_ and not has_link:
        return

    if auto_leech:
        await leech(client, message)
    if auto_mirror:
        await mirror(client, message)
    if auto_ddl:
        await uphoster(client, message)


async def leech(client, message):
    bot_loop.create_task(Mirror(client, message, is_leech=True).new_event())


async def qb_leech(client, message):
    bot_loop.create_task(
        Mirror(client, message, is_qbit=True, is_leech=True).new_event()
    )


async def jd_leech(client, message):
    if Config.DISABLE_JD:
        await message.reply("JDownloader is currently disabled by the Bot Owner.")
        return
    bot_loop.create_task(Mirror(client, message, is_leech=True, is_jd=True).new_event())


async def nzb_leech(client, message):
    if Config.DISABLE_NZB:
        await message.reply("SABnzbd is currently disabled by the Bot Owner.")
        return
    nzb_id = hydra_nzb_id(message, "/nzbleech")
    mirror_task = Mirror(client, message, is_leech=True, is_nzb=True)
    if nzb_id:
        mirror_task.nzb_id = nzb_id
    bot_loop.create_task(mirror_task.new_event())




async def uphoster(client, message):
    nzb_id = hydra_nzb_id(message, "/uphoster", force_extract=False)
    if nzb_id and Config.DISABLE_NZB:
        await message.reply("SABnzbd is currently disabled by the Bot Owner.")
        return
    mirror_task = Mirror(client, message, is_uphoster=True, is_nzb=bool(nzb_id))
    if nzb_id:
        mirror_task.nzb_id = nzb_id
    bot_loop.create_task(mirror_task.new_event())


async def clear_seedr_account(email, password):
    client = SeedrClient(email, password)
    await client.login()
    res = await client.list_contents("0")
    if not isinstance(res, dict):
        return 0, 0
    t_count = 0
    f_count = 0
    for t in res.get("torrents", []):
        t_id = t.get("id") or t.get("user_torrent_id")
        if t_id:
            try:
                await client.delete("torrent", t_id)
                t_count += 1
            except Exception:
                pass
    for f in res.get("folders", []):
        f_id = f.get("id")
        if f_id:
            try:
                await client.delete("folder", f_id)
                f_count += 1
            except Exception:
                pass
    return t_count, f_count


def _seedr_creds(user_id):
    user_dict = user_data.get(user_id, {})
    email = user_dict.get("SEEDR_EMAIL") or Config.SEEDR_EMAIL
    password = user_dict.get("SEEDR_PASSWORD") or Config.SEEDR_PASSWORD
    return email, password


async def seedr_guard(message, user_id):
    if Config.DISABLE_SEEDR:
        await send_message(message, "<blockquote>Seedr is currently disabled by the Bot Owner.</blockquote>")
        return False
    email, password = _seedr_creds(user_id)
    if not email or not password:
        uset_cmd = (
            f"/{BotCommands.UserSetCommand[0]}"
            if isinstance(BotCommands.UserSetCommand, list)
            else f"/{BotCommands.UserSetCommand}"
        )
        await send_message(
            message,
            f"<blockquote>Seedr credentials not configured! Please set SEEDR_EMAIL and SEEDR_PASSWORD in {uset_cmd} or bot settings.</blockquote>",
        )
        return False
    return True


@new_task
async def seedr_link(client, message):
    user_id = message.from_user.id
    if not await seedr_guard(message, user_id):
        return
    email, password = _seedr_creds(user_id)
    tag = message.from_user.mention(style="html") if message.from_user else "N/A"
    seedrlink_cmd = (
        f"/{BotCommands.SeedrLinkCommand[0]}"
        if isinstance(BotCommands.SeedrLinkCommand, list)
        else f"/{BotCommands.SeedrLinkCommand}"
    )

    link = ""
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        link = args[1].strip()
    elif reply_to := message.reply_to_message:
        if reply_to.text:
            link = reply_to.text.split("\n", 1)[0].strip()

    if not link or not (is_magnet(link) or is_url(link) or link.endswith(".torrent")):
        await message.reply(
            f"<blockquote>Please provide a valid magnet link or .torrent URL!\nUsage: <code>{seedrlink_cmd} magnet:...</code></blockquote>"
        )
        return

    msg = await send_message(message, "<b>Processing Seedr magnet link...</b>")
    seedr_client = SeedrClient(email, password)
    torrent_id = None
    folder_id = None

    try:
        await seedr_client.login()
        log_link = f"{link[:60]}..." if is_magnet(link) else link
        LOGGER.info(f"SeedrLink: Adding magnet: {log_link}")
        result = await seedr_client.add_torrent(link)
        torrent_id = result.get("torrent_id") or result.get("user_torrent_id")
        title = result.get("title") or ""

        if not torrent_id:
            raise ValueError("Failed to obtain Seedr torrent ID!")

        if title:
            await edit_message(
                msg,
                f"<b>🌱 Added to Seedr Cloud</b>\n\n<blockquote>• <b>Title:</b> <code>{escape(title)}</code>\nFetching cloud progress...</blockquote>",
            )

        known_folders = {
            f.get("id")
            for f in (await seedr_client.list_contents("0")).get("folders", [])
        }
        folder_names = {title} if title else set()
        not_found_count = 0
        last_progress = ""
        last_prog_value = -1.0
        stall_count = 0

        while True:
            await sleep(3)
            stall_count += 1
            if stall_count >= 400:
                raise ValueError("Seedr cloud download stalled with no progress!")
            res = await seedr_client.list_contents("0")
            torrent = next(
                (
                    t
                    for t in res.get("torrents", [])
                    if t.get("id") == torrent_id
                    or t.get("user_torrent_id") == torrent_id
                ),
                None,
            )
            if torrent is not None:
                not_found_count = 0
                prog = float(torrent.get("progress", 0) or 0)
                if prog != last_prog_value:
                    last_prog_value = prog
                    stall_count = 0
                name_str = torrent.get("name") or title or "Torrent"
                if torrent.get("name"):
                    folder_names.add(torrent["name"])
                prog_str = f"<b>🌱 Seedr Cloud Downloading...</b>\n\n<blockquote>• <b>Name:</b> <code>{escape(name_str)}</code>\n• <b>Progress:</b> <code>{round(prog, 2)}%</code></blockquote>"
                if prog_str != last_progress:
                    last_progress = prog_str
                    await edit_message(msg, prog_str)

            folder = _match_folder(
                res.get("folders", []),
                folder_names,
                known_folders,
                torrent is None,
            )

            if folder is not None:
                folder_contents = await seedr_client.list_contents(folder["id"])
                if folder_contents.get("files") or folder_contents.get("folders"):
                    folder_id = folder["id"]
                    break
            else:
                not_found_count += 1
                if not_found_count >= 36:
                    raise ValueError("Torrent not found on Seedr account!")

        await edit_message(msg, "<b>Generating Seedr direct download links...</b>")
        contents, total_size = await _build_contents(seedr_client, folder_id)
        if not contents:
            raise ValueError("No downloadable files found in Seedr folder!")

        buttons = ButtonMaker()
        text_lines = [
            f"<b>🌱 {escape(title or contents[0]['filename'])}</b>\n",
            f"<blockquote>• <b>Task Size:</b> {get_readable_file_size(total_size)}",
            f"• <b>Time Elapsed:</b> {get_readable_time(time() - message.date.timestamp())}",
            "• <b>In Mode:</b> Seedr Cloud",
            f"• <b>Total Files:</b> {len(contents)}",
            f"• <b>User:</b> {tag}</blockquote>\n",
            "<b>📁 Direct Download Files:</b>",
        ]

        for idx, item in enumerate(contents, start=1):
            fname = item["filename"]
            furl = item["url"]
            fsize = get_readable_file_size(item["size"])
            text_lines.append(
                f"{idx}. <a href='{furl}'>{escape(fname)}</a> (<code>{fsize}</code>)"
            )
            buttons.url_button(f"Download #{idx}", furl)

        out_text = "\n".join(text_lines)
        if len(out_text) > 4000:
            out_text = (
                out_text[:3900]
                + "\n\n<i>(Links truncated due to length limits. Use buttons below)</i>"
            )

        await edit_message(msg, out_text, buttons.build_menu(2))

    except Exception as e:
        LOGGER.error(f"SeedrLink error: {e}")
        if torrent_id:
            try:
                await seedr_client.delete("torrent", torrent_id)
            except Exception:
                pass
        await _delete_seedr_folder(seedr_client, folder_id)
        await edit_message(
            msg,
            "<b>🛑 Seedr Link Generation Stopped</b>\n\n"
            f"<blockquote>• <b>Reason:</b> {escape(str(e))}\n"
            f"• <b>Time Elapsed:</b> {get_readable_time(time() - message.date.timestamp())}\n"
            "• <b>In Mode:</b> Seedr Cloud\n"
            f"• <b>User:</b> {tag}</blockquote>",
        )
