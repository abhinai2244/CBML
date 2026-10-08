import re
from asyncio import gather, sleep, wait_for
from contextlib import suppress
from html import escape
from os import path as ospath, walk
from pyrogram.types import Message
from re import sub
from secrets import token_hex
from shlex import split

from aiofiles.os import listdir, makedirs, remove, path as aiopath
from aioshutil import move, rmtree
from pyrogram.enums import ButtonStyle, ChatAction, ChatType

from .. import (
    DOWNLOAD_DIR,
    LOGGER,
    categories_dict,
    excluded_extensions,
    intervals,
    multi_tags,
    task_dict,
    task_dict_lock,
    user_data,
)
from ..core.config_manager import Config, BinConfig
from ..core.cpu import ffmpeg_layout
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_lock import ff_lock
from .telegram_helper.button_build import ButtonMaker
from .ext_utils.bot_utils import (
    fetch_drive_cat,
    get_size_bytes,
    new_task,
    parse_dest,
    sync_to_async,
)
from .ext_utils.bulk_links import extract_bulk_links
from .ext_utils.files_utils import (
    SevenZ,
    get_base_name,
    get_path_size,
    is_archive,
    is_archive_split,
    is_first_archive_split,
    split_file,
)
from .ext_utils.links_utils import (
    is_gdrive_id,
    is_gdrive_link,
    is_rclone_path,
    is_telegram_link,
    is_mega_link,
)
from .ext_utils.media_utils import (
    FFMpeg,
    create_thumb,
    download_image_thumb,
    get_document_type,
    take_ss,
)
from .ext_utils.metadata_utils import MetadataProcessor
from .mirror_leech_utils.gdrive_utils.list import GoogleDriveList
from .mirror_leech_utils.rclone_utils.list import RcloneList
from .mirror_leech_utils.status_utils.ffmpeg_status import FFmpegStatus
from .mirror_leech_utils.status_utils.sevenz_status import SevenZStatus
from .telegram_helper.bot_commands import BotCommands
from .telegram_helper.message_utils import (
    delete_message,
    edit_message,
    get_tg_link_message,
    open_category_btns,
    open_dump_chat_btns,
    send_message,
    send_status_message,
)


def parse_track_selectors(config_str):
    aud_langs, aud_positions = set(), set()
    sub_langs, sub_positions = set(), set()

    if not config_str:
        return aud_langs, aud_positions, sub_langs, sub_positions

    parts = config_str.replace("\n", ",").replace("|", ",").split(",")
    current_mode = "aud"

    for part in parts:
        part = part.strip().lower()
        if not part:
            continue

        if "=" in part:
            prefix, val = part.split("=", 1)
            prefix = prefix.strip()
            if prefix in ("audio", "aud"):
                current_mode = "aud"
            elif prefix in ("subtitle", "sub"):
                current_mode = "sub"
            else:
                current_mode = "aud"
            part = val.strip()

        tokens = part.split()
        for token in tokens:
            token = token.strip()
            if token in ("audio", "aud"):
                current_mode = "aud"
                continue
            elif token in ("subtitle", "sub"):
                current_mode = "sub"
                continue

            if token.isdigit():
                pos = int(token)
                if current_mode == "aud":
                    aud_positions.add(pos)
                else:
                    sub_positions.add(pos)
            else:
                if current_mode == "aud":
                    aud_langs.add(token)
                else:
                    sub_langs.add(token)

    return aud_langs, aud_positions, sub_langs, sub_positions


def match_stream_track(stream, pos_1based, target_langs, target_positions):
    if pos_1based in target_positions:
        return True
    if not target_langs:
        return False
    lang = stream.get("tags", {}).get("language", "").lower()
    title = stream.get("tags", {}).get("title", "").lower()
    for l in target_langs:
        if l in lang or l in title:
            return True
        with suppress(Exception):
            from langcodes import Language
            display = Language.get(l).display_name().lower()
            if display in lang or display in title or lang in display:
                return True
    return False


def parse_reorder_rules(config_str):
    aud_swaps = []
    sub_swaps = []
    if not config_str:
        return aud_swaps, sub_swaps

    for item in config_str.split(","):
        item = item.strip().lower()
        if not item:
            continue
        if "-" in item and item.replace("-", "").isdigit():
            nums = [int(x) for x in item.split("-") if x.isdigit()]
            if len(nums) == 2:
                aud_swaps.append([nums[0], nums[1]])
        elif item.startswith("aud="):
            val = item.split("=", 1)[1]
            if ":" in val:
                for sub_item in val.split(","):
                    parts = sub_item.split(":")
                    if len(parts) == 2:
                        p1 = int(parts[0]) if parts[0].strip().isdigit() else parts[0].strip()
                        p2 = int(parts[1]) if parts[1].strip().isdigit() else parts[1].strip()
                        aud_swaps.append([p1, p2])
        elif item.startswith("sub="):
            val = item.split("=", 1)[1]
            if ":" in val:
                for sub_item in val.split(","):
                    parts = sub_item.split(":")
                    if len(parts) == 2:
                        p1 = int(parts[0]) if parts[0].strip().isdigit() else parts[0].strip()
                        p2 = int(parts[1]) if parts[1].strip().isdigit() else parts[1].strip()
                        sub_swaps.append([p1, p2])
        elif ":" in item:
            parts = item.split(":", 1)
            pos_str = parts[0].strip()
            val_str = parts[1].strip()
            if pos_str.isdigit():
                pos = int(pos_str)
                aud_swaps.append([pos, val_str])

    return aud_swaps, sub_swaps


class TaskConfig:
    def __init__(self):
        self.mid = self.message.id
        self.user = self.message.from_user or self.message.sender_chat
        self.user_id = self.user.id
        self.user_dict = user_data.get(self.user_id, {})
        self.metadata_processor = MetadataProcessor()
        set_all_meta = self.user_dict.get("SET_ALL_METADATA_ENABLE", False) and self.user_dict.get("SET_ALL_METADATA")
        if set_all_meta:
            v = self.user_dict.get("SET_ALL_METADATA")
            parsed_v = v if isinstance(v, dict) else (self.metadata_processor.parse_string(v) if isinstance(v, str) else {})
            self.default_metadata_dict = parsed_v
            self.audio_metadata_dict = parsed_v
            self.video_metadata_dict = parsed_v
            self.subtitle_metadata_dict = parsed_v
        else:
            for k in ("METADATA", "AUDIO_METADATA", "VIDEO_METADATA", "SUBTITLE_METADATA"):
                v = self.user_dict.get(k, {})
                if k == "METADATA":
                    k = "default_metadata"
                if isinstance(v, dict):
                    setattr(self, f"{k.lower()}_dict", v)
                elif isinstance(v, str):
                    setattr(
                        self, f"{k.lower()}_dict", self.metadata_processor.parse_string(v)
                    )
                else:
                    setattr(self, f"{k.lower()}_dict", {})
        self.dir = f"{DOWNLOAD_DIR}{self.mid}"
        self.up_dir = ""
        self.link = ""
        self.up_dest = ""
        self.drive_id = ""
        self.leech_dest = ""
        self.cmd_up_dest = ""
        self.cmd_thread_id = None
        self.leech_thread_id = None
        self.dump_dest = ""
        self.key_dump_dests = []
        self.rc_flags = ""
        self.tag = ""
        self.name = ""
        self.subname = ""
        self.category = ""
        self.index_link = ""
        self.name_swap = ""
        self.thumbnail_layout = ""
        self.folder_name = ""
        self.split_size = 0
        self.max_split_size = 0
        self.split_mode = "part"
        self.multi = 0
        self.size = 0
        self.subsize = 0
        self.proceed_count = 0
        self.is_leech = False
        self.is_yt = False
        self.is_qbit = False
        self.is_mega = False
        self.is_nzb = False
        self.is_seedr = False
        self.is_jd = False
        self.is_clone = False
        self.is_uphoster = False
        self.is_gdrive = False
        self.is_rclone = False
        self.is_ytdlp = False
        self.is_alldebrid = False
        self._alldebrid_magnet_id = 0
        self.equal_splits = False
        self.transmission_mode = "bot"
        self.extract = False
        self.compress = False
        self.select = False
        self.files_selected = False
        self.seed = False
        self.join = False
        self.private_link = False
        self.stop_duplicate = False
        self.auto_merge = False
        self.sample_video = False
        self.convert_audio = False
        self.convert_video = False
        self.screen_shots = False
        self.is_cancelled = False
        self.force_run = False
        self.force_download = False
        self.force_upload = False
        self.is_torrent = False
        self.as_med = False
        self.as_doc = False
        self.is_file = False
        self.hybrid_leech = False
        self.manual_merge = False
        self.manual_reorder = False
        self.manual_trim = False
        self.manual_extract = False
        self.manual_rm_stream = False
        self.bot_trans = False
        self.user_trans = False
        self.is_rss = getattr(self.message, "_rss_trigger", False)
        self.progress = True
        self.ffmpeg_cmds = None
        self.dump_chat = 0
        self.dump_msg_id = 0
        self.metadata_title = None
        self.chat_thread_id = None
        self.subproc = None
        self.thumb = None
        self.excluded_extensions = []
        self.files_to_proceed = []
        self.is_super_chat = self.message.chat.type in [
            ChatType.SUPERGROUP,
            ChatType.CHANNEL,
            ChatType.FORUM,
        ]
        self.source_url = None
        self.bot_pm = Config.BOT_PM or self.user_dict.get("BOT_PM")
        self.pm_msg = None
        self.file_details = {}
        self.mode = tuple()

    def _set_mode_engine(self):
        if self.is_nzb and self.link and "/getnzb/api/" in self.link:
            try:
                nzb_id = self.link.split("/getnzb/api/")[1].split("?")[0]
                self.source_url = f"NZB: {nzb_id}"
            except Exception:
                self.source_url = "NZB Link"
        else:
            self.source_url = (
                self.link
                if len(self.link) > 0 and self.link.startswith("http")
                else (
                    f"https://t.me/share/url?url={self.link}"
                    if self.link
                    else self.message.link
                )
            )

        out_mode = f"#{'Leech' if self.is_leech else 'UphosterUpload' if self.is_uphoster else 'Clone' if self.is_clone else 'Mega' if self.up_dest in ('mega', 'mega:') else 'RClone' if self.up_dest.startswith('mrcc:') or is_rclone_path(self.up_dest) else 'GDrive' if self.up_dest.startswith(('mtp:', 'tp:', 'sa:')) or is_gdrive_id(self.up_dest) else 'UpHosters'}"
        out_mode += " (Zip)" if self.compress else " (Unzip)" if self.extract else ""

        self.is_rclone = is_rclone_path(self.link)
        self.is_gdrive = is_gdrive_link(self.source_url) if self.source_url else False
        self.is_mega = is_mega_link(self.link) if self.source_url else False

        in_mode = f"#{'Seedr' if self.is_seedr else 'Mega' if self.is_mega else 'qBit' if self.is_qbit else 'SABnzbd' if self.is_nzb else 'JDown' if self.is_jd else 'RCloneDL' if self.is_rclone else 'ytdlp' if self.is_ytdlp else 'GDrive' if (self.is_clone or self.is_gdrive) else 'Aria2' if (self.source_url and self.source_url != self.message.link) else 'TgMedia'}"

        self.mode = (in_mode, out_mode)

    def get_token_path(self, dest):
        if dest.startswith("mtp:"):
            return f"tokens/{self.user_id}.pickle"
        elif dest.startswith("sa:") or (
            Config.USE_SERVICE_ACCOUNTS and not dest.startswith("tp:")
        ):
            return "accounts"
        else:
            return "token.pickle"

    def get_config_path(self, dest):
        return (
            f"rclone/{self.user_id}.conf" if dest.startswith("mrcc:") else "rclone.conf"
        )

    async def is_token_exists(self, path, status):
        if is_rclone_path(path):
            config_path = self.get_config_path(path)
            if config_path != "rclone.conf" and status == "up":
                self.private_link = True
            if not await aiopath.exists(config_path):
                raise ValueError(f"Rclone Config: {config_path} not Exists!")
        elif (
            status == "dl"
            and is_gdrive_link(path)
            or status == "up"
            and is_gdrive_id(path)
        ):
            token_path = self.get_token_path(path)
            if token_path.startswith("tokens/") and status == "up":
                self.private_link = True
            if not await aiopath.exists(token_path):
                raise ValueError(f"NO TOKEN! {token_path} not Exists!")

    async def before_start(self):
        self.name_swap = (
            self.name_swap
            or self.user_dict.get("NAME_SWAP", False)
            or (Config.NAME_SWAP if "NAME_SWAP" not in self.user_dict else "")
        )
        if self.name_swap:
            self.name_swap = [x.split(":") for x in self.name_swap.split("|")]
        self.excluded_extensions = self.user_dict.get("EXCLUDED_EXTENSIONS") or (
            excluded_extensions
            if "EXCLUDED_EXTENSIONS" not in self.user_dict
            else ["aria2", "!qB"]
        )
        if not self.rc_flags:
            if self.user_dict.get("RCLONE_FLAGS"):
                self.rc_flags = self.user_dict["RCLONE_FLAGS"]
            elif "RCLONE_FLAGS" not in self.user_dict and Config.RCLONE_FLAGS:
                self.rc_flags = Config.RCLONE_FLAGS
        if self.link not in ["rcl", "gdl"]:
            if not self.is_jd:
                if is_rclone_path(self.link):
                    if not self.link.startswith("mrcc:") and self.user_dict.get(
                        "USER_TOKENS", False
                    ):
                        self.link = f"mrcc:{self.link}"
                    await self.is_token_exists(self.link, "dl")
                elif is_gdrive_link(self.link):
                    if not self.link.startswith(
                        ("mtp:", "tp:", "sa:")
                    ) and self.user_dict.get("USER_TOKENS", False):
                        self.link = f"mtp:{self.link}"
                    await self.is_token_exists(self.link, "dl")
        elif self.link == "rcl":
            if not self.is_ytdlp and not self.is_jd:
                self.link = await RcloneList(self).get_rclone_path("rcd")
                if not is_rclone_path(self.link):
                    raise ValueError(self.link)
        elif self.link == "gdl":
            if not self.is_ytdlp and not self.is_jd:
                self.link = await GoogleDriveList(self).get_target_id("gdd")
                if not is_gdrive_id(self.link):
                    raise ValueError(self.link)

        self.transmission_mode = Config.TRANSMISSION_MODE

        if self.user_dict.get("UPLOAD_PATHS", False):
            if self.up_dest in self.user_dict["UPLOAD_PATHS"]:
                self.up_dest = self.user_dict["UPLOAD_PATHS"][self.up_dest]
        elif "UPLOAD_PATHS" not in self.user_dict and Config.UPLOAD_PATHS:
            if self.up_dest in Config.UPLOAD_PATHS:
                self.up_dest = Config.UPLOAD_PATHS[self.up_dest]

        if self.category and not self.is_leech:
            dcats = fetch_drive_cat(self.user_id)
            default_id = self.user_dict.get("GDRIVE_ID") or Config.GDRIVE_ID
            default_index = self.user_dict.get("INDEX_URL") or Config.INDEX_URL
            merged_cats = {
                "Default": {"drive_id": default_id, "index_link": default_index},
                **dcats,
                **categories_dict,
            }
            if self.category == "gdl":
                self.up_dest = "gdl"
            elif self.category == "gd":
                self.up_dest = default_id
                self.index_link = default_index
            elif "|" in self.category:
                parts = self.category.split("|", 1)
                self.up_dest = parts[0]
                self.index_link = parts[1] if len(parts) > 1 else ""
            elif is_gdrive_id(self.category):
                self.up_dest = self.category
            elif self.category in merged_cats:
                self.up_dest = merged_cats[self.category]["drive_id"]
                self.index_link = merged_cats[self.category].get("index_link", "")
            else:
                drive_id, index_link, is_cancelled = await open_category_btns(
                    self.message
                )
                if is_cancelled:
                    self.is_cancelled = True
                    return
                if drive_id:
                    self.up_dest = drive_id
                    self.index_link = index_link or ""
            gc_used = True
        else:
            gc_used = False

        enable_ffc = self.user_dict.get("ENABLE_FFMPEG_CMDS") if "ENABLE_FFMPEG_CMDS" in self.user_dict else Config.ENABLE_FFMPEG_CMDS
        user_ff = self.user_dict.get("FFMPEG_CMDS") or {}
        global_ff = Config.FFMPEG_CMDS or {}
        ffmpeg_dict = {**global_ff, **user_ff} if isinstance(user_ff, dict) and isinstance(global_ff, dict) else (user_ff or global_ff or {})

        DEFAULT_BLOCKED_FFMPEG = {
            "compress": [
                "-i mltb.video -c:v libx264 -crf 28 -preset medium -c:a aac -b:a 128k mltb -del"
            ],
            "encode": [
                "-i mltb.video -c:v libx265 -crf 28 -preset medium -c:a aac -b:a 128k mltb -del"
            ],
            "watermark": [
                "-i mltb.video -vf \"drawtext=text='anizoneflix':fontcolor=red:fontsize=48:x=w-tw-20:y=20\" -map 0:v -map 0:a? -c:v libx264 -c:a copy mltb -del"
            ]
        }
        for b_key, b_cmd in DEFAULT_BLOCKED_FFMPEG.items():
            if b_key not in ffmpeg_dict:
                ffmpeg_dict[b_key] = b_cmd

        if not enable_ffc:
            self.ffmpeg_cmds = None

        if enable_ffc and self.ffmpeg_cmds is not None:
            raw_input = self.ffmpeg_cmds if isinstance(self.ffmpeg_cmds, (list, set, tuple)) else [self.ffmpeg_cmds]
            keys = []
            custom_cmd_strings = []
            for item in raw_input:
                if isinstance(item, str):
                    if item.strip().startswith("-i "):
                        custom_cmd_strings.append(item.strip())
                    else:
                        for sub_k in item.split(","):
                            if sub_k.strip():
                                keys.append(sub_k.strip().lower())
                else:
                    keys.append(str(item).strip().lower())

            valid = {
                str(key).lower(): (cmds if isinstance(cmds, (list, tuple)) else [cmds])
                for key, cmds in ffmpeg_dict.items()
            } if isinstance(ffmpeg_dict, dict) else {}

            enc_enabled = Config.ENABLE_ENCODE and (self.user_dict.get("ENABLE_ENCODE") if "ENABLE_ENCODE" in self.user_dict else True)
            com_enabled = Config.ENABLE_COMPRESS and (self.user_dict.get("ENABLE_COMPRESS") if "ENABLE_COMPRESS" in self.user_dict else True)
            wm_enabled = Config.ENABLE_WATERMARK and (self.user_dict.get("ENABLE_WATERMARK") if "ENABLE_WATERMARK" in self.user_dict else True)

            allowed_keys = []
            blocked_keys = []
            for k in keys:
                if k == "encode" and not enc_enabled:
                    blocked_keys.append(k)
                elif k == "compress" and not com_enabled:
                    blocked_keys.append(k)
                elif k == "watermark" and not wm_enabled:
                    blocked_keys.append(k)
                else:
                    allowed_keys.append(k)

            if blocked_keys:
                await send_message(
                    self.message,
                    f"FFmpeg feature option(s) disabled: {', '.join(blocked_keys)}.",
                )

            if missing := [key for key in allowed_keys if key not in valid]:
                await send_message(
                    self.message,
                    f"Unknown FFmpeg Cmds key(s): {', '.join(map(str, missing))}. Check FF Media Settings in /bsetting.",
                )

            resolved_cmds = [
                value for key in allowed_keys if key in valid for value in valid[key]
            ]
            resolved_cmds.extend(custom_cmd_strings)
            self.ffmpeg_cmds = resolved_cmds or None

            user_dump = self.user_dict.get("FFMPEG_DUMP") or {}
            global_dump = Config.FFMPEG_DUMP or {}
            dump_chats = Config.LEECH_DUMP_CHATS or {}
            has_preset_dump = False
            for k in keys:
                d_val = user_dump.get(k) or global_dump.get(k)
                if d_val:
                    resolved_dest = dump_chats.get(d_val) or d_val
                    if resolved_dest and resolved_dest not in self.key_dump_dests:
                        self.key_dump_dests.append(resolved_dest)
                        has_preset_dump = True

            if has_preset_dump:
                self.has_preset_dump = True
                self.dump_dest = self.key_dump_dests[0]
            else:
                self.has_preset_dump = False
                universal_dump = self.user_dict.get("LEECH_DUMP_CHAT") or Config.LEECH_LOG_CHAT or ""
                if not self.dump_dest:
                    self.dump_dest = universal_dump

        self.metadata_title = self.user_dict.get("METADATA")

        if not self.is_leech:
            self.stop_duplicate = (
                self.user_dict.get("STOP_DUPLICATE")
                or "STOP_DUPLICATE" not in self.user_dict
                and Config.STOP_DUPLICATE
            )
            if not gc_used:
                default_upload = (
                    self.user_dict.get("DEFAULT_UPLOAD", "") or Config.DEFAULT_UPLOAD
                )
                if not self.is_uphoster and (
                    (not self.up_dest and default_upload == "rc")
                    or self.up_dest == "rc"
                ):
                    self.up_dest = (
                        self.user_dict.get("RCLONE_PATH") or Config.RCLONE_PATH
                    )
                elif not self.is_uphoster and (
                    (not self.up_dest and default_upload == "gd")
                    or self.up_dest == "gd"
                ):
                    self.up_dest = self.user_dict.get("GDRIVE_ID") or Config.GDRIVE_ID
                elif not self.is_uphoster and (
                    (not self.up_dest and default_upload == "mega")
                    or self.up_dest == "mega"
                ):
                    self.up_dest = "mega:"

                if self.is_uphoster and not self.up_dest:
                    uphoster_service = self.user_dict.get("UPHOSTER_SERVICE", "gofile")
                    services = uphoster_service.split(",")
                    for service in services:
                        if service == "gofile":
                            if not (
                                self.user_dict.get("GOFILE_TOKEN") or Config.GOFILE_API
                            ):
                                raise ValueError("No Gofile Token Found!")
                        elif service == "buzzheavier":
                            if not (
                                self.user_dict.get("BUZZHEAVIER_TOKEN")
                                or Config.BUZZHEAVIER_API
                            ):
                                raise ValueError("No BuzzHeavier Token Found!")
                        elif service == "pixeldrain":
                            if not (
                                self.user_dict.get("PIXELDRAIN_KEY")
                                or Config.PIXELDRAIN_KEY
                            ):
                                raise ValueError("No PixelDrain Key Found!")
                    self.up_dest = "Uphoster"

            if not self.up_dest:
                raise ValueError("No Upload Destination!")

            if self.up_dest in ("gdl", "rcl"):
                pass
            elif is_gdrive_id(self.up_dest):
                if not self.up_dest.startswith(
                    ("mtp:", "tp:", "sa:")
                ) and self.user_dict.get("USER_TOKENS", False):
                    self.up_dest = f"mtp:{self.up_dest}"
            elif self.up_dest == "mega:":
                pass
            elif is_rclone_path(self.up_dest):
                if not self.up_dest.startswith("mrcc:") and self.user_dict.get(
                    "USER_TOKENS", False
                ):
                    self.up_dest = f"mrcc:{self.up_dest}"
                self.up_dest = self.up_dest.strip("/")
            elif self.is_uphoster:
                pass
            else:
                raise ValueError("Wrong Upload Destination!")

            if (
                self.up_dest not in ["rcl", "gdl"]
                and not self.is_uphoster
                and self.up_dest != "mega:"
            ):
                await self.is_token_exists(self.up_dest, "up")

            if self.up_dest == "rcl":
                if self.is_clone:
                    if not is_rclone_path(self.link):
                        raise ValueError(
                            "You can't clone from different types of tools"
                        )
                    config_path = self.get_config_path(self.link)
                else:
                    config_path = None
                self.up_dest = await RcloneList(self).get_rclone_path(
                    "rcu", config_path
                )
                if not is_rclone_path(self.up_dest):
                    raise ValueError(self.up_dest)
            elif self.up_dest == "gdl":
                if self.is_clone:
                    if not is_gdrive_link(self.link):
                        raise ValueError(
                            "You can't clone from different types of tools"
                        )
                    token_path = self.get_token_path(self.link)
                else:
                    token_path = None
                self.up_dest = await GoogleDriveList(self).get_target_id(
                    "gdu", token_path
                )
                if not is_gdrive_id(self.up_dest):
                    raise ValueError(self.up_dest)
            elif self.is_clone:
                if is_gdrive_link(self.link) and self.get_token_path(
                    self.link
                ) != self.get_token_path(self.up_dest):
                    raise ValueError("You must use the same token to clone!")
                elif is_rclone_path(self.link) and self.get_config_path(
                    self.link
                ) != self.get_config_path(self.up_dest):
                    raise ValueError("You must use the same config to clone!")
        else:
            # Telegram uploads must never silently target an AUTHORIZED_CHATS
            # chat. Authorized chats are command-access controls, not upload
            # destinations. Prefer configured dump chats; otherwise DM the user.
            raw_auth = str(getattr(Config, "AUTHORIZED_CHATS", "") or "")
            auth_ids = set()
            for raw in raw_auth.split():
                base = raw.split("|", 1)[0].strip()
                if base.lstrip("-").isdigit():
                    auth_ids.add(int(base))

            configured_dump = self.user_dict.get("LEECH_DUMP_CHAT") or Config.LEECH_LOG_CHAT or ""
            try:
                parsed_dump, parsed_thread = parse_dest(configured_dump) if configured_dump else (0, None)
            except Exception:
                parsed_dump, parsed_thread = 0, None

            if parsed_dump and parsed_dump in auth_ids:
                # The configured dump is invalid as an upload target; fall back
                # to the user's private chat instead of uploading into an auth chat.
                self.leech_dest = self.user_id
                self.leech_thread_id = None
                LOGGER.warning(
                    "Configured dump chat %s is also AUTHORIZED_CHATS; using user DM %s instead",
                    parsed_dump, self.user_id,
                )
            elif configured_dump:
                self.leech_dest, self.leech_thread_id = parsed_dump, parsed_thread
            else:
                self.leech_dest, self.leech_thread_id = self.user_id, None

            self.cmd_up_dest = self.up_dest
            if self.cmd_up_dest:
                if not isinstance(self.cmd_up_dest, int):
                    if self.cmd_up_dest.startswith("b:"):
                        self.cmd_up_dest = self.cmd_up_dest.replace("b:", "", 1)
                        self.transmission_mode = "bot"
                    elif self.cmd_up_dest.startswith("u:"):
                        self.cmd_up_dest = self.cmd_up_dest.replace("u:", "", 1)
                        self.transmission_mode = "user"
                    elif self.cmd_up_dest.startswith("h:"):
                        self.cmd_up_dest = self.cmd_up_dest.replace("h:", "", 1)
                        self.transmission_mode = "both"
                    if str(self.cmd_up_dest).lower() == "pm":
                        self.cmd_up_dest = self.user_id
                    else:
                        chat, self.cmd_thread_id = parse_dest(self.cmd_up_dest)
                        self.cmd_up_dest = chat

            self.transmission_mode = Config.TRANSMISSION_MODE
            if self.bot_trans:
                self.transmission_mode = "bot"
            if self.user_trans:
                self.transmission_mode = "user"
            if self.hybrid_leech:
                self.transmission_mode = "both"

            self.up_dest = ""
            if self.dump_dest:
                dump_chats = Config.LEECH_DUMP_CHATS or {}
                self.up_dest = dump_chats.get(self.dump_dest)
                if self.up_dest is None:
                    chat, thread = parse_dest(self.dump_dest)
                    if isinstance(chat, int) or (isinstance(chat, str) and (chat.startswith("@") or chat.lstrip("-").isdigit())):
                        self.up_dest = chat
                        if thread is not None:
                            self.chat_thread_id = thread
                    else:
                        default_dump = Config.LEECH_LOG_CHAT or self.user_dict.get("LEECH_DUMP_CHAT") or ""
                        if default_dump:
                            self.up_dest, thread = parse_dest(default_dump)
                            if thread is not None:
                                self.chat_thread_id = thread
                        elif dump_chats:
                            up_dest, is_cancelled = await open_dump_chat_btns(
                                self.message, dump_chats, self.dump_dest
                            )
                            if is_cancelled:
                                self.is_cancelled = True
                                return
                            if not up_dest:
                                raise ValueError("No dump chat selected!")
                            self.up_dest = up_dest

            if self.up_dest:
                if not isinstance(self.up_dest, int):
                    self.up_dest, self.chat_thread_id = parse_dest(self.up_dest)

                personal_mode = self.user_dict.get("TELEGRAM_SESSION_MODE", "disabled")
                if personal_mode in ("upload", "both"):
                    self.tg_user_client = await TgClient.get_personal_user(
                        self.user_id,
                        self.user_dict.get("TELEGRAM_SESSION_STRING"),
                    )
                else:
                    self.tg_user_client = None

                user_client = self.tg_user_client or TgClient.user
                if self.transmission_mode in ("user", "both"):
                    if not user_client:
                        self.transmission_mode = "bot"
                    else:
                        try:
                            chat = await user_client.get_chat(self.up_dest)
                        except Exception:
                            chat = None
                        if chat is None:
                            self.transmission_mode = "bot"
                        else:
                            uploader_id = user_client.me.id
                            if chat.type not in [
                                ChatType.SUPERGROUP,
                                ChatType.CHANNEL,
                                ChatType.GROUP,
                                ChatType.FORUM,
                            ]:
                                self.transmission_mode = "bot"
                            else:
                                member = await chat.get_member(uploader_id)
                                if (
                                    not member.privileges.can_manage_chat
                                    or not member.privileges.can_delete_messages
                                ):
                                    self.transmission_mode = "bot"

                try:
                    chat = await self.client.get_chat(self.up_dest)
                except Exception:
                    chat = None
                if chat is None:
                    if self.transmission_mode == "bot":
                        self.transmission_mode = "user" if (getattr(self, "tg_user_client", None) or TgClient.user) else "bot"
                else:
                    uploader_id = self.client.me.id
                    if chat.type in [
                        ChatType.SUPERGROUP,
                        ChatType.CHANNEL,
                        ChatType.GROUP,
                        ChatType.FORUM,
                    ]:
                        member = await chat.get_member(uploader_id)
                        if (
                            not member.privileges.can_manage_chat
                            or not member.privileges.can_delete_messages
                        ):
                            if self.transmission_mode == "bot":
                                raise ValueError(
                                    "You don't have enough privileges in this chat!"
                                )
                            else:
                                self.transmission_mode = "user"
                    else:
                        if self.transmission_mode == "bot":
                            try:
                                await self.client.send_chat_action(
                                    self.up_dest, ChatAction.TYPING
                                )
                            except Exception:
                                raise ValueError("Start the bot and try again!")
                        else:
                            self.transmission_mode = "user"
            elif self.transmission_mode in ("user", "both") and not self.is_super_chat:
                self.transmission_mode = "bot"
            if self.split_size:
                if self.split_size.isdigit():
                    self.split_size = int(self.split_size)
                else:
                    self.split_size = get_size_bytes(self.split_size)
            self.split_size = (
                self.split_size
                or self.user_dict.get("LEECH_SPLIT_SIZE")
                or Config.LEECH_SPLIT_SIZE
            )
            self.equal_splits = (
                self.user_dict.get("EQUAL_SPLITS")
                or Config.EQUAL_SPLITS
                and "EQUAL_SPLITS" not in self.user_dict
            )
            self.max_split_size = (
                TgClient.MAX_SPLIT_SIZE
                if self.transmission_mode in ("user", "both")
                else 2097152000
            )
            self.split_size = min(self.split_size, self.max_split_size)

            if not self.as_doc:
                self.as_doc = (
                    not self.as_med
                    if self.as_med
                    else (
                        self.user_dict.get("AS_DOCUMENT", False)
                        or Config.AS_DOCUMENT
                        and "AS_DOCUMENT" not in self.user_dict
                    )
                )

            self.thumbnail_layout = (
                self.thumbnail_layout
                or self.user_dict.get("THUMBNAIL_LAYOUT", False)
                or (
                    Config.THUMBNAIL_LAYOUT
                    if "THUMBNAIL_LAYOUT" not in self.user_dict
                    else ""
                )
            )

            self.split_mode = (
                self.user_dict.get("SPLIT_MODE")
                or getattr(Config, "SPLIT_MODE", "part")
            )

            if not self.auto_merge:
                self.auto_merge = self.user_dict.get("AUTO_MERGE", False) or (
                    "AUTO_MERGE" not in self.user_dict
                    and getattr(Config, "AUTO_MERGE", False)
                )

        if not self.thumb:
            user_thumb = self.user_dict.get("THUMBNAIL") or f"thumbnails/{self.user_id}.jpg"
            if user_thumb and (await aiopath.exists(user_thumb) or user_thumb.startswith("http") or is_telegram_link(user_thumb)):
                self.thumb = user_thumb

        if self.thumb and self.thumb != "none":
            if is_telegram_link(self.thumb):
                msg = (await get_tg_link_message(self.thumb, user_id=self.user_id, user_dict=self.user_dict))[0]
                self.thumb = (
                    await create_thumb(msg, self.user_id) if msg and (msg.photo or msg.document) else ""
                )
            elif self.thumb.startswith("http"):
                self.thumb = await download_image_thumb(self.thumb)

    async def get_tag(self, text: list):
        if len(text) > 1 and text[1].startswith("Tag: "):
            user_info = text[1].split("Tag: ")
            if len(user_info) >= 3:
                id_ = user_info[-1]
                self.tag = " ".join(user_info[:-1])
            else:
                self.tag, id_ = text[1].split("Tag: ")[1].split()
            self.user = self.message.from_user = await self.client.get_users(int(id_))
            self.user_id = self.user.id
            self.user_dict = user_data.get(self.user_id, {})
            with suppress(Exception):
                await self.message.unpin()
        if self.user:
            if username := self.user.username:
                self.tag = f"@{username}"
            elif hasattr(self.user, "mention"):
                self.tag = self.user.mention
            else:
                self.tag = self.user.title

    @new_task
    async def run_multi(self, input_list, obj):
        await sleep(7)
        if not self.multi_tag and self.multi > 1:
            self.multi_tag = token_hex(3)
            multi_tags.add(self.multi_tag)
        elif self.multi <= 1:
            if self.multi_tag in multi_tags:
                multi_tags.discard(self.multi_tag)
            return
        if self.multi_tag and self.multi_tag not in multi_tags:
            await send_message(
                self.message, f"{self.tag} Multi Task has been cancelled!"
            )
            await send_status_message(self.message)
            async with task_dict_lock:
                for fd_name in self.same_dir:
                    self.same_dir[fd_name]["total"] -= self.multi
            return
        if len(self.bulk) != 0:
            msg = input_list[:1]
            msg.append(f"{self.bulk[0]} -i {self.multi - 1} {self.options}")
            msgts = " ".join(msg)
            if self.multi > 2:
                msgts += f"\n• <b>Cancel Multi:</b> <i>/{BotCommands.CancelTaskCommand[1]}_{self.multi_tag}</i>"
            nextmsg = await send_message(self.message, msgts)
        else:
            msg = [s.strip() for s in input_list]
            index = msg.index("-i")
            msg[index + 1] = f"{self.multi - 1}"
            reply_id = self.message.reply_to_message_id
            if reply_id is not None:
                nextmsg = None
                target_user_id = self.user_id
                start_id = reply_id + 1
                for offset in range(100):
                    try:
                        candidate = await self.client.get_messages(
                            chat_id=self.message.chat.id,
                            message_ids=start_id + offset,
                        )
                    except Exception:
                        candidate = None
                    if candidate and not candidate.empty:
                        c_user = candidate.from_user or candidate.sender_chat
                        if c_user and c_user.id == target_user_id:
                            nextmsg = candidate
                            break
                if nextmsg is None:
                    nextmsg = self.message
            else:
                nextmsg = self.message
            if not isinstance(nextmsg, Message):
                nextmsg = self.message
            msgts = " ".join(msg)
            if self.multi > 2:
                msgts += f"\n• <b>Cancel Multi:</b> <i>/{BotCommands.CancelTaskCommand[1]}_{self.multi_tag}</i>"
            nextmsg = await send_message(nextmsg, msgts)
        if not isinstance(nextmsg, Message):
            return
        nextmsg = await self.client.get_messages(
            chat_id=self.message.chat.id, message_ids=nextmsg.id
        )
        if self.message.from_user:
            nextmsg.from_user = self.user
        else:
            nextmsg.sender_chat = self.user
        setattr(nextmsg, "_is_bulk_subtask", True)
        if intervals["stopAll"]:
            return

        await obj(
            client=self.client,
            message=nextmsg,
            is_qbit=self.is_qbit,
            is_leech=self.is_leech,
            is_jd=self.is_jd,
            is_nzb=self.is_nzb,
            is_seedr=self.is_seedr,
            is_uphoster=self.is_uphoster,
            same_dir=self.same_dir,
            bulk=self.bulk,
            multi_tag=self.multi_tag,
            options=self.options,
        ).new_event()

    async def init_bulk(self, input_list, bulk_start, bulk_end, obj):
        if Config.DISABLE_BULK:
            await send_message(self.message, "Bulk downloads are currently disabled.")
            return
        try:
            self.bulk = await extract_bulk_links(self.message, bulk_start, bulk_end)
            if len(self.bulk) == 0:
                raise ValueError("Bulk Empty!")
            b_msg = input_list[:1]
            self.options = input_list[1:]
            if "-b" in self.options:
                index = self.options.index("-b")
                del self.options[index]
                if (bulk_start or bulk_end) and index < len(self.options):
                    del self.options[index]
            self.options = " ".join(self.options)
            b_msg.append(f"{self.bulk[0]} -i {len(self.bulk)}")
            if self.options:
                b_msg.append(self.options)
            msg = " ".join(b_msg)
            if len(self.bulk) > 2:
                self.multi_tag = token_hex(3)
                multi_tags.add(self.multi_tag)
                msg += f"\n• <b>Cancel Multi:</b> <i>/{BotCommands.CancelTaskCommand[1]}_{self.multi_tag}</i>"
            nextmsg = await send_message(self.message, msg)
            if not isinstance(nextmsg, Message):
                return
            nextmsg = await self.client.get_messages(
                chat_id=self.message.chat.id, message_ids=nextmsg.id
            )
            if self.message.from_user:
                nextmsg.from_user = self.user
            else:
                nextmsg.sender_chat = self.user
            setattr(nextmsg, "_is_bulk_subtask", True)

            await obj(
                client=self.client,
                message=nextmsg,
                is_qbit=self.is_qbit,
                is_leech=self.is_leech,
                is_jd=self.is_jd,
                is_nzb=self.is_nzb,
                is_seedr=self.is_seedr,
                is_uphoster=self.is_uphoster,
                same_dir=self.same_dir,
                bulk=self.bulk,
                multi_tag=self.multi_tag,
                options=self.options,
            ).new_event()
        except Exception:
            await send_message(
                self.message,
                "Reply to text file or to telegram message that has links separated by new line!",
            )

    async def proceed_extract(self, dl_path, gid):
        pswd = self.extract if isinstance(self.extract, str) else ""
        self.files_to_proceed = []
        if self.is_file and is_archive(dl_path):
            self.files_to_proceed.append(dl_path)
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    if (
                        is_first_archive_split(file_)
                        or is_archive(file_)
                        and not file_.strip().lower().endswith(".rar")
                    ):
                        f_path = ospath.join(dirpath, file_)
                        self.files_to_proceed.append(f_path)

        if not self.files_to_proceed:
            return dl_path
        sevenz = SevenZ(self)
        LOGGER.info(f"Extracting: {self.name}")
        async with task_dict_lock:
            task_dict[self.mid] = SevenZStatus(self, sevenz, gid, "Extract")
        t_path = dl_path
        for dirpath, _, files in await sync_to_async(
            walk, self.up_dir or self.dir, topdown=False
        ):
            code = 0
            for file_ in files:
                if self.is_cancelled:
                    return False
                if (
                    is_first_archive_split(file_)
                    or is_archive(file_)
                    and not file_.strip().lower().endswith(".rar")
                ):
                    self.proceed_count += 1
                    f_path = ospath.join(dirpath, file_)
                    t_path = get_base_name(f_path) if self.is_file else dirpath
                    if not self.is_file:
                        self.subname = file_
                    code = await sevenz.extract(f_path, t_path, pswd)
            if self.is_cancelled:
                return code
            if code == 0:
                for file_ in files:
                    if is_archive_split(file_) or is_archive(file_):
                        del_path = ospath.join(dirpath, file_)
                        try:
                            await remove(del_path)
                        except Exception:
                            self.is_cancelled = True
        return t_path if self.is_file and code == 0 else dl_path

    async def proceed_ffmpeg(self, dl_path, gid):
        cores, _ = ffmpeg_layout()
        checked = False
        lock_acquired = False
        cmds = [
            [part.strip() for part in split(item) if part.strip()]
            for item in self.ffmpeg_cmds
        ]
        try:
            ffmpeg = FFMpeg(self)
            for ffmpeg_cmd in cmds:
                self.proceed_count = 0
                cmd = [
                    "taskset",
                    "-c",
                    f"{cores}",
                    BinConfig.FFMPEG_NAME,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-progress",
                    "pipe:1",
                ] + ffmpeg_cmd
                if "-del" in cmd:
                    cmd.remove("-del")
                    delete_files = True
                else:
                    delete_files = False
                if "-i" not in cmd:
                    LOGGER.error(f"Skipping ffmpeg cmd without -i: {ffmpeg_cmd}")
                    continue
                index = cmd.index("-i")
                input_file = cmd[index + 1]
                if input_file.strip().endswith(".video"):
                    ext = "video"
                elif input_file.strip().endswith(".audio"):
                    ext = "audio"
                elif "." not in input_file:
                    ext = "all"
                else:
                    ext = ospath.splitext(input_file)[-1].lower()
                if await aiopath.isfile(dl_path):
                    is_video, is_audio, _ = await get_document_type(dl_path)
                    if not is_video and not is_audio:
                        break
                    elif is_video and ext == "audio":
                        continue
                    elif is_audio and not is_video and ext == "video":
                        continue
                    elif ext not in [
                        "all",
                        "audio",
                        "video",
                    ] and not dl_path.strip().lower().endswith(ext):
                        continue
                    new_folder = ospath.splitext(dl_path)[0]
                    if await aiopath.isfile(new_folder):
                        new_folder = f"{new_folder}_temp"
                    name = ospath.basename(dl_path)
                    await makedirs(new_folder, exist_ok=True)
                    file_path = f"{new_folder}/{name}"
                    await move(dl_path, file_path)
                    if not checked:
                        checked = True
                        async with task_dict_lock:
                            task_dict[self.mid] = FFmpegStatus(
                                self, ffmpeg, gid, "FFmpeg"
                            )
                        self.progress = False
                        await ff_lock.acquire()
                        lock_acquired = True
                        self.progress = True
                    LOGGER.info(f"Running ffmpeg cmd for: {file_path}")
                    var_cmd = cmd.copy()
                    var_cmd[index + 1] = file_path
                    self.subsize = self.size
                    res = await ffmpeg.ffmpeg_cmds(var_cmd, file_path)
                    if res:
                        if delete_files:
                            await remove(file_path)
                        remaining = await listdir(new_folder)
                        if len(remaining) == 1:
                            folder = new_folder.rsplit("/", 1)[0]
                            single_res = ospath.join(new_folder, remaining[0])
                            self.name = ospath.basename(single_res)
                            if self.name.startswith("ffmpeg"):
                                self.name = self.name.split(".", 1)[-1]
                            dl_path = ospath.join(folder, self.name)
                            await move(single_res, dl_path)
                            await rmtree(new_folder)
                            self.is_file = True
                        else:
                            # Clean up 'ffmpeg' prefix for all generated output files in folder
                            for item in remaining:
                                item_path = ospath.join(new_folder, item)
                                if item.startswith("ffmpeg"):
                                    clean_name = item.split(".", 1)[-1]
                                    clean_path = ospath.join(new_folder, clean_name)
                                    await move(item_path, clean_path)
                            dl_path = new_folder
                            self.name = new_folder.rsplit("/", 1)[-1]
                            self.is_file = False
                    else:
                        await move(file_path, dl_path)
                        await rmtree(new_folder)
                else:
                    for dirpath, _, files in await sync_to_async(
                        walk, dl_path, topdown=False
                    ):
                        for file_ in files:
                            var_cmd = cmd.copy()
                            if self.is_cancelled:
                                return False
                            f_path = ospath.join(dirpath, file_)
                            is_video, is_audio, _ = await get_document_type(f_path)
                            if not is_video and not is_audio:
                                continue
                            elif is_video and ext == "audio":
                                continue
                            elif is_audio and not is_video and ext == "video":
                                continue
                            elif ext not in [
                                "all",
                                "audio",
                                "video",
                            ] and not f_path.strip().lower().endswith(ext):
                                continue
                            self.proceed_count += 1
                            var_cmd[index + 1] = f_path
                            if not checked:
                                checked = True
                                async with task_dict_lock:
                                    task_dict[self.mid] = FFmpegStatus(
                                        self, ffmpeg, gid, "FFmpeg"
                                    )
                                self.progress = False
                                await ff_lock.acquire()
                                lock_acquired = True
                                self.progress = True
                            LOGGER.info(f"Running ffmpeg cmd for: {f_path}")
                            self.subsize = await get_path_size(f_path)
                            self.subname = file_
                            res = await ffmpeg.ffmpeg_cmds(var_cmd, f_path)
                            if res:
                                if delete_files:
                                    await remove(f_path)
                                for output_path in res:
                                    file_name = ospath.basename(output_path)
                                    if file_name.startswith("ffmpeg"):
                                        newname = file_name.split(".", 1)[-1]
                                        newres = ospath.join(dirpath, newname)
                                        await move(output_path, newres)
        finally:
            if lock_acquired:
                await ff_lock.release()
        return dl_path

    async def auto_rename(self, dl_path):
        auto_rename_enabled = self.user_dict.get("AUTO_RENAME", False) or (
            "AUTO_RENAME" not in self.user_dict and getattr(Config, "AUTO_RENAME", False)
        )
        if not auto_rename_enabled or not dl_path or not await aiopath.exists(dl_path):
            return dl_path

        from .ext_utils.rename_utils import extract_media_metadata, format_auto_rename

        format_template = self.user_dict.get("AUTO_RENAME_FORMAT") or getattr(
            Config, "AUTO_RENAME_FORMAT", "{TITLE} - {SEASON} {EPISODE} {QUALITY}"
        )

        file_details = getattr(self, "file_details", None) or {}
        caption = file_details.get("caption") or ""

        if self.is_file:
            up_dir = ospath.dirname(dl_path)
            file_name = ospath.basename(dl_path)
            metadata = extract_media_metadata(file_name, caption, file_details)
            new_name = format_auto_rename(format_template, metadata)
            if not new_name or new_name == file_name:
                return dl_path
            new_path = ospath.join(up_dir, new_name)
            await move(dl_path, new_path)
            self.name = new_name
            return new_path
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    metadata = extract_media_metadata(file_, caption, file_details)
                    new_name = format_auto_rename(format_template, metadata)
                    if not new_name or new_name == file_:
                        continue
                    await move(f_path, ospath.join(dirpath, new_name))
            return dl_path

    async def substitute(self, dl_path):
        def perform_swap(name, swaps):
            name, ext = ospath.splitext(name)
            name = sub(r"www\S+", "", name)
            for swap in swaps:
                pattern, res, cnt, sen = (
                    swap + ["", "0", "NOFLAG"][min(len(swap) - 1, 2) :]
                )[0:4]
                cnt = 0 if len(cnt) == 0 else int(cnt)
                try:
                    name = sub(
                        rf"{pattern}", res, name, cnt, flags=getattr(re, sen.upper(), 0)
                    )
                except Exception as e:
                    LOGGER.error(
                        f"Swap Error: pattern: {pattern} res: {res}. Error: {e}"
                    )
                    return False
                if len(name.encode()) > 255:
                    LOGGER.error(f"Name Swap: {name} is too long")
                    return False
            return name + ext

        if self.is_file:
            up_dir, name = dl_path.rsplit("/", 1)
            new_name = perform_swap(name, self.name_swap)
            if not new_name or new_name == name:
                return dl_path
            new_path = ospath.join(up_dir, new_name)
            await move(dl_path, new_path)
            self.name = new_name
            return new_path
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    new_name = perform_swap(file_, self.name_swap)
                    if not new_name:
                        continue
                    await move(f_path, ospath.join(dirpath, new_name))
            return dl_path

    async def generate_screenshots(self, dl_path):
        ss_nb = int(self.screen_shots) if isinstance(self.screen_shots, str) else 10
        if self.is_file:
            if (await get_document_type(dl_path))[0]:
                LOGGER.info(f"Creating Screenshot for: {dl_path}")
                res = await take_ss(dl_path, ss_nb)
                if res:
                    new_folder = ospath.splitext(dl_path)[0]
                    if await aiopath.isfile(new_folder):
                        new_folder = f"{new_folder}_temp"
                    name = ospath.basename(dl_path)
                    await makedirs(new_folder, exist_ok=True)
                    await gather(
                        move(dl_path, f"{new_folder}/{name}"),
                        move(res, new_folder),
                    )
                    return new_folder
        else:
            LOGGER.info(f"Creating Screenshot for: {dl_path}")
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    if (await get_document_type(f_path))[0]:
                        await take_ss(f_path, ss_nb)
        return dl_path

    async def convert_media(self, dl_path, gid):
        fvext = []
        if self.convert_video:
            vdata = self.convert_video.split()
            vext = vdata[0].lower()
            if len(vdata) > 2:
                if "+" in vdata[1].split():
                    vstatus = "+"
                elif "-" in vdata[1].split():
                    vstatus = "-"
                else:
                    vstatus = ""
                fvext.extend(f".{ext.lower()}" for ext in vdata[2:])
            else:
                vstatus = ""
        else:
            vext = ""
            vstatus = ""

        faext = []
        if self.convert_audio:
            adata = self.convert_audio.split()
            aext = adata[0].lower()
            if len(adata) > 2:
                if "+" in adata[1].split():
                    astatus = "+"
                elif "-" in adata[1].split():
                    astatus = "-"
                else:
                    astatus = ""
                faext.extend(f".{ext.lower()}" for ext in adata[2:])
            else:
                astatus = ""
        else:
            aext = ""
            astatus = ""

        self.files_to_proceed = {}
        all_files = []
        if self.is_file:
            all_files.append(dl_path)
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    all_files.append(f_path)

        for f_path in all_files:
            is_video, is_audio, _ = await get_document_type(f_path)
            if (
                is_video
                and vext
                and not f_path.strip().lower().endswith(f".{vext}")
                and (
                    vstatus == "+"
                    and f_path.strip().lower().endswith(tuple(fvext))
                    or vstatus == "-"
                    and not f_path.strip().lower().endswith(tuple(fvext))
                    or not vstatus
                )
            ):
                self.files_to_proceed[f_path] = "video"
            elif (
                is_audio
                and aext
                and not is_video
                and not f_path.strip().lower().endswith(f".{aext}")
                and (
                    astatus == "+"
                    and f_path.strip().lower().endswith(tuple(faext))
                    or astatus == "-"
                    and not f_path.strip().lower().endswith(tuple(faext))
                    or not astatus
                )
            ):
                self.files_to_proceed[f_path] = "audio"
        del all_files

        if self.files_to_proceed:
            ffmpeg = FFMpeg(self)
            async with task_dict_lock:
                task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Convert")
            self.progress = False
            async with ff_lock:
                self.progress = True
                for f_path, f_type in self.files_to_proceed.items():
                    self.proceed_count += 1
                    LOGGER.info(f"Converting: {f_path}")
                    if self.is_file:
                        self.subsize = self.size
                    else:
                        self.subsize = await get_path_size(f_path)
                        self.subname = ospath.basename(f_path)
                    if f_type == "video":
                        res = await ffmpeg.convert_video(f_path, vext)
                    else:
                        res = await ffmpeg.convert_audio(f_path, aext)
                    if res:
                        try:
                            await remove(f_path)
                        except Exception:
                            self.is_cancelled = True
                            return False
                        if self.is_file:
                            return res
        return dl_path

    async def generate_sample_video(self, dl_path, gid):
        data = (
            self.sample_video.split(":") if isinstance(self.sample_video, str) else ""
        )
        if data:
            sample_duration = int(data[0]) if data[0] else 60
            part_duration = int(data[1]) if len(data) > 1 else 4
        else:
            sample_duration = 60
            part_duration = 4

        self.files_to_proceed = {}
        if self.is_file and (await get_document_type(dl_path))[0]:
            file_ = ospath.basename(dl_path)
            self.files_to_proceed[dl_path] = file_
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    if (await get_document_type(f_path))[0]:
                        self.files_to_proceed[f_path] = file_
        if self.files_to_proceed:
            ffmpeg = FFMpeg(self)
            async with task_dict_lock:
                task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Sample Video")
            self.progress = False
            async with ff_lock:
                self.progress = True
                LOGGER.info(f"Creating Sample video: {self.name}")
                for f_path, file_ in self.files_to_proceed.items():
                    self.proceed_count += 1
                    if self.is_file:
                        self.subsize = self.size
                    else:
                        self.subsize = await get_path_size(f_path)
                        self.subname = file_
                    res = await ffmpeg.sample_video(
                        f_path, sample_duration, part_duration
                    )
                    if res and self.is_file:
                        new_folder = ospath.splitext(f_path)[0]
                        if await aiopath.isfile(new_folder):
                            new_folder = f"{new_folder}_temp"
                        await makedirs(new_folder, exist_ok=True)
                        await gather(
                            move(f_path, f"{new_folder}/{file_}"),
                            move(res, f"{new_folder}/SAMPLE.{file_}"),
                        )
                        return new_folder
        return dl_path

    async def proceed_encode(self, dl_path, gid):
        if not dl_path or not await aiopath.exists(dl_path) or is_archive(dl_path) or is_archive_split(dl_path):
            return dl_path
        all_files = [dl_path] if self.is_file else []
        if not self.is_file:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    if (await get_document_type(f_path))[0]:
                        all_files.append(f_path)

        if not all_files:
            return dl_path

        ffmpeg = FFMpeg(self)
        async with task_dict_lock:
            task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Encode")

        self.progress = True
        eq = self.user_dict.get("ENC_QUALITY") or getattr(Config, "ENC_QUALITY", "")
        ec = self.user_dict.get("ENC_CRF") or getattr(Config, "ENC_CRF", "")
        ep = self.user_dict.get("ENC_PRESET") or getattr(Config, "ENC_PRESET", "")
        eco = self.user_dict.get("ENC_CODEC") or getattr(Config, "ENC_CODEC", "")
        er = self.user_dict.get("ENC_RESOLUTION") or getattr(Config, "ENC_RESOLUTION", "")
        ef = self.user_dict.get("ENC_FPS") or getattr(Config, "ENC_FPS", "")

        for f_path in all_files:
            if self.is_cancelled:
                return False
            LOGGER.info(f"Encoding video: {f_path}")
            res = await ffmpeg.encode_video(f_path, quality=eq, crf=ec, preset=ep, codec=eco, resolution=er, fps=ef)
            if res:
                await remove(f_path)
                await move(res, f_path)

        return dl_path

    async def proceed_compress_video(self, dl_path, gid):
        if not dl_path or not await aiopath.exists(dl_path) or is_archive(dl_path) or is_archive_split(dl_path):
            return dl_path
        all_files = [dl_path] if self.is_file else []
        if not self.is_file:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    if (await get_document_type(f_path))[0]:
                        all_files.append(f_path)

        if not all_files:
            return dl_path

        ffmpeg = FFMpeg(self)
        async with task_dict_lock:
            task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Compress")

        self.progress = True
        cq = self.user_dict.get("COM_QUALITY") or getattr(Config, "COM_QUALITY", "")
        cc = self.user_dict.get("COM_CRF") or getattr(Config, "COM_CRF", "")
        cp = self.user_dict.get("COM_PRESET") or getattr(Config, "COM_PRESET", "")
        ca = self.user_dict.get("COM_AUDIO_BITRATE") or getattr(Config, "COM_AUDIO_BITRATE", "")
        cac = self.user_dict.get("COM_AUDIO_CODEC") or getattr(Config, "COM_AUDIO_CODEC", "")

        for f_path in all_files:
            if self.is_cancelled:
                return False
            LOGGER.info(f"Compressing video: {f_path}")
            res = await ffmpeg.compress_video(f_path, quality=cq, crf=cc, preset=cp, audio_bitrate=ca, audio_codec=cac)
            if res:
                await remove(f_path)
                await move(res, f_path)

        return dl_path

    async def proceed_watermark(self, dl_path, gid):
        if not dl_path or not await aiopath.exists(dl_path) or is_archive(dl_path) or is_archive_split(dl_path):
            return dl_path
        all_files = [dl_path] if self.is_file else []
        if not self.is_file:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    if (await get_document_type(f_path))[0]:
                        all_files.append(f_path)

        if not all_files:
            return dl_path

        wm_user = self.user_dict.get("WM_USERNAME") or getattr(Config, "WM_USERNAME", "")
        wm_text = self.user_dict.get("WM_TEXT") or getattr(Config, "WM_TEXT", "")
        wm_img = self.user_dict.get("WM_IMAGE") or getattr(Config, "WM_IMAGE", "")
        wm_size = self.user_dict.get("WM_SIZE") or getattr(Config, "WM_SIZE", "")
        wm_color = self.user_dict.get("WM_COLOR") or getattr(Config, "WM_COLOR", "white")
        wm_img_pos = self.user_dict.get("WM_IMAGE_POSITION") or self.user_dict.get("WM_POSITION") or getattr(Config, "WM_POSITION", "Top-Left")
        wm_text_pos = self.user_dict.get("WM_TEXT_POSITION") or self.user_dict.get("WM_POSITION") or getattr(Config, "WM_POSITION", "Top-Left")

        disp_text = wm_text or (f"@{wm_user}" if wm_user else "")
        img_path = ""

        if wm_img:
            if wm_img.startswith(("http://", "https://")):
                downloaded = await download_image_thumb(wm_img)
                if downloaded and await aiopath.exists(downloaded):
                    img_path = downloaded
            elif await aiopath.exists(wm_img):
                img_path = wm_img

        if not disp_text and not img_path:
            return dl_path

        ffmpeg = FFMpeg(self)
        async with task_dict_lock:
            task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Watermark")

        self.progress = True
        for f_path in all_files:
            if self.is_cancelled:
                return False
            LOGGER.info(f"Applying watermark to: {f_path}")
            res = await ffmpeg.apply_watermark(
                f_path,
                text=disp_text,
                image_path=img_path,
                color=wm_color,
                size=wm_size,
                image_position=wm_img_pos,
                text_position=wm_text_pos,
            )
            if res:
                await remove(f_path)
                await move(res, f_path)

        if img_path and img_path.startswith(f"{DOWNLOAD_DIR}thumbnails"):
            with suppress(Exception):
                await remove(img_path)

        return dl_path

    async def proceed_compress(self, dl_path, gid):
        pswd = self.compress if isinstance(self.compress, str) else ""
        if self.is_leech and self.is_file:
            new_folder = ospath.splitext(dl_path)[0]
            if await aiopath.isfile(new_folder):
                new_folder = f"{new_folder}_temp"
            name = ospath.basename(dl_path)
            await makedirs(new_folder, exist_ok=True)
            new_dl_path = f"{new_folder}/{name}"
            await move(dl_path, new_dl_path)
            dl_path = new_dl_path
            up_path = f"{new_dl_path}.zip"
            self.is_file = False
        else:
            up_path = f"{dl_path}.zip"
        sevenz = SevenZ(self)
        async with task_dict_lock:
            task_dict[self.mid] = SevenZStatus(self, sevenz, gid, "Zip")
        return await sevenz.zip(dl_path, up_path, pswd)

    async def proceed_reorder(self, dl_path, gid):
        if not dl_path or not await aiopath.exists(dl_path):
            return dl_path
        all_files = [dl_path] if self.is_file else []
        if not self.is_file:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    fp = ospath.join(dirpath, file_)
                    is_vid, is_aud, _ = await get_document_type(fp)
                    if is_vid or is_aud:
                        all_files.append(fp)
        if not all_files:
            return dl_path

        ffmpeg = FFMpeg(self)
        aud_swaps = getattr(self, "reorder_aud", [])
        sub_swaps = getattr(self, "reorder_sub", [])
        aud_select = getattr(self, "aud_select", None)
        sub_select = getattr(self, "sub_select", None)
        aud_order = getattr(self, "aud_order", None)
        sub_order = getattr(self, "sub_order", None)

        if aud_swaps or sub_swaps or aud_select is not None or sub_select is not None or aud_order is not None or sub_order is not None:
            for f_path in all_files:
                if self.is_cancelled:
                    return False
                streams = await ffmpeg.get_streams(f_path)
                if not streams:
                    continue

                aud_streams = [s for s in streams if s.get("codec_type") == "audio"]
                sub_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

                if not aud_streams and not sub_streams:
                    continue

                async with task_dict_lock:
                    task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Reorder Streams")
                await ffmpeg.reorder_tracks(
                    f_path,
                    aud_swaps,
                    sub_swaps,
                    aud_select=aud_select,
                    sub_select=sub_select,
                    aud_order=aud_order,
                    sub_order=sub_order,
                )

        return dl_path

    async def proceed_trim(self, dl_path, gid):
        if not dl_path or not await aiopath.exists(dl_path):
            return dl_path
        trim_range = getattr(self, "trim_range", "")
        if not trim_range or "-" not in trim_range:
            return dl_path
        parts = trim_range.split("-")
        start_t = parts[0].strip()
        end_t = parts[1].strip()

        all_files = [dl_path] if self.is_file else []
        if not self.is_file:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    fp = ospath.join(dirpath, file_)
                    if (await get_document_type(fp))[0]:
                        all_files.append(fp)
        if not all_files:
            return dl_path

        ffmpeg = FFMpeg(self)
        for f_path in all_files:
            if self.is_cancelled:
                return False
            async with task_dict_lock:
                task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Trimming")
            await ffmpeg.trim_media(f_path, start_t, end_t)
        return dl_path

    async def proceed_extract_content(self, dl_path, gid):
        if not dl_path or not await aiopath.exists(dl_path):
            return dl_path
        extract_types = getattr(self, "extract_types", [])
        if not extract_types:
            return dl_path

        all_files = [dl_path] if self.is_file else []
        if not self.is_file:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    fp = ospath.join(dirpath, file_)
                    if (await get_document_type(fp))[0]:
                        all_files.append(fp)
        if not all_files:
            return dl_path

        ffmpeg = FFMpeg(self)
        for f_path in all_files:
            if self.is_cancelled:
                return False
            async with task_dict_lock:
                task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Extracting")
            await ffmpeg.extract_tracks(f_path, extract_types)

        if self.is_file:
            self.is_file = False
            return ospath.dirname(dl_path)
        return dl_path

    async def proceed_merge(self, dl_path, gid, custom_name=""):
        all_files = []
        if self.is_file:
            all_files.append(dl_path)
            work_dir = ospath.dirname(dl_path)
        else:
            work_dir = dl_path
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    all_files.append(ospath.join(dirpath, file_))

        if await aiopath.isdir(work_dir):
            for dirpath, _, files in await sync_to_async(walk, work_dir, topdown=False):
                for file_ in files:
                    fp = ospath.join(dirpath, file_)
                    if fp not in all_files:
                        all_files.append(fp)

        video_exts = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".m4v", ".ts", ".3gp")
        audio_exts = (".mp3", ".m4a", ".flac", ".aac", ".ac3", ".ogg", ".opus", ".wav", ".wma", ".eac3", ".mka")
        sub_exts = (".srt", ".ass", ".vtt", ".sub", ".idx")

        v_files = []
        a_files = []
        s_files = []

        for fp in all_files:
            ext = ospath.splitext(fp)[1].lower()
            if ext in video_exts or (await get_document_type(fp))[0]:
                if fp not in v_files:
                    v_files.append(fp)
            elif ext in audio_exts or (await get_document_type(fp))[1]:
                if fp not in a_files:
                    a_files.append(fp)
            elif ext in sub_exts:
                if fp not in s_files:
                    s_files.append(fp)

        def natural_key(text):
            return [
                int(c) if c.isdigit() else c.lower()
                for c in re.split(r"(\d+)", text)
            ]

        v_files.sort(key=lambda x: natural_key(ospath.basename(x)))
        a_files.sort(key=lambda x: natural_key(ospath.basename(x)))
        s_files.sort(key=lambda x: natural_key(ospath.basename(x)))

        # Merge policy: a video is mandatory. Audio and subtitles are optional.
        # Use every available audio/subtitle input when a video is present.
        # Never attempt an audio-only or subtitle-only merge.
        if not v_files:
            LOGGER.info(
                "Merge skipped: video is required; found %d audio and %d subtitle files.",
                len(a_files), len(s_files),
            )
            return dl_path

        total_inputs = len(v_files) + len(a_files) + len(s_files)
        if total_inputs < 2 and len(v_files) < 2:
            LOGGER.info("Merge skipped: video only; no additional tracks to merge.")
            if custom_name and len(v_files) == 1:
                single_v = v_files[0]
                parent_d = ospath.dirname(single_v)
                v_ext = ospath.splitext(single_v)[1]
                target_n = custom_name if custom_name.lower().endswith(v_ext.lower()) else f"{custom_name}{v_ext}"
                target_p = ospath.join(parent_d, target_n)
                if single_v != target_p:
                    await move(single_v, target_p)
                    self.name = target_n
                    return target_p
            return dl_path

        if custom_name:
            out_base = custom_name
        elif self.extract and getattr(self, "name", ""):
            out_base = self.name
        else:
            main_f = v_files[0] if v_files else (a_files[0] if a_files else all_files[0])
            out_base = ospath.basename(main_f)

        for non_vid_ext in [".zip", ".7z", ".rar", ".tar", ".gz", ".xz", ".pdf", ".txt", ".bin", ".tmp", ".001", ".part1"]:
            if out_base.lower().endswith(non_vid_ext):
                out_base = out_base[:-len(non_vid_ext)]

        out_ext = ospath.splitext(out_base)[1].lower()
        if out_ext not in video_exts:
            out_base = ospath.splitext(out_base)[0] if out_ext else out_base
            out_filename = f"{out_base}.mkv"
        else:
            out_filename = out_base

        merge_mode = getattr(self, "merge_mode", None) or self.user_dict.get("AUTO_MERGE_MODE") or getattr(Config, "AUTO_MERGE_MODE", "normal")
        if merge_mode == "advanced" and len(v_files) > 1:
            from bot import planner_tasks, bot_loop
            from web.wserver import planner_store
            key = f"{self.mid}_{self.user_id}"
            fut = bot_loop.create_future()

            files_to_plan = v_files
            file_map = {ospath.basename(f): f for f in files_to_plan}
            file_names = list(file_map.keys())

            from time import time
            planner_info = {
                "mid": self.mid,
                "user_id": self.user_id,
                "files": file_names,
                "orig_files": list(file_names),
                "file_map": file_map,
                "output_filename": out_filename,
                "saved": False,
                "future": fut,
                "created_at": time(),
                "timeout_seconds": 600,
            }
            planner_tasks[key] = planner_info
            planner_store[key] = planner_info

            def format_planner_ui(p_info, is_dm=True, page=1):
                cur_files = p_info.get("files", [])
                cur_out = p_info.get("output_filename", out_filename)
                page_size = 10
                total_files = len(cur_files)
                total_pages = max(1, (total_files + page_size - 1) // page_size)
                page = max(1, min(page, total_pages))
                p_info["page"] = page

                start_idx = (page - 1) * page_size
                end_idx = min(start_idx + page_size, total_files)
                page_files = cur_files[start_idx:end_idx]

                msg_text = (
                    f"<b>🧩 Merge Planner</b>\n\n"
                    f"• <b>Output Filename:</b> <code>{escape(cur_out)}</code>\n"
                    f"• <b>Files to Merge ({total_files}):</b> [Page {page}/{total_pages}]\n"
                    + "\n".join([f"{start_idx + idx + 1}. {escape(fn)}" for idx, fn in enumerate(page_files)])
                    + "\n\n<i>Reorder files below or edit output filename.</i>"
                )
                buttons = ButtonMaker()

                for idx, fn in enumerate(page_files):
                    global_idx = start_idx + idx
                    up_cb = f"plcb move {p_info['mid']} {global_idx} -1 {page}" if global_idx > 0 else "plcb dummy"
                    dn_cb = f"plcb move {p_info['mid']} {global_idx} 1 {page}" if global_idx < total_files - 1 else "plcb dummy"
                    rm_cb = f"plcb rmfile {p_info['mid']} {global_idx} {page}"
                    buttons.data_button(f"#{global_idx + 1} ⬆️", up_cb)
                    buttons.data_button(f"#{global_idx + 1} ⬇️", dn_cb)
                    buttons.data_button(f"❌ #{global_idx + 1}", rm_cb)

                if total_pages > 1:
                    prev_page = page - 1 if page > 1 else total_pages
                    next_page = page + 1 if page < total_pages else 1
                    buttons.data_button("◀️ Prev", f"plcb page {p_info['mid']} {prev_page}")
                    buttons.data_button(f"Page {page}/{total_pages}", "plcb dummy")
                    buttons.data_button("Next ▶️", f"plcb page {p_info['mid']} {next_page}")

                buttons.data_button("🔄 Reset Order", f"plcb reset {p_info['mid']}")
                buttons.data_button("✏️ Rename Output", f"plcb name {p_info['mid']}")
                buttons.data_button("💾 Save Order", f"plcb save {p_info['mid']}")
                buttons.data_button("🗑️ Delete Session", f"plcb delete {p_info['mid']}")

                return msg_text, buttons.build_menu(3)

            planner_msg_text, markup = format_planner_ui(planner_info, is_dm=True)

            try:
                dm_msg = await TgClient.bot.send_message(
                    chat_id=self.user_id,
                    text=planner_msg_text,
                    reply_markup=markup,
                )
            except Exception as e:
                LOGGER.warning(f"Failed to send planner DM: {e}")
                planner_msg_text, group_markup = format_planner_ui(planner_info, is_dm=False)
                dm_msg = await send_message(
                    self.message,
                    planner_msg_text,
                    group_markup,
                )

            planner_info["msg"] = dm_msg

            async def on_save(p_data):
                b_save = ButtonMaker()
                b_save.data_button("🚀 Start Merging", f"startmerge {self.mid}")
                updated_files = p_data.get("files", file_names)
                updated_out = p_data.get("output_filename", out_filename)
                save_text = (
                    f"<b>🧩 Merge Planner (Saved)</b>\n\n"
                    f"• <b>Configured Output:</b> <code>{escape(updated_out)}</code>\n"
                    f"• <b>Configured File Order:</b>\n"
                    + "\n".join([f"{idx + 1}. {escape(fn)}" for idx, fn in enumerate(updated_files)])
                    + "\n\n<i>Click button below to start merging.</i>"
                )
                await edit_message(dm_msg, save_text, b_save.build_menu(1))

            async def on_delete(p_data):
                if not fut.done():
                    fut.set_result(False)
                await edit_message(dm_msg, "<b>🗑️ Merge Planner Deleted. Using default merge order.</b>")

            planner_info["on_save_cb"] = on_save
            planner_info["on_delete_cb"] = on_delete
            planner_info["format_ui"] = format_planner_ui

            try:
                from asyncio import wait_for, TimeoutError as AsyncTimeoutError
                res = await wait_for(fut, timeout=600)
                if res and planner_info.get("saved"):
                    ordered_names = planner_info.get("files", [])
                    v_files = [file_map[fn] for fn in ordered_names if fn in file_map]
                    if p_out := planner_info.get("output_filename"):
                        out_filename = p_out
            except AsyncTimeoutError:
                LOGGER.info(f"Merge Planner timed out after 10 min for {key}. Auto-saving default configuration.")
                planner_info["saved"] = True
                ordered_names = planner_info.get("files", file_names)
                v_files = [file_map[fn] for fn in ordered_names if fn in file_map]
                if p_out := planner_info.get("output_filename"):
                    out_filename = p_out
                with suppress(Exception):
                    await edit_message(
                        dm_msg,
                        f"<b>⏰ Merge Planner Timed Out (10 min)</b>\n\n"
                        f"Automatically proceeding with current file order and default output: <code>{escape(out_filename)}</code>"
                    )
            except Exception as e:
                LOGGER.error(f"Error in Planner execution: {e}")
            finally:
                planner_tasks.pop(key, None)

        if not v_files and not a_files and not s_files:
            LOGGER.info("Merge Planner left 0 files. Returning dl_path.")
            return dl_path

        if len(v_files) == 1 and not a_files and not s_files:
            LOGGER.info("Merge Planner left only 1 video file. Returning single file.")
            single_v = v_files[0]
            if out_filename:
                parent_d = ospath.dirname(single_v)
                v_ext = ospath.splitext(single_v)[1]
                target_n = out_filename if out_filename.lower().endswith(v_ext.lower()) else f"{out_filename}{v_ext}"
                target_p = ospath.join(parent_d, target_n)
                if single_v != target_p:
                    await move(single_v, target_p)
                    self.name = target_n
                    return target_p
            return single_v

        self.name = out_filename
        output_file = ospath.join(work_dir, out_filename)

        ffmpeg = FFMpeg(self)
        async with task_dict_lock:
            task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Merge")

        a_langs = []
        for af in a_files:
            if self.extract:
                a_langs.append("eng")
                continue
            prompt_str = f"<b>🗣️ Track Language:</b>\nPlease send the language name for audio track: <code>{ospath.basename(af)}</code>\n⏱️ <i>Timeout: 30s</i>"
            prompt_msg = await send_message(self.user_id, prompt_str)
            lang = "eng"
            if prompt_msg and isinstance(prompt_msg, Message):
                event_done = TgClient.bot.loop.create_future()
                user_lang = []

                async def lang_filter(_, __, event):
                    u = event.from_user or event.sender_chat
                    return bool(u and u.id == self.user_id and event.chat.id == prompt_msg.chat.id and event.text)

                async def lang_handler(_, msg):
                    user_lang.append(msg.text.strip())
                    await delete_message(msg)
                    if not event_done.done():
                        event_done.set_result(True)

                from pyrogram.handlers import MessageHandler
                from pyrogram.filters import create
                h = TgClient.bot.add_handler(MessageHandler(lang_handler, filters=create(lang_filter)), group=-1)
                try:
                    await wait_for(event_done, timeout=30)
                    if user_lang:
                        lang = user_lang[0]
                except Exception:
                    pass
                finally:
                    TgClient.bot.remove_handler(*h)
                    await delete_message(prompt_msg)
            a_langs.append(lang)

        s_langs = []
        for sf in s_files:
            if self.extract:
                s_langs.append("eng")
                continue
            prompt_str = f"<b>📝 Track Language:</b>\nPlease send the language name for subtitle track: <code>{ospath.basename(sf)}</code>\n⏱️ <i>Timeout: 30s</i>"
            prompt_msg = await send_message(self.user_id, prompt_str)
            lang = "eng"
            if prompt_msg and isinstance(prompt_msg, Message):
                event_done = TgClient.bot.loop.create_future()
                user_lang = []

                async def lang_filter(_, __, event):
                    u = event.from_user or event.sender_chat
                    return bool(u and u.id == self.user_id and event.chat.id == prompt_msg.chat.id and event.text)

                async def lang_handler(_, msg):
                    user_lang.append(msg.text.strip())
                    await delete_message(msg)
                    if not event_done.done():
                        event_done.set_result(True)

                from pyrogram.handlers import MessageHandler
                from pyrogram.filters import create
                h = TgClient.bot.add_handler(MessageHandler(lang_handler, filters=create(lang_filter)), group=-1)
                try:
                    await wait_for(event_done, timeout=30)
                    if user_lang:
                        lang = user_lang[0]
                except Exception:
                    pass
                finally:
                    TgClient.bot.remove_handler(*h)
                    await delete_message(prompt_msg)
            s_langs.append(lang)

        LOGGER.info(
            f"Merging {len(v_files)} video(s) + {len(a_files)} audio track(s) + "
            f"{len(s_files)} subtitle track(s) into {output_file}; "
            "video required, optional tracks included when available."
        )
        self.progress = True
        res = await ffmpeg.merge_tracks(v_files, a_files, s_files, output_file, gid, a_langs=a_langs, s_langs=s_langs)

        if res and await aiopath.exists(output_file):
            save_files = self.user_dict.get("SAVE_FILES", False) or getattr(Config, "SAVE_FILES", False)
            if not save_files:
                merged_sources = v_files + a_files + s_files
                for sf in merged_sources:
                    if sf != output_file:
                        with suppress(Exception):
                            await remove(sf)

                if work_dir != dl_path:
                    for root, dirs, files in await sync_to_async(walk, work_dir, topdown=False):
                        for d in dirs:
                            dp = ospath.join(root, d)
                            if not await listdir(dp):
                                with suppress(Exception):
                                    await rmtree(dp)

                self.is_file = True
                return output_file
            else:
                self.is_file = False
                self.name = ospath.basename(work_dir)
                return work_dir

        return dl_path

    async def proceed_split(self, dl_path, gid):
        self.files_to_proceed = {}
        if self.is_file:
            f_size = await get_path_size(dl_path)
            if f_size > self.split_size:
                self.files_to_proceed[dl_path] = [f_size, ospath.basename(dl_path)]
        else:
            for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    f_size = await get_path_size(f_path)
                    if f_size > self.split_size:
                        self.files_to_proceed[f_path] = [f_size, file_]
        if self.files_to_proceed:
            ffmpeg = FFMpeg(self)
            async with task_dict_lock:
                task_dict[self.mid] = FFmpegStatus(self, ffmpeg, gid, "Split")
            LOGGER.info(f"Splitting: {self.name}")
            for f_path, (f_size, file_) in self.files_to_proceed.items():
                self.proceed_count += 1
                if self.is_file:
                    self.subsize = self.size
                else:
                    self.subsize = f_size
                    self.subname = file_
                parts = -(-f_size // self.split_size)
                if self.equal_splits:
                    split_size = (f_size // parts) + (f_size % parts)
                else:
                    split_size = self.split_size
                if not self.as_doc and (await get_document_type(f_path))[0]:
                    self.progress = True
                    res = await ffmpeg.split(f_path, file_, parts, split_size)
                else:
                    self.progress = False
                    res = await split_file(f_path, split_size, self)
                if self.is_cancelled:
                    return False
                if res or f_size >= self.max_split_size:
                    try:
                        await remove(f_path)
                    except Exception:
                        self.is_cancelled = True

    def parse_metadata_string(self, metadata_str):
        return self.metadata_processor.parse_string(metadata_str)

    def merge_metadata_dicts(self, default_dict, cmd_dict):
        return self.metadata_processor.merge_dicts(default_dict, cmd_dict)
