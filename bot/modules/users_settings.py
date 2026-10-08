from asyncio import sleep
from ast import literal_eval
from pyrogram.enums import ButtonStyle
from functools import partial
from html import escape
from io import BytesIO
import json
import os
from os import getcwd
from contextlib import suppress
from re import sub
from time import time
import zipfile
from aiofiles.os import makedirs, remove, rename
from aiofiles.os import path as aiopath
from aioshutil import move
from langcodes import Language
from pyrogram.filters import create
from pyrogram.handlers import MessageHandler
from pyrogram.types import ReplyParameters


from .. import auth_chats, excluded_extensions, sudo_users, user_data
from ..core.config_manager import Config
from ..core.seedr_client import SeedrClient
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import (
    get_size_bytes,
    new_task,
    update_user_ldata,
)
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.mega_utils import get_mega_account_info
from ..helper.ext_utils.media_utils import create_thumb, download_image_thumb
from ..helper.ext_utils.status_utils import get_readable_file_size
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.ext_utils.cookie_utils import (
    describe_cookie_report,
    normalize_cookie_file,
)
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_file,
    send_message,
)

handler_dict = {}

leech_options = [
    "THUMBNAIL",
    "LEECH_SPLIT_SIZE",
    "LEECH_DUMP_CHAT",
    "LEECH_PREFIX",
    "LEECH_SUFFIX",
    "LEECH_CAPTION",
    "LEECH_FONT",
    "THUMBNAIL_LAYOUT",
]
uphoster_options = [
    "GOFILE_TOKEN",
    "GOFILE_FOLDER_ID",
    "BUZZHEAVIER_TOKEN",
    "BUZZHEAVIER_FOLDER_ID",
    "PIXELDRAIN_KEY",
    "DEVUPLOADS_KEY",
    "DEVUPLOADS_FOLDER",
    "VIKINGFILE_HASH",
    "VIKINGFILE_FOLDER",
    "GDFLIX_UPLOAD_URL", "GDFLIX_API_KEY",
    "HUBCLOUD_UPLOAD_URL", "HUBCLOUD_API_KEY",
    "FILEPRESS_UPLOAD_URL", "FILEPRESS_API_KEY",
    "LULUSTREAM_UPLOAD_URL", "LULUSTREAM_API_KEY",
    "STREAMTAPE_UPLOAD_URL", "STREAMTAPE_API_KEY",
    "FILEMOON_UPLOAD_URL", "FILEMOON_API_KEY",
    "UPLOADHUB_UPLOAD_URL", "UPLOADHUB_API_KEY",
    "FILESTREAMS_UPLOAD_URL", "FILESTREAMS_API_KEY",
]
rclone_options = ["RCLONE_CONFIG", "RCLONE_PATH", "RCLONE_FLAGS"]
gdrive_options = ["TOKEN_PICKLE", "GDRIVE_ID", "INDEX_URL", "DRIVE_CAT"]
ffset_options = [
    "FFMPEG_CMDS",
    "SET_ALL_METADATA",
    "METADATA",
    "AUDIO_METADATA",
    "VIDEO_METADATA",
    "SUBTITLE_METADATA",
]
advanced_options = [
    "EXCLUDED_EXTENSIONS",
    "NAME_SWAP",
    "AUTO_RENAME_FORMAT",
    "YT_DLP_OPTIONS",
    "UPLOAD_PATHS",
    "USER_COOKIE_FILE",
    "TELEGRAM_SESSION_STRING",
]
yt_options = ["YT_DESP", "YT_TAGS", "YT_CATEGORY_ID", "YT_PRIVACY_STATUS"]
mega_options = ["MEGA_EMAIL", "MEGA_PASSWORD"]
seedr_options = ["SEEDR_EMAIL", "SEEDR_PASSWORD", "SEEDR_DELETE_FOLDER"]

user_settings_text = {
    "THUMBNAIL": (
        "Photo or Document",
        "Custom thumbnail used when uploading files to Telegram in Media or Document mode.",
        "<blockquote>Send a photo to set as custom thumbnail.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "RCLONE_CONFIG": (
        "File",
        "Your rclone.conf file for Rclone cloud storage uploads.",
        "<blockquote>Send your <code>rclone.conf</code> file.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "TOKEN_PICKLE": (
        "File",
        "Your token.pickle file for Google Drive API uploads.",
        "<blockquote>Send your <code>token.pickle</code> file.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "LEECH_SPLIT_SIZE": (
        "Number / Size String",
        "Maximum file split size limit for Telegram uploads.",
        f"<blockquote>Send split size (e.g. 2gb, 500mb, or bytes).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "LEECH_DUMP_CHAT": (
        "Chat ID / Username / PM",
        "Destination chat ID or username for Telegram uploads.",
        """<blockquote>Send destination chat ID, @username, or pm.
• b:id/@username (Leech via Bot)
• u:id/@username (Leech via User session)
• h:id/@username (Hybrid size upload)
• id/@username|topic_id (Specific topic)
⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>""",
    ),
    "LEECH_PREFIX": (
        "Text",
        "Prefix added to beginning of leeched filenames.",
        "<blockquote>Send Filename Prefix text.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "LEECH_SUFFIX": (
        "Text",
        "Suffix added to end of leeched filenames.",
        "<blockquote>Send Filename Suffix text.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "LEECH_CAPTION": (
        "Text",
        "Custom caption added to uploaded Telegram files.",
        "<blockquote>Send custom caption text.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "THUMBNAIL_LAYOUT": (
        "Dimensions (WxH)",
        "Grid layout format for video thumbnail screenshots.",
        "<blockquote>Send thumbnail grid layout (e.g. 3x3, 2x2).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "RCLONE_PATH": (
        "Remote Path",
        "Default Rclone upload path (e.g. remote:folder).",
        "<blockquote>Send default Rclone path.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "RCLONE_FLAGS": (
        "Key-Value Flags",
        "Custom flags appended to Rclone execution.",
        "<blockquote>Send rclone flags (e.g. --buffer-size:8M|--drive-starred-only).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "GDRIVE_ID": (
        "Drive ID",
        "Default Google Drive folder ID for uploads.",
        "<blockquote>Send Google Drive folder ID.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "INDEX_URL": (
        "URL",
        "Google Drive Index mirror URL.",
        "<blockquote>Send Index mirror URL.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "UPLOAD_PATHS": (
        "Dict",
        "Predefined dictionary of upload paths.",
        "<blockquote>Send dictionary of path shortcuts.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "EXCLUDED_EXTENSIONS": (
        "Extensions",
        "Space-separated file extensions to exclude from upload.",
        "<blockquote>Send excluded extensions separated by space (e.g. txt iso zip).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "NAME_SWAP": (
        "Pattern Rules",
        "Filename text substitution rules.",
        "<blockquote>Send substitution rules in format: <code>word1/word2/s</code>\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "AUTO_RENAME_FORMAT": (
        "Template String",
        "Format template for auto renaming media files.",
        "<blockquote>Send custom rename format template (e.g. <code>{TITLE} - {SEASON} {EPISODE} {QUALITY}</code>).\nPlaceholders: {TITLE}, {SEASON}, {EPISODE}, {QUALITY}, {YEAR}, {LANGUAGE}, {CODEC}, {AUDIO}, {GROUP}, {EXT}\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "YT_DLP_OPTIONS": (
        "Dict",
        "Custom yt-dlp option dictionary.",
        "<blockquote>Send yt-dlp options dictionary.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "FFMPEG_CMDS": (
        "Configured Language / Command keys",
        "Available FFmpeg command presets.",
        "<blockquote>Select or view configured FFmpeg keys.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "FFMPEG_DUMP": (
        "Key-Value mapping (KEY: DUMP_ID)",
        "Separate dump destination per key.",
        "<blockquote>Send key and dump destination (e.g., <code>TEL: -100123456789</code>).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "METADATA_CMDS": (
        "Text",
        "Metadata tagging configuration.",
        "<blockquote>Send metadata configuration parameters.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "METADATA": (
        "Key-Value string",
        "Apply metadata to all media files.",
        """<blockquote>Send metadata string format: <code>key=value|key2=value2</code>
⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>""",
    ),
    "SET_ALL_METADATA": (
        "Key-Value string",
        "Global stream metadata override.",
        """<blockquote>Send global metadata format: <code>key=value|key2=value2</code>
⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>""",
    ),
    "AUDIO_METADATA": (
        "Key-Value string",
        "Audio stream metadata.",
        "<blockquote>Send audio metadata format: <code>key=value</code>\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "VIDEO_METADATA": (
        "Key-Value string",
        "Video stream metadata.",
        "<blockquote>Send video metadata format: <code>key=value</code>\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "SUBTITLE_METADATA": (
        "Key-Value string",
        "Subtitle stream metadata.",
        "<blockquote>Send subtitle metadata format: <code>key=value</code>\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "YT_DESP": (
        "String",
        "Custom YouTube upload description.",
        "<blockquote>Send custom YouTube description.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "YT_TAGS": (
        "Comma-separated list",
        "Custom tags for YouTube uploads.",
        "<blockquote>Send comma-separated YouTube tags.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "YT_CATEGORY_ID": (
        "Number",
        "YouTube category ID.",
        "<blockquote>Send YouTube category ID number.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "YT_PRIVACY_STATUS": (
        "public / private / unlisted",
        "Privacy status for YouTube videos.",
        "<blockquote>Send privacy status: public, private, or unlisted.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "TELEGRAM_SESSION_STRING": (
        "Telegram Session String",
        "Optional personal Telegram user session. It is stored privately and used only for the enabled Telegram-link download and/or upload mode.",
        "<blockquote>Send your Telegram session string. It will not be displayed back in the chat.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "USER_COOKIE_FILE": (
        "File",
        "Cookies file for yt-dlp authentication.",
        "<blockquote>Send cookie file (cookies.txt).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "GOFILE_TOKEN": (
        "String",
        "Gofile API Token",
        "<blockquote>Send Gofile API Token.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "GOFILE_FOLDER_ID": (
        "String",
        "Gofile Folder ID",
        "<blockquote>Send Gofile Folder ID.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "BUZZHEAVIER_TOKEN": (
        "String",
        "BuzzHeavier API Token",
        "<blockquote>Send BuzzHeavier API Token.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "BUZZHEAVIER_FOLDER_ID": (
        "String",
        "BuzzHeavier Folder ID",
        "<blockquote>Send BuzzHeavier Folder ID.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "PIXELDRAIN_KEY": (
        "String",
        "PixelDrain API Key",
        "<blockquote>Send PixelDrain API Key.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "DEVUPLOADS_KEY": (
        "String",
        "DevUploads API Key",
        "<blockquote>Send DevUploads API Key.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "DEVUPLOADS_FOLDER": (
        "String",
        "DevUploads Folder ID",
        "<blockquote>Send DevUploads Folder ID.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "VIKINGFILE_HASH": (
        "String",
        "VikingFile User Hash",
        "<blockquote>Send VikingFile Hash.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "VIKINGFILE_FOLDER": (
        "String",
        "VikingFile Folder Name",
        "<blockquote>Send VikingFile folder name.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "MEGA_EMAIL": (
        "String",
        "Mega.nz account email address.",
        "<blockquote>Send Mega.nz email address.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "MEGA_PASSWORD": (
        "String",
        "Mega.nz account password.",
        "<blockquote>Send Mega.nz account password.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "SEEDR_EMAIL": (
        "String",
        "Seedr.cc account email address.",
        "<blockquote>Send Seedr.cc email address.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "SEEDR_PASSWORD": (
        "String",
        "Seedr.cc account password.",
        "<blockquote>Send Seedr.cc account password.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "DRIVE_CAT": (
        "Dict",
        "User-defined GDrive categories dictionary.",
        "<blockquote>Send drive category dictionary.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "ENC_QUALITY": (
        "String/Number",
        "Video encoding quality setting.",
        "<blockquote>Send Encoding Quality (e.g. 1080p, 720p, High).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "ENC_CRF": (
        "Number",
        "Constant Rate Factor for encoding.",
        "<blockquote>Send CRF value (e.g. 18, 23, 28).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "ENC_PRESET": (
        "String",
        "FFmpeg encoding preset.",
        "<blockquote>Send Preset (e.g. ultrafast, fast, medium, slow).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "ENC_CODEC": (
        "String",
        "Video encoder codec.",
        "<blockquote>Send Video Codec (e.g. libx264, libx265, libvpx-vp9, copy).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "ENC_RESOLUTION": (
        "String",
        "Target video resolution.",
        "<blockquote>Send Resolution (e.g. 1920x1080, 1280x720).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "ENC_FPS": (
        "Number",
        "Target frames per second.",
        "<blockquote>Send FPS value (e.g. 24, 30, 60).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "COM_QUALITY": (
        "String/Number",
        "Video compression quality setting.",
        "<blockquote>Send Compression Quality (e.g. Medium, High).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "COM_CRF": (
        "Number",
        "Constant Rate Factor for compression.",
        "<blockquote>Send Compression CRF value (e.g. 26, 28, 30).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "COM_PRESET": (
        "String",
        "FFmpeg compression preset.",
        "<blockquote>Send Preset (e.g. faster, fast, medium).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "COM_AUDIO_BITRATE": (
        "String",
        "Audio bitrate for compression.",
        "<blockquote>Send Audio Bitrate (e.g. 128k, 192k).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "COM_AUDIO_CODEC": (
        "String",
        "Audio codec for compression.",
        "<blockquote>Send Audio Codec (e.g. aac, mp3, opus, copy).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "WM_USERNAME": (
        "String",
        "Watermark username text.",
        "<blockquote>Send Watermark Username text.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "WM_TEXT": (
        "String",
        "Watermark display text.",
        "<blockquote>Send Watermark Text.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "WM_IMAGE": (
        "Photo or Image URL",
        "Watermark image overlay.",
        "<blockquote>Send photo or Image URL for watermark.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "WM_COLOR": (
        "String/Hex",
        "Color for text watermark.",
        "<blockquote>Send text watermark color name or hex code (e.g. white, yellow, #FF0000).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "WM_SIZE": (
        "Number / Width Dimension",
        "Font size for text watermark or width for image watermark.",
        "<blockquote>Send Font Size (e.g. 24, 30) or Image Width (e.g. 150, 200).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "THUMB_WM_TEXT": (
        "String",
        "Thumbnail watermark display text.",
        "<blockquote>Send Thumbnail Watermark Text.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "THUMB_WM_SIZE": (
        "Number",
        "Font size or scale percentage for thumbnail watermark.",
        "<blockquote>Send Thumbnail Watermark size/font size (e.g. 24, 30).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "THUMB_WM_IMAGE": (
        "Photo or Image URL",
        "Thumbnail watermark overlay image.",
        "<blockquote>Send photo or Image URL for thumbnail watermark.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "THUMB_WM_COLOR": (
        "String/Hex",
        "Color for thumbnail text watermark.",
        "<blockquote>Send text watermark color name or hex code (e.g. white, yellow, #FF0000).\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>",
    ),
    "WM_IMAGE_POSITION": (
        "String",
        "Position for image watermark.",
        "<blockquote>Select position for image watermark.</blockquote>",
    ),
    "WM_TEXT_POSITION": (
        "String",
        "Position for text watermark.",
        "<blockquote>Select position for text watermark.</blockquote>",
    ),
    "THUMB_WM_IMAGE_POSITION": (
        "String",
        "Position for thumbnail image watermark.",
        "<blockquote>Select position for thumbnail image watermark.</blockquote>",
    ),
    "THUMB_WM_TEXT_POSITION": (
        "String",
        "Position for thumbnail text watermark.",
        "<blockquote>Select position for thumbnail text watermark.</blockquote>",
    ),
}


async def get_user_settings(from_user, stype="main"):
    user_id = from_user.id
    user_name = from_user.mention(style="html")
    buttons = ButtonMaker()
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"
    user_dict = user_data.get(user_id, {})
    auto_thumb = "Disabled"

    if stype == "main":
        buttons.data_button(
            "⚙️ General Settings", f"userset {user_id} general", position="header"
        )
        buttons.data_button("☁️ Mirror Settings", f"userset {user_id} mirror")
        buttons.data_button("📦 Leech Settings", f"userset {user_id} leech")
        buttons.data_button("🎬 ENC & COM & WATERMARK", f"userset {user_id} enc_com_wm")
        buttons.data_button("🎬 Video Tools", f"userset {user_id} vtools")
        buttons.data_button("🌐 Uphoster Settings", f"userset {user_id} uphoster")
        buttons.data_button("🎞️ FF Media Settings", f"userset {user_id} ffset")
        buttons.data_button(
            "🛠️ Misc Settings", f"userset {user_id} advanced", position="l_body"
        )

        buttons.data_button("📤 Export Settings", f"userset {user_id} export_settings", position="footer")
        buttons.data_button("📥 Import Settings", f"userset {user_id} import_settings", position="footer")

        if user_dict and any(
            key in user_dict
            for key in list(user_settings_text.keys())
            + [
                "USER_TOKENS",
                "AS_DOCUMENT",
                "AUTO_THUMBNAIL",
                "EQUAL_SPLITS",
                "MEDIA_GROUP",
                "STOP_DUPLICATE",
                "DEFAULT_UPLOAD",
                "AUTO_MERGE",
                "SPLIT_MODE",
                "AUTO_LEECH",
                "AUTO_MIRROR",
                "AUTO_DDL",
                "SAVE_FILES",
            ]
        ):
            buttons.data_button(
                "♻️ Reset All", f"userset {user_id} confirm_reset_all", position="footer"
            )
        buttons.data_button(
            "❌ Close",
            f"userset {user_id} close",
            position="footer",
            style=ButtonStyle.DANGER,
        )

        text = f"""<b>👤 User Personal Settings</b>

<blockquote>• <b>Name:</b> {user_name}
• <b>User ID:</b> <code>#ID{user_id}</code>
• <b>Username:</b> @{from_user.username or 'N/A'}
• <b>Telegram DC:</b> {from_user.dc_id or 'N/A'}
• <b>Language:</b> {Language.get(lc).display_name() if (lc := from_user.language_code) else "N/A"}</blockquote>"""

        btns = buttons.build_menu(2)

    elif stype == "general":
        if user_dict.get("DEFAULT_UPLOAD", ""):
            default_upload = user_dict["DEFAULT_UPLOAD"]
        elif "DEFAULT_UPLOAD" not in user_dict:
            default_upload = Config.DEFAULT_UPLOAD
        du = "GDRIVE API" if default_upload == "gd" else "RCLONE"
        dur = "GDRIVE API" if default_upload != "gd" else "RCLONE"
        buttons.data_button(
            f"Swap to {dur} Mode", f"userset {user_id} {default_upload}"
        )

        user_tokens = user_dict.get("USER_TOKENS", False)
        tr = "USER" if user_tokens else "OWNER"
        trr = "OWNER" if user_tokens else "USER"
        buttons.data_button(
            f"Swap to {trr} token/config",
            f"userset {user_id} tog USER_TOKENS {'f' if user_tokens else 't'}",
        )

        buttons.data_button("◀️ Back", f"userset {user_id} back", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )

        def_cookies = user_dict.get("USE_DEFAULT_COOKIE", False)
        cookie_mode = "Owner's Cookie" if def_cookies else "User's Cookie"
        buttons.data_button(
            f"Swap to {'OWNER' if not def_cookies else 'USER'}'s Cookie File",
            f"userset {user_id} tog USE_DEFAULT_COOKIE {'f' if def_cookies else 't'}",
        )
        btns = buttons.build_menu(2)

        text = f"""<b>⚙️ General User Settings</b>

<blockquote>• <b>Name:</b> {user_name}
• <b>Default Upload Engine:</b> <b>{du}</b>
• <b>Token Credentials Mode:</b> <b>{tr}'s</b> token/config
• <b>YT Cookie Source:</b> <b>{cookie_mode}</b></blockquote>"""

    elif stype == "leech":
        thumbpath = f"thumbnails/{user_id}.jpg"
        has_thumb = await aiopath.exists(thumbpath)
        thumb_mode = user_dict.get("THUMBNAIL_MODE", "custom" if has_thumb else "none")
        buttons.data_button("Thumbnail", f"userset {user_id} thumb_select")
        thumbmsg = f"{thumb_mode.title()} ({'Exists' if has_thumb else 'Not Exists'})"
        buttons.data_button(
            "Leech Split Size", f"userset {user_id} menu LEECH_SPLIT_SIZE"
        )
        if user_dict.get("LEECH_SPLIT_SIZE", False):
            split_size = user_dict["LEECH_SPLIT_SIZE"]
        else:
            split_size = Config.LEECH_SPLIT_SIZE
        buttons.data_button(
            "Leech Destination", f"userset {user_id} menu LEECH_DUMP_CHAT"
        )
        if user_dict.get("LEECH_DUMP_CHAT", False):
            leech_dest = user_dict["LEECH_DUMP_CHAT"]
        elif "LEECH_DUMP_CHAT" not in user_dict and Config.LEECH_LOG_CHAT:
            leech_dest = Config.LEECH_LOG_CHAT
        else:
            leech_dest = "None"
        buttons.data_button("Leech Prefix", f"userset {user_id} menu LEECH_PREFIX")
        if user_dict.get("LEECH_PREFIX", False):
            lprefix = user_dict["LEECH_PREFIX"]
        elif "LEECH_PREFIX" not in user_dict and Config.LEECH_PREFIX:
            lprefix = Config.LEECH_PREFIX
        else:
            lprefix = "Not Exists"
        buttons.data_button("Leech Suffix", f"userset {user_id} menu LEECH_SUFFIX")
        if user_dict.get("LEECH_SUFFIX", False):
            lsuffix = user_dict["LEECH_SUFFIX"]
        elif "LEECH_SUFFIX" not in user_dict and Config.LEECH_SUFFIX:
            lsuffix = Config.LEECH_SUFFIX
        else:
            lsuffix = "Not Exists"

        buttons.data_button("Leech Caption", f"userset {user_id} menu LEECH_CAPTION")
        if user_dict.get("LEECH_CAPTION", False):
            lcap = user_dict["LEECH_CAPTION"]
        elif "LEECH_CAPTION" not in user_dict and Config.LEECH_CAPTION:
            lcap = Config.LEECH_CAPTION
        else:
            lcap = "Not Exists"

        buttons.data_button("Caption Font", f"userset {user_id} lfont")
        if user_dict.get("LEECH_FONT", False):
            lfont = user_dict["LEECH_FONT"]
        elif "LEECH_FONT" not in user_dict and Config.LEECH_FONT:
            lfont = Config.LEECH_FONT
        else:
            lfont = "Normal (None)"

        if (
            user_dict.get("AS_DOCUMENT", False)
            or "AS_DOCUMENT" not in user_dict
            and Config.AS_DOCUMENT
        ):
            ltype = "DOCUMENT"
            buttons.data_button("Send As Media", f"userset {user_id} tog AS_DOCUMENT f")
        else:
            ltype = "MEDIA"
            buttons.data_button(
                "Send As Document", f"userset {user_id} tog AS_DOCUMENT t"
            )
        if (
            user_dict.get("EQUAL_SPLITS", False)
            or "EQUAL_SPLITS" not in user_dict
            and Config.EQUAL_SPLITS
        ):
            buttons.data_button(
                "Disable Equal Splits", f"userset {user_id} tog EQUAL_SPLITS f"
            )
            equal_splits = "Enabled"
        else:
            buttons.data_button(
                "Enable Equal Splits", f"userset {user_id} tog EQUAL_SPLITS t"
            )
            equal_splits = "Disabled"
        if (
            user_dict.get("MEDIA_GROUP", False)
            or "MEDIA_GROUP" not in user_dict
            and Config.MEDIA_GROUP
        ):
            buttons.data_button(
                "Disable Media Group", f"userset {user_id} tog MEDIA_GROUP f"
            )
            media_group = "Enabled"
        else:
            buttons.data_button(
                "Enable Media Group", f"userset {user_id} tog MEDIA_GROUP t"
            )
            media_group = "Disabled"
        buttons.data_button(
            "Thumbnail Layout", f"userset {user_id} menu THUMBNAIL_LAYOUT"
        )
        if user_dict.get("THUMBNAIL_LAYOUT", False):
            thumb_layout = user_dict["THUMBNAIL_LAYOUT"]
        elif "THUMBNAIL_LAYOUT" not in user_dict and Config.THUMBNAIL_LAYOUT:
            thumb_layout = Config.THUMBNAIL_LAYOUT
        else:
            thumb_layout = "None"

        split_mode = user_dict.get("SPLIT_MODE", "part")
        next_split_mode = "number" if split_mode == "part" else "part"
        buttons.data_button(
            f"Split Mode: {split_mode.capitalize()}",
            f"userset {user_id} split_mode {next_split_mode}",
        )

        sequence_enabled = user_dict.get("LEECH_SEQUENCE", False)
        buttons.data_button(
            f"Sequence: {'✓ ON' if sequence_enabled else 'OFF'}",
            f"userset {user_id} tog LEECH_SEQUENCE {'f' if sequence_enabled else 't'} leech",
        )

        auto_leech = user_dict.get("AUTO_LEECH", False)
        buttons.data_button(
            f"Auto Leech: {'✓ ON' if auto_leech else 'OFF'}",
            f"userset {user_id} tog AUTO_LEECH {'f' if auto_leech else 't'} leech",
        )

        thumb_mode_val = user_dict.get("THUMBNAIL_MODE")
        if thumb_mode_val == "auto" or (not thumb_mode_val and user_dict.get("AUTO_THUMBNAIL", False)):
            auto_thumb = "Enabled"
        else:
            auto_thumb = "Disabled"

        buttons.data_button("◀️ Back", f"userset {user_id} back", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(2)

        text = f"""<b>📦 Leech Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Upload Format:</b> <b>{ltype}</b>
• <b>Thumbnail Status:</b> <b>{thumbmsg}</b>
• <b>Split Size Limit:</b> <b>{get_readable_file_size(split_size)}</b>
• <b>Equal Splits:</b> <b>{equal_splits}</b>
• <b>Media Group:</b> <b>{media_group}</b>
• <b>Filename Prefix:</b> <code>{escape(lprefix)}</code>
• <b>Filename Suffix:</b> <code>{escape(lsuffix)}</code>
• <b>Caption Text:</b> <code>{escape(lcap)}</code>
• <b>Destination Chat:</b> <code>{leech_dest}</code>
• <b>Grid Layout:</b> <b>{thumb_layout}</b>
• <b>Split Mode:</b> <b>{split_mode.capitalize()}</b>
• <b>Auto Thumbnail:</b> <b>{auto_thumb}</b>
• <b>Sequence Upload:</b> <b>{'Enabled' if sequence_enabled else 'Disabled'}</b>
• <b>Auto Leech:</b> <b>{'Enabled' if auto_leech else 'Disabled'}</b></blockquote>"""

    elif stype == "thumb_select":
        thumbpath = f"thumbnails/{user_id}.jpg"
        has_thumb = await aiopath.exists(thumbpath)
        cur_mode = user_dict.get("THUMBNAIL_MODE", "custom" if has_thumb else "none")

        a_state = "✓ " if cur_mode == "auto" else ""
        c_state = "✓ " if cur_mode == "custom" else ""
        r_state = "✓ " if cur_mode == "random" else ""
        n_state = "✓ " if cur_mode == "none" else ""

        buttons.data_button(f"{a_state}Auto Thumbnail", f"userset {user_id} thumb_mode auto")
        buttons.data_button(f"{c_state}Custom Thumbnail", f"userset {user_id} thumb_mode custom")
        buttons.data_button(f"{r_state}Random Thumbnail", f"userset {user_id} thumb_mode random")
        buttons.data_button(f"{n_state}No Thumbnail", f"userset {user_id} thumb_mode none")

        buttons.data_button("🖼️ Thumbnail Watermark", f"userset {user_id} thumb_wm_menu")

        if cur_mode == "custom" and has_thumb:
            buttons.data_button("View Thumb", f"userset {user_id} view THUMBNAIL", "header")
            buttons.data_button("Change Thumb", f"userset {user_id} file THUMBNAIL")
            buttons.data_button("Remove Thumb", f"userset {user_id} remove THUMBNAIL")
        elif cur_mode == "custom" and not has_thumb:
            buttons.data_button("Set Custom Thumb", f"userset {user_id} file THUMBNAIL", "header")

        buttons.data_button("◀️ Back", f"userset {user_id} leech", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )

        thumb_status = "Exists" if has_thumb else "Not Configured"
        text = f"""<b>🖼️ User Thumbnail Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Active Mode:</b> <b>{cur_mode.title()}</b>
• <b>Custom Thumb Status:</b> <b>{thumb_status}</b></blockquote>

Select thumbnail option for Telegram uploads:"""
        btns = buttons.build_menu(2)

    elif stype == "thumb_wm_menu":
        wm_text = user_dict.get("THUMB_WM_TEXT") or user_dict.get("WM_TEXT")
        wm_size = user_dict.get("THUMB_WM_SIZE") or user_dict.get("WM_SIZE") or "30"
        wm_img = user_dict.get("THUMB_WM_IMAGE") or user_dict.get("WM_IMAGE")
        wm_color = user_dict.get("THUMB_WM_COLOR") or user_dict.get("WM_COLOR") or "white"
        wm_img_pos = user_dict.get("THUMB_WM_IMAGE_POSITION") or user_dict.get("THUMB_WM_POSITION") or user_dict.get("WM_IMAGE_POSITION") or user_dict.get("WM_POSITION") or "Top-Left"
        wm_text_pos = user_dict.get("THUMB_WM_TEXT_POSITION") or user_dict.get("THUMB_WM_POSITION") or user_dict.get("WM_TEXT_POSITION") or user_dict.get("WM_POSITION") or "Top-Left"

        buttons.data_button("Watermark Text", f"userset {user_id} menu THUMB_WM_TEXT")
        buttons.data_button("Watermark Size", f"userset {user_id} menu THUMB_WM_SIZE")
        buttons.data_button("Photo / Image", f"userset {user_id} file THUMB_WM_IMAGE")
        buttons.data_button("🎨 Text Color", f"userset {user_id} thumb_wm_color_select")
        buttons.data_button("🖼️ Image Position", f"userset {user_id} thumb_wm_img_pos_select")
        buttons.data_button("📝 Text Position", f"userset {user_id} thumb_wm_text_pos_select")

        buttons.data_button("◀️ Back", f"userset {user_id} thumb_select", "footer")
        buttons.data_button("❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER)

        text = f"""<b>🖼️ Thumbnail Watermark Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Watermark Text:</b> <code>{escape(str(wm_text or 'Not Set'))}</code>
• <b>Watermark Size:</b> <code>{escape(str(wm_size))}</code>
• <b>Text Color:</b> <code>{escape(str(wm_color))}</code>
• <b>Photo/Image:</b> <code>{escape(str(wm_img or 'Not Set'))}</code>
• <b>Image Position:</b> <b>{escape(str(wm_img_pos))}</b>
• <b>Text Position:</b> <b>{escape(str(wm_text_pos))}</b></blockquote>"""
        btns = buttons.build_menu(2)

    elif stype == "enc_com_wm":
        enc_enabled = user_dict.get("ENABLE_ENCODE") if "ENABLE_ENCODE" in user_dict else Config.ENABLE_ENCODE
        com_enabled = user_dict.get("ENABLE_COMPRESS") if "ENABLE_COMPRESS" in user_dict else Config.ENABLE_COMPRESS
        wm_enabled = user_dict.get("ENABLE_WATERMARK") if "ENABLE_WATERMARK" in user_dict else Config.ENABLE_WATERMARK

        buttons.data_button(f"🎞️ Encode: {'ON' if enc_enabled else 'OFF'}", f"userset {user_id} encode_menu")
        buttons.data_button(f"🗜️ Compress: {'ON' if com_enabled else 'OFF'}", f"userset {user_id} compress_menu")
        buttons.data_button(f"🖼️ Watermark: {'ON' if wm_enabled else 'OFF'}", f"userset {user_id} watermark_menu")
        buttons.data_button("◀️ Back", f"userset {user_id} back", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(1)

        text = f"""<b>🎬 Encode & Compress & Watermark Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Encode Status:</b> <b>{'Enabled' if enc_enabled else 'Disabled'}</b>
• <b>Compress Status:</b> <b>{'Enabled' if com_enabled else 'Disabled'}</b>
• <b>Watermark Status:</b> <b>{'Enabled' if wm_enabled else 'Disabled'}</b>

Configure custom video encoding, compression, and watermark overlays for uploads. Each feature can be independently enabled or disabled.</blockquote>"""

    elif stype == "encode_menu":
        enc_enabled = user_dict.get("ENABLE_ENCODE") if "ENABLE_ENCODE" in user_dict else Config.ENABLE_ENCODE
        buttons.data_button(
            f"Encode Feature: {'ON' if enc_enabled else 'OFF'}",
            f"userset {user_id} tog ENABLE_ENCODE {'f' if enc_enabled else 't'}",
            position="header",
        )
        buttons.data_button("Quality", f"userset {user_id} menu ENC_QUALITY")
        buttons.data_button("CRF", f"userset {user_id} menu ENC_CRF")
        buttons.data_button("Preset", f"userset {user_id} menu ENC_PRESET")
        buttons.data_button("Codec", f"userset {user_id} menu ENC_CODEC")
        buttons.data_button("Resolution", f"userset {user_id} menu ENC_RESOLUTION")
        buttons.data_button("FPS", f"userset {user_id} menu ENC_FPS")

        buttons.data_button("◀️ Back", f"userset {user_id} enc_com_wm", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(2)

        eq = user_dict.get("ENC_QUALITY", "Not Set")
        ec = user_dict.get("ENC_CRF", "Not Set")
        ep = user_dict.get("ENC_PRESET", "Not Set")
        eco = user_dict.get("ENC_CODEC", "Not Set")
        er = user_dict.get("ENC_RESOLUTION", "Not Set")
        ef = user_dict.get("ENC_FPS", "Not Set")

        text = f"""<b>🎞️ Video Encoding Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Feature Status:</b> <b>{'Enabled' if enc_enabled else 'Disabled'}</b>
• <b>Quality:</b> <code>{escape(str(eq))}</code>
• <b>CRF:</b> <code>{escape(str(ec))}</code>
• <b>Preset:</b> <code>{escape(str(ep))}</code>
• <b>Codec:</b> <code>{escape(str(eco))}</code>
• <b>Resolution:</b> <code>{escape(str(er))}</code>
• <b>FPS:</b> <code>{escape(str(ef))}</code></blockquote>"""

    elif stype == "compress_menu":
        com_enabled = user_dict.get("ENABLE_COMPRESS") if "ENABLE_COMPRESS" in user_dict else Config.ENABLE_COMPRESS
        buttons.data_button(
            f"Compress Feature: {'ON' if com_enabled else 'OFF'}",
            f"userset {user_id} tog ENABLE_COMPRESS {'f' if com_enabled else 't'}",
            position="header",
        )
        buttons.data_button("Quality", f"userset {user_id} menu COM_QUALITY")
        buttons.data_button("CRF", f"userset {user_id} menu COM_CRF")
        buttons.data_button("Preset", f"userset {user_id} menu COM_PRESET")
        buttons.data_button("Audio Bitrate", f"userset {user_id} menu COM_AUDIO_BITRATE")
        buttons.data_button("Audio Codec", f"userset {user_id} menu COM_AUDIO_CODEC")

        buttons.data_button("◀️ Back", f"userset {user_id} enc_com_wm", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(2)

        cq = user_dict.get("COM_QUALITY", "Not Set")
        cc = user_dict.get("COM_CRF", "Not Set")
        cp = user_dict.get("COM_PRESET", "Not Set")
        ca = user_dict.get("COM_AUDIO_BITRATE", "Not Set")
        cac = user_dict.get("COM_AUDIO_CODEC", "Not Set")

        text = f"""<b>🗜️ Video Compression Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Feature Status:</b> <b>{'Enabled' if com_enabled else 'Disabled'}</b>
• <b>Quality:</b> <code>{escape(str(cq))}</code>
• <b>CRF:</b> <code>{escape(str(cc))}</code>
• <b>Preset:</b> <code>{escape(str(cp))}</code>
• <b>Audio Bitrate:</b> <code>{escape(str(ca))}</code>
• <b>Audio Codec:</b> <code>{escape(str(cac))}</code></blockquote>"""

    elif stype == "watermark_menu":
        wm_enabled = user_dict.get("ENABLE_WATERMARK") if "ENABLE_WATERMARK" in user_dict else Config.ENABLE_WATERMARK
        buttons.data_button(
            f"Watermark Feature: {'ON' if wm_enabled else 'OFF'}",
            f"userset {user_id} tog ENABLE_WATERMARK {'f' if wm_enabled else 't'}",
            position="header",
        )
        buttons.data_button("Username", f"userset {user_id} menu WM_USERNAME")
        buttons.data_button("Text", f"userset {user_id} menu WM_TEXT")
        buttons.data_button("Photo / Image URL", f"userset {user_id} file WM_IMAGE")
        buttons.data_button("Size / Scale", f"userset {user_id} menu WM_SIZE")
        buttons.data_button("🎨 Text Color", f"userset {user_id} wm_color_select")
        buttons.data_button("🖼️ Image Position", f"userset {user_id} wm_img_pos_select")
        buttons.data_button("📝 Text Position", f"userset {user_id} wm_text_pos_select")

        wm_user = user_dict.get("WM_USERNAME")
        wm_text = user_dict.get("WM_TEXT")
        wm_img = user_dict.get("WM_IMAGE")
        wm_size = user_dict.get("WM_SIZE", "Default")
        wm_color = user_dict.get("WM_COLOR", "white")
        wm_img_pos = user_dict.get("WM_IMAGE_POSITION") or user_dict.get("WM_POSITION") or "Top-Left"
        wm_text_pos = user_dict.get("WM_TEXT_POSITION") or user_dict.get("WM_POSITION") or "Top-Left"

        buttons.data_button("◀️ Back", f"userset {user_id} enc_com_wm", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(2)

        text = f"""<b>🖼️ Watermark Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Feature Status:</b> <b>{'Enabled' if wm_enabled else 'Disabled'}</b>
• <b>Username:</b> <code>{escape(str(wm_user or 'Not Set'))}</code>
• <b>Text:</b> <code>{escape(str(wm_text or 'Not Set'))}</code>
• <b>Photo/Image URL:</b> <code>{escape(str(wm_img or 'Not Set'))}</code>
• <b>Size / Scale:</b> <code>{escape(str(wm_size))}</code>
• <b>Text Color:</b> <code>{escape(str(wm_color))}</code>
• <b>Image Position:</b> <b>{escape(str(wm_img_pos))}</b>
• <b>Text Position:</b> <b>{escape(str(wm_text_pos))}</b></blockquote>"""

    elif stype == "vtools":
        auto_merge = user_dict.get("AUTO_MERGE", False) or (
            "AUTO_MERGE" not in user_dict and getattr(Config, "AUTO_MERGE", False)
        )
        buttons.data_button(
            f"Auto Merge: {'✓ ON' if auto_merge else 'OFF'}",
            f"userset {user_id} tog AUTO_MERGE {'f' if auto_merge else 't'} vtools",
            position="header",
        )

        merge_mode = user_dict.get("AUTO_MERGE_MODE", "normal")
        if auto_merge:
            n_st = "✓ " if merge_mode == "normal" else ""
            a_st = "✓ " if merge_mode == "advanced" else ""
            buttons.data_button(f"{n_st}Normal Mode", f"userset {user_id} set_merge_mode normal")
            buttons.data_button(f"{a_st}Advanced Mode", f"userset {user_id} set_merge_mode advanced")

        save_files = user_dict.get("SAVE_FILES", False)
        buttons.data_button(
            f"Keep Original Files: {'✓ ON' if save_files else 'OFF'}",
            f"userset {user_id} tog SAVE_FILES {'f' if save_files else 't'} vtools",
        )

        buttons.data_button("◀️ Back", f"userset {user_id} back", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(2)

        text = f"""<b>🎬 Video Processing Tools</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Auto Video Merge:</b> <b>{'Enabled (' + merge_mode.title() + ' Mode)' if auto_merge else 'Disabled'}</b>
• <b>Keep Original Files on Merge:</b> <b>{'Enabled' if save_files else 'Disabled'}</b></blockquote>"""

    elif stype == "uphoster":
        uphoster_service = user_dict.get("UPHOSTER_SERVICE", "gofile")
        auto_ddl = user_dict.get("AUTO_DDL", False)
        buttons.data_button(
            f"Auto DDL: {'✓ ON' if auto_ddl else 'OFF'}",
            f"userset {user_id} tog AUTO_DDL {'f' if auto_ddl else 't'} uphoster",
            position="header",
        )
        buttons.data_button(
            "Change Destination ⇋", f"userset {user_id} uphoster_destinations", "header"
        )
        buttons.data_button("Gofile Tools", f"userset {user_id} gofile")
        buttons.data_button("BuzzHeavier Tools", f"userset {user_id} buzzheavier")
        buttons.data_button("PixelDrain Tools", f"userset {user_id} pixeldrain")
        buttons.data_button("DevUploads Tools", f"userset {user_id} devuploads")
        buttons.data_button("VikingFile Tools", f"userset {user_id} vikingfile")
        buttons.data_button("External/API Host Tools", f"userset {user_id} host_api_tools")
        buttons.data_button("◀️ Back", f"userset {user_id} back", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(2)

        destinations = [s.capitalize() for s in uphoster_service.split(",")]
        text = f"""<b>🌐 Uphoster Services Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Auto DDL:</b> <b>{'Enabled' if auto_ddl else 'Disabled'}</b>
• <b>Active Services:</b> {", ".join(destinations)}</blockquote>"""

    elif stype == "host_api_tools":
        buttons = ButtonMaker()
        api_hosts = [
            ("GDFlix", "GDFLIX_UPLOAD_URL", "GDFLIX_API_KEY"),
            ("HubCloud", "HUBCLOUD_UPLOAD_URL", "HUBCLOUD_API_KEY"),
            ("FilePress", "FILEPRESS_UPLOAD_URL", "FILEPRESS_API_KEY"),
            ("LuluStream", "LULUSTREAM_UPLOAD_URL", "LULUSTREAM_API_KEY"),
            ("StreamTape", "STREAMTAPE_UPLOAD_URL", "STREAMTAPE_API_KEY"),
            ("FileMoon", "FILEMOON_UPLOAD_URL", "FILEMOON_API_KEY"),
            ("UploadHub", "UPLOADHUB_UPLOAD_URL", "UPLOADHUB_API_KEY"),
            ("FileStreams", "FILESTREAMS_UPLOAD_URL", "FILESTREAMS_API_KEY"),
        ]
        for label, url_key, key_key in api_hosts:
            buttons.data_button(f"{label} Endpoint", f"userset {user_id} menu {url_key}")
            buttons.data_button(f"{label} API Key", f"userset {user_id} menu {key_key}")
        buttons.data_button("◀️ Back", f"userset {user_id} back uphoster", "footer")
        buttons.data_button("❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER)
        btns = buttons.build_menu(2)
        configured = sum(bool(user_dict.get(k) or getattr(Config, k, "")) for _, u, k in api_hosts for k in (u,))
        text = f"""<b>🌐 External/API Host Destinations</b>

<blockquote>Configure the host's current official upload API endpoint and optional API key.
The bot does not guess undocumented endpoints.</blockquote>

<b>Configured endpoints:</b> <code>{configured}/{len(api_hosts)}</code>"""
    elif stype == "pixeldrain":
        buttons.data_button("PixelDrain Key", f"userset {user_id} menu PIXELDRAIN_KEY")
        buttons.data_button("◀️ Back", f"userset {user_id} back uphoster", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(1)

        if user_dict.get("PIXELDRAIN_KEY", False):
            pdtoken = user_dict["PIXELDRAIN_KEY"]
        elif Config.PIXELDRAIN_KEY:
            pdtoken = Config.PIXELDRAIN_KEY
        else:
            pdtoken = "None"

        pdtoken_disp = (
            pdtoken[:2] + "****" + pdtoken[-2:]
            if pdtoken and pdtoken != "None" and len(pdtoken) > 6
            else ("****" if pdtoken and pdtoken != "None" else "None")
        )

        text = f"""<b>PixelDrain Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>API Key:</b> <code>{pdtoken_disp}</code></blockquote>"""

    elif stype == "buzzheavier":
        buttons.data_button(
            "BuzzHeavier Token", f"userset {user_id} menu BUZZHEAVIER_TOKEN"
        )
        buttons.data_button(
            "BuzzHeavier Folder ID", f"userset {user_id} menu BUZZHEAVIER_FOLDER_ID"
        )
        buttons.data_button("◀️ Back", f"userset {user_id} back uphoster", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(1)

        if user_dict.get("BUZZHEAVIER_TOKEN", False):
            bztoken = user_dict["BUZZHEAVIER_TOKEN"]
        elif Config.BUZZHEAVIER_API:
            bztoken = Config.BUZZHEAVIER_API
        else:
            bztoken = "None"

        bztoken_disp = (
            bztoken[:2] + "****" + bztoken[-2:]
            if bztoken and bztoken != "None" and len(bztoken) > 6
            else ("****" if bztoken and bztoken != "None" else "None")
        )

        if user_dict.get("BUZZHEAVIER_FOLDER_ID", False):
            bzfolder = user_dict["BUZZHEAVIER_FOLDER_ID"]
        else:
            bzfolder = "None"

        text = f"""<b>BuzzHeavier Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>API Token:</b> <code>{bztoken_disp}</code>
• <b>Folder ID:</b> <code>{bzfolder}</code></blockquote>"""

    elif stype == "devuploads":
        buttons.data_button(
            "DevUploads API Key", f"userset {user_id} menu DEVUPLOADS_KEY"
        )
        buttons.data_button(
            "DevUploads Folder ID", f"userset {user_id} menu DEVUPLOADS_FOLDER"
        )
        buttons.data_button("◀️ Back", f"userset {user_id} back uphoster", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(1)

        dukey = user_dict.get("DEVUPLOADS_KEY") or Config.DEVUPLOADS_KEY or "None"
        dukey_disp = (
            dukey[:2] + "****" + dukey[-2:]
            if dukey and dukey != "None" and len(dukey) > 6
            else ("****" if dukey and dukey != "None" else "None")
        )
        dufolder = (
            user_dict.get("DEVUPLOADS_FOLDER")
            or Config.DEVUPLOADS_FOLDER
            or "None (Root)"
        )
        text = f"""<b>DevUploads Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>API Key:</b> <code>{dukey_disp}</code>
• <b>Folder ID:</b> <code>{dufolder}</code></blockquote>"""

    elif stype == "vikingfile":
        buttons.data_button(
            "VikingFile Hash", f"userset {user_id} menu VIKINGFILE_HASH"
        )
        buttons.data_button(
            "VikingFile Folder", f"userset {user_id} menu VIKINGFILE_FOLDER"
        )
        buttons.data_button("◀️ Back", f"userset {user_id} back uphoster", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(1)

        vfkey = user_dict.get("VIKINGFILE_HASH") or Config.VIKINGFILE_HASH or "None"
        vfkey_disp = (
            vfkey[:2] + "****" + vfkey[-2:]
            if vfkey and vfkey != "None" and len(vfkey) > 6
            else ("****" if vfkey and vfkey != "None" else "None")
        )
        vffolder = (
            user_dict.get("VIKINGFILE_FOLDER")
            or Config.VIKINGFILE_FOLDER
            or "None (Root)"
        )
        text = f"""<b>VikingFile Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>User Hash:</b> <code>{vfkey_disp}</code>
• <b>Folder Path:</b> <code>{vffolder}</code></blockquote>"""

    elif stype == "gofile":
        buttons.data_button("Gofile Token", f"userset {user_id} menu GOFILE_TOKEN")
        buttons.data_button(
            "Gofile Folder ID", f"userset {user_id} menu GOFILE_FOLDER_ID"
        )
        auto_create = (
            user_dict.get("GOFILE_AUTO_CREATE_FOLDER")
            if "GOFILE_AUTO_CREATE_FOLDER" in user_dict
            else Config.GOFILE_AUTO_CREATE_FOLDER
        )
        auto_state = "✓" if auto_create else ""
        buttons.data_button(
            f"Auto-Create Folder {auto_state}",
            f"userset {user_id} tog GOFILE_AUTO_CREATE_FOLDER {'t' if not auto_create else 'f'}",
        )
        buttons.data_button("◀️ Back", f"userset {user_id} back uphoster", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(1)

        if user_dict.get("GOFILE_TOKEN", False):
            gftoken = user_dict["GOFILE_TOKEN"]
        elif Config.GOFILE_API:
            gftoken = Config.GOFILE_API
        else:
            gftoken = "None"

        gftoken_disp = (
            gftoken[:2] + "****" + gftoken[-2:]
            if gftoken and gftoken != "None" and len(gftoken) > 6
            else ("****" if gftoken and gftoken != "None" else "None")
        )

        if user_dict.get("GOFILE_FOLDER_ID", False):
            gffolder = user_dict["GOFILE_FOLDER_ID"]
        elif Config.GOFILE_FOLDER_ID:
            gffolder = Config.GOFILE_FOLDER_ID
        else:
            gffolder = "None (Uploads to Root)"

        text = f"""<b>Gofile Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>API Token:</b> <code>{gftoken_disp}</code>
• <b>Folder ID:</b> <code>{gffolder}</code>
• <b>Auto-Create Folder:</b> <code>{"Enabled" if auto_create else "Disabled"}</code></blockquote>"""

    elif stype == "lfont":
        fonts = [
            ("Bold", "b"),
            ("Italic", "i"),
            ("Monospace", "code"),
            ("Spoiler", "tg-spoiler"),
            ("Strikethrough", "s"),
            ("Underline", "u"),
            ("None (Normal)", "none"),
        ]
        cur_font = user_dict.get("LEECH_FONT") or Config.LEECH_FONT or "none"
        for label, tag in fonts:
            st = "✓ " if cur_font == tag else ""
            buttons.data_button(f"{st}{label}", f"userset {user_id} setfont {tag}")
        buttons.data_button("◀️ Back", f"userset {user_id} leech", position="footer")
        btns = buttons.build_menu(2)
        text = f"<b>📄 Select Caption Font Style:</b>\nCurrent: <code>{cur_font}</code>"
    elif stype == "rclone":
        buttons.data_button("Rclone Config", f"userset {user_id} menu RCLONE_CONFIG")
        buttons.data_button(
            "Default Rclone Path", f"userset {user_id} menu RCLONE_PATH"
        )
        buttons.data_button("Rclone Flags", f"userset {user_id} menu RCLONE_FLAGS")

        buttons.data_button("◀️ Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )

        rccmsg = "Exists" if await aiopath.exists(rclone_conf) else "Not Exists"
        if user_dict.get("RCLONE_PATH", False):
            rccpath = user_dict["RCLONE_PATH"]
        elif Config.RCLONE_PATH:
            rccpath = Config.RCLONE_PATH
        else:
            rccpath = "None"
        btns = buttons.build_menu(2)

        if user_dict.get("RCLONE_FLAGS", False):
            rcflags = user_dict["RCLONE_FLAGS"]
        elif "RCLONE_FLAGS" not in user_dict and Config.RCLONE_FLAGS:
            rcflags = Config.RCLONE_FLAGS
        else:
            rcflags = "None"

        text = f"""<b>☁️ Rclone Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Config Status:</b> <b>{rccmsg}</b>
• <b>Default Flags:</b> <code>{rcflags}</code>
• <b>Default Path:</b> <code>{rccpath}</code></blockquote>"""

    elif stype == "gdrive":
        buttons.data_button("Default Gdrive ID", f"userset {user_id} menu GDRIVE_ID")
        buttons.data_button("Default Index URL", f"userset {user_id} menu INDEX_URL")
        buttons.data_button("Token.pickle", f"userset {user_id} menu TOKEN_PICKLE")
        if (
            user_dict.get("STOP_DUPLICATE", False)
            or "STOP_DUPLICATE" not in user_dict
            and Config.STOP_DUPLICATE
        ):
            buttons.data_button(
                "Disable Stop Duplicate", f"userset {user_id} tog STOP_DUPLICATE f"
            )
            sd_msg = "Enabled"
        else:
            buttons.data_button(
                "Enable Stop Duplicate",
                f"userset {user_id} tog STOP_DUPLICATE t",
                "l_body",
            )
            sd_msg = "Disabled"
        buttons.data_button(
            "User Drive Categories", f"userset {user_id} menu DRIVE_CAT", "header"
        )
        buttons.data_button("◀️ Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )

        tokenmsg = "Exists" if await aiopath.exists(token_pickle) else "Not Exists"
        if user_dict.get("GDRIVE_ID", False):
            gdrive_id = user_dict["GDRIVE_ID"]
        elif GDID := Config.GDRIVE_ID:
            gdrive_id = GDID
        else:
            gdrive_id = "None"
        index = user_dict["INDEX_URL"] if user_dict.get("INDEX_URL", False) else "None"
        upload_sa = user_dict.get("DRIVE_CATEGORY_SA") or Config.DRIVE_CATEGORY_SA
        sa_display = escape(upload_sa) if upload_sa else "Not Set"
        dc_status = "Enabled" if user_dict.get("drive_cat_mode", False) else "Disabled"
        if not Config.DRIVE_CATEGORY_MODE:
            dc_status = "Force Disabled (Global)"
        drive_cat_val = user_dict.get("DRIVE_CAT")
        lines = []
        default_ilink_part = (
            f" | <code>{escape(index)}</code>" if index != "None" else ""
        )
        lines.append(
            f"• <b>Default:</b> <code>{escape(gdrive_id)}</code>{default_ilink_part}"
        )
        if drive_cat_val:
            for k, v in drive_cat_val.items():
                did = v.get("drive_id", "")
                ilink = v.get("index_link", "")
                ilink_part = f" | <code>{escape(ilink)}</code>" if ilink else ""
                lines.append(
                    f"• <b>{escape(k)}:</b> <code>{escape(did)}</code>{ilink_part}"
                )
        drive_cat_display = "\n".join(lines)
        btns = buttons.build_menu(2)

        text = f"""<b>📁 Google Drive Tools Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Default Drive ID:</b> <code>{gdrive_id}</code>
• <b>Index Mirror URL:</b> <code>{index}</code>
• <b>Stop Duplicate:</b> <b>{sd_msg}</b>
• <b>Token.pickle Status:</b> <b>{tokenmsg}</b>
• <b>Category SA:</b> <code>{sa_display}</code>
• <b>Category Mode:</b> <b>{dc_status}</b>
• <b>Categories:</b>\n{drive_cat_display}</blockquote>"""
    elif stype == "mirror":
        buttons.data_button("RClone Tools", f"userset {user_id} rclone")
        rccmsg = "Exists" if await aiopath.exists(rclone_conf) else "Not Exists"
        if user_dict.get("RCLONE_PATH", False):
            rccpath = user_dict["RCLONE_PATH"]
        elif RP := Config.RCLONE_PATH:
            rccpath = RP
        else:
            rccpath = "None"

        buttons.data_button("GDrive Tools", f"userset {user_id} gdrive")
        tokenmsg = "Exists" if await aiopath.exists(token_pickle) else "Not Exists"
        if user_dict.get("GDRIVE_ID", False):
            gdrive_id = user_dict["GDRIVE_ID"]
        elif GI := Config.GDRIVE_ID:
            gdrive_id = GI
        else:
            gdrive_id = "None"

        index = user_dict["INDEX_URL"] if user_dict.get("INDEX_URL", False) else "None"
        if (
            user_dict.get("STOP_DUPLICATE", False)
            or "STOP_DUPLICATE" not in user_dict
            and Config.STOP_DUPLICATE
        ):
            sd_msg = "Enabled"
        else:
            sd_msg = "Disabled"

        buttons.data_button("YT Up Tools", f"userset {user_id} yttools")
        buttons.data_button("Mega Tools", f"userset {user_id} mega")
        if not Config.DISABLE_SEEDR:
            buttons.data_button("Seedr Tools", f"userset {user_id} seedr")
        if Config.DRIVE_CATEGORY_MODE:
            dc_enabled = user_dict.get("drive_cat_mode", False)
            buttons.data_button(
                f"Drive Categories: {'ON' if dc_enabled else 'OFF'}",
                f"userset {user_id} tog drive_cat_mode {'f' if dc_enabled else 't'}",
                "header",
            )
        auto_mirror = user_dict.get("AUTO_MIRROR", False)
        buttons.data_button(
            f"Auto Mirror: {'✓ ON' if auto_mirror else 'OFF'}",
            f"userset {user_id} tog AUTO_MIRROR {'f' if auto_mirror else 't'} mirror",
            position="header",
        )
        buttons.data_button("◀️ Back", f"userset {user_id} back", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(2)

        text = f"""<b>☁️ Mirror Cloud Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Auto Mirror:</b> <b>{'Enabled' if auto_mirror else 'Disabled'}</b>
• <b>Stop Duplicate Checks:</b> <b>{sd_msg}</b></blockquote>"""

    elif stype == "mega":
        mega_email = user_dict.get("MEGA_EMAIL") or Config.MEGA_EMAIL or ""
        mega_password = user_dict.get("MEGA_PASSWORD") or Config.MEGA_PASSWORD or ""
        has_creds = bool(mega_email and mega_password)
        masked_pass = (
            (
                mega_password[:2] + "*" * (len(mega_password) - 4) + mega_password[-2:]
                if len(mega_password) > 6
                else "****"
            )
            if mega_password
            else ""
        )

        buttons.data_button("Mega Email", f"userset {user_id} menu MEGA_EMAIL")
        if mega_email:
            buttons.data_button(
                "Mega Password", f"userset {user_id} menu MEGA_PASSWORD"
            )

        if has_creds:
            buttons.data_button(
                "Remove Account",
                f"userset {user_id} remove MEGA_EMAIL",
                position="l_body",
            )

        buttons.data_button("◀️ Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(1)

        email_display = mega_email or "Not Set"
        pass_display = masked_pass if mega_password else "Not Set"
        account_status = "✓ Configured" if has_creds else "❌ Not Configured"
        text = f"""<b>🔴 Mega.nz Cloud Account</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Email:</b> <code>{email_display}</code>
• <b>Password:</b> <code>{pass_display}</code>
• <b>Status:</b> {account_status}</blockquote>"""

    elif stype == "seedr":
        seedr_email = user_dict.get("SEEDR_EMAIL", "")
        seedr_password = user_dict.get("SEEDR_PASSWORD", "")
        seedr_delete = (
            user_dict.get("SEEDR_DELETE_FOLDER")
            if "SEEDR_DELETE_FOLDER" in user_dict
            else Config.SEEDR_DELETE_FOLDER
        )
        has_creds = bool(seedr_email and seedr_password)
        masked_pass = (
            (
                seedr_password[:2]
                + "*" * (len(seedr_password) - 4)
                + seedr_password[-2:]
                if len(seedr_password) > 6
                else "****"
            )
            if seedr_password
            else ""
        )

        buttons.data_button("Seedr Email", f"userset {user_id} menu SEEDR_EMAIL")
        if seedr_email:
            buttons.data_button(
                "Seedr Password", f"userset {user_id} menu SEEDR_PASSWORD"
            )

        buttons.data_button(
            f"Delete Folder: {'ON' if seedr_delete else 'OFF'}",
            f"userset {user_id} tog SEEDR_DELETE_FOLDER {'f' if seedr_delete else 't'}",
        )

        if has_creds:
            buttons.data_button(
                "Clear Storage",
                f"userset {user_id} clear_seedr",
                position="l_body",
            )
            buttons.data_button(
                "Remove Account",
                f"userset {user_id} remove SEEDR_EMAIL",
                position="l_body",
            )

        buttons.data_button("◀️ Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(1)

        email_display = seedr_email or "Not Set"
        pass_display = masked_pass if seedr_password else "Not Set"
        account_status = "✓ Configured" if has_creds else "❌ Not Configured"
        delete_display = "Enabled" if seedr_delete else "Disabled"
        text = f"""<b>🌱 Seedr.cc Cloud Account</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Email:</b> <code>{email_display}</code>
• <b>Password:</b> <code>{pass_display}</code>
• <b>Auto Delete Folder:</b> {delete_display}
• <b>Status:</b> {account_status}</blockquote>"""

    elif stype == "ffset":
        enable_ffc = user_dict.get("ENABLE_FFMPEG_CMDS") if "ENABLE_FFMPEG_CMDS" in user_dict else Config.ENABLE_FFMPEG_CMDS
        buttons.data_button(
            f"FFmpeg Commands: {'ON' if enable_ffc else 'OFF'}",
            f"userset {user_id} tog ENABLE_FFMPEG_CMDS {'f' if enable_ffc else 't'}",
            position="header",
        )
        buttons.data_button(
            "FFmpeg Cmds", f"userset {user_id} menu FFMPEG_CMDS"
        )
        buttons.data_button(
            "DUMP", f"userset {user_id} menu FFMPEG_DUMP"
        )

        user_ff = user_dict.get("FFMPEG_CMDS") or {}
        global_ff = Config.FFMPEG_CMDS or {}
        merged_ff = {**global_ff, **user_ff} if isinstance(user_ff, dict) and isinstance(global_ff, dict) else (user_ff or global_ff or {})
        avail_keys = list(merged_ff.keys())
        if avail_keys:
            lines = []
            for k in avail_keys:
                source_tag = " (User)" if k in user_ff else " (Global)"
                lines.append(f"• <code>-ff {escape(str(k))}</code>{source_tag}")
            ffc_display = "\n" + "\n".join(lines)
        else:
            ffc_display = "<b>None Configured</b>"

        user_dump_dict = user_dict.get("FFMPEG_DUMP") or Config.FFMPEG_DUMP or {}
        if isinstance(user_dump_dict, dict) and user_dump_dict:
            dump_display = "\n" + "\n".join([f"• <b>{escape(str(k)).upper()}:</b> <code>{escape(str(v))}</code>" for k, v in user_dump_dict.items()])
        else:
            dump_display = "<b>Not Set (Default DM)</b>"

        set_all_enabled = user_dict.get("SET_ALL_METADATA_ENABLE", False)

        buttons.data_button(
            f"Set All Metadata: {'ON' if set_all_enabled else 'OFF'}",
            f"userset {user_id} tog SET_ALL_METADATA_ENABLE {'f' if set_all_enabled else 't'}",
        )

        strip_meta_enabled = user_dict.get("STRIP_METADATA_ENABLE", False)
        buttons.data_button(
            f"Strip Metadata: {'ON' if strip_meta_enabled else 'OFF'}",
            f"userset {user_id} tog STRIP_METADATA_ENABLE {'f' if strip_meta_enabled else 't'}",
        )

        set_all_meta_setting = user_dict.get("SET_ALL_METADATA")
        display_set_all_meta = "<b>Not Set</b>"
        if isinstance(set_all_meta_setting, dict) and set_all_meta_setting:
            display_set_all_meta = ", ".join(
                f"{k}={escape(str(v))}" for k, v in set_all_meta_setting.items()
            )
            display_set_all_meta = f"<code>{display_set_all_meta}</code>"

        if set_all_enabled:
            buttons.data_button("Set All Metadata", f"userset {user_id} menu SET_ALL_METADATA")
            buttons.data_button("Metadata", f"userset {user_id} menu METADATA")
        else:
            buttons.data_button("Metadata", f"userset {user_id} menu METADATA")
            buttons.data_button("Audio Metadata", f"userset {user_id} menu AUDIO_METADATA")
            buttons.data_button("Video Metadata", f"userset {user_id} menu VIDEO_METADATA")
            buttons.data_button(
                "Subtitle Metadata", f"userset {user_id} menu SUBTITLE_METADATA"
            )

        metadata_setting = user_dict.get("METADATA")
        display_meta_val = "<b>Not Set</b>"
        if isinstance(metadata_setting, dict) and metadata_setting:
            display_meta_val = ", ".join(
                f"{k}={escape(str(v))}" for k, v in metadata_setting.items()
            )
            display_meta_val = f"<code>{display_meta_val}</code>"
        elif isinstance(metadata_setting, str) and metadata_setting:  # Legacy
            display_meta_val = (
                f"<code>{escape(metadata_setting)}</code> [<i>Legacy, needs re-set</i>]"
            )

        audio_meta_setting = user_dict.get("AUDIO_METADATA")
        display_audio_meta = "<b>Not Set</b>"
        if isinstance(audio_meta_setting, dict) and audio_meta_setting:
            display_audio_meta = ", ".join(
                f"{k}={escape(str(v))}" for k, v in audio_meta_setting.items()
            )
            display_audio_meta = f"<code>{display_audio_meta}</code>"

        video_meta_setting = user_dict.get("VIDEO_METADATA")
        display_video_meta = "<b>Not Set</b>"
        if isinstance(video_meta_setting, dict) and video_meta_setting:
            display_video_meta = ", ".join(
                f"{k}={escape(str(v))}" for k, v in video_meta_setting.items()
            )
            display_video_meta = f"<code>{display_video_meta}</code>"

        subtitle_meta_setting = user_dict.get("SUBTITLE_METADATA")
        display_subtitle_meta = "<b>Not Set</b>"
        if isinstance(subtitle_meta_setting, dict) and subtitle_meta_setting:
            display_subtitle_meta = ", ".join(
                f"{k}={escape(str(v))}" for k, v in subtitle_meta_setting.items()
            )
            display_subtitle_meta = f"<code>{display_subtitle_meta}</code>"

        buttons.data_button("◀️ Back", f"userset {user_id} back", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(2, h_cols=1)

        set_all_status = "Enabled" if set_all_enabled else "Disabled"
        strip_meta_status = "Enabled" if strip_meta_enabled else "Disabled"
        text = f"""<b>🎞️ FFmpeg & Media Metadata Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Available FFmpeg Flags:</b> {ffc_display}
• <b>Configured Key DUMP Destinations:</b> {dump_display}
• <b>Global Metadata Override:</b> <b>{set_all_status}</b>
• <b>Strip Metadata:</b> <b>{strip_meta_status}</b>
• <b>Global Metadata:</b> {display_set_all_meta}
• <b>Default Metadata:</b> {display_meta_val if not set_all_enabled else '(Disabled)'}
• <b>Audio Metadata:</b> {display_audio_meta if not set_all_enabled else '(Disabled)'}
• <b>Video Metadata:</b> {display_video_meta if not set_all_enabled else '(Disabled)'}
• <b>Subtitle Metadata:</b> {display_subtitle_meta if not set_all_enabled else '(Disabled)'}</blockquote>"""

    elif stype == "advanced":
        name_source = user_dict.get("NAME_SOURCE", "caption")
        ns_label = "File Caption" if name_source == "caption" else "Filename"
        next_ns = "filename" if name_source == "caption" else "caption"
        buttons.data_button(
            f"Name Source: {ns_label}",
            f"userset {user_id} name_source {next_ns}",
            position="header",
        )

        range_mode = user_dict.get("RANGE_LINK_MODE") or getattr(Config, "RANGE_LINK_MODE", "normal")
        rm_label = "Each Message" if range_mode == "each" else "Normal (Batch)"
        next_rm = "normal" if range_mode == "each" else "each"
        buttons.data_button(
            f"Range Link Mode: {rm_label}",
            f"userset {user_id} range_mode {next_rm}",
            position="header",
        )

        buttons.data_button(
            "Excluded Extensions", f"userset {user_id} menu EXCLUDED_EXTENSIONS"
        )
        if user_dict.get("EXCLUDED_EXTENSIONS", False):
            ex_ex = user_dict["EXCLUDED_EXTENSIONS"]
        elif "EXCLUDED_EXTENSIONS" not in user_dict:
            ex_ex = excluded_extensions
        else:
            ex_ex = "None"

        if ex_ex != "None":
            ex_ex = ", ".join(ex_ex)

        swap = user_dict.get("NAME_SWAP", False)
        ns_msg = f"<code>{swap}</code>" if swap else "<b>Not Set</b>"
        buttons.data_button("Name Swap", f"userset {user_id} menu NAME_SWAP")

        auto_rename = user_dict.get("AUTO_RENAME", False) or (
            "AUTO_RENAME" not in user_dict and getattr(Config, "AUTO_RENAME", False)
        )
        buttons.data_button(
            f"Auto Rename: {'ON' if auto_rename else 'OFF'}",
            f"userset {user_id} tog AUTO_RENAME {'f' if auto_rename else 't'} advanced",
        )

        rename_fmt = user_dict.get("AUTO_RENAME_FORMAT") or getattr(
            Config, "AUTO_RENAME_FORMAT", "{TITLE} - {SEASON} {EPISODE} {QUALITY}"
        )
        buttons.data_button("Rename Format", f"userset {user_id} menu AUTO_RENAME_FORMAT")

        buttons.data_button("YT-DLP Options", f"userset {user_id} menu YT_DLP_OPTIONS")
        if user_dict.get("YT_DLP_OPTIONS", False):
            ytopt = user_dict["YT_DLP_OPTIONS"]
        elif "YT_DLP_OPTIONS" not in user_dict and Config.YT_DLP_OPTIONS:
            ytopt = Config.YT_DLP_OPTIONS
        else:
            ytopt = "None"

        if user_dict.get("UPLOAD_PATHS", False):
            upload_paths = user_dict["UPLOAD_PATHS"]
        elif "UPLOAD_PATHS" not in user_dict and Config.UPLOAD_PATHS:
            upload_paths = Config.UPLOAD_PATHS
        else:
            upload_paths = "None"
        buttons.data_button("Upload Paths", f"userset {user_id} menu UPLOAD_PATHS")

        yt_cookie_path = f"cookies/{user_id}/cookies.txt"
        user_cookie_msg = (
            "Exists" if await aiopath.exists(yt_cookie_path) else "Not Exists"
        )
        buttons.data_button(
            "YT Cookie File", f"userset {user_id} menu USER_COOKIE_FILE"
        )

        session_mode = user_dict.get("TELEGRAM_SESSION_MODE", "disabled")
        session_labels = {
            "telegram": "Telegram Links",
            "upload": "Upload",
            "both": "Telegram Links + Upload",
            "disabled": "Disabled",
        }
        session_state = session_labels.get(session_mode, "Disabled")
        buttons.data_button(
            f"🔐 Session String: {session_state}",
            f"userset {user_id} session_menu",
        )

        buttons.data_button("◀️ Back", f"userset {user_id} back", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(2)

        text = f"""<b>🛠️ Advanced Options Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Range Link Mode:</b> <b>{rm_label}</b>
• <b>Name Swap Patterns:</b> {ns_msg}
• <b>Auto Rename:</b> <b>{'Enabled' if auto_rename else 'Disabled'}</b>
• <b>Rename Format:</b> <code>{escape(str(rename_fmt))}</code>
• <b>Excluded Extensions:</b> <code>{ex_ex}</code>
• <b>Upload Paths Dict:</b> <b>{upload_paths}</b>
• <b>YT-DLP Custom Options:</b> <code>{ytopt}</code>
• <b>Cookie File Status:</b> <b>{user_cookie_msg}</b>
• <b>Personal Session:</b> <b>{session_state}</b></blockquote>"""
    elif stype == "yttools":
        buttons.data_button("YT Description", f"userset {user_id} menu YT_DESP")
        yt_desp_val = user_dict.get(
            "YT_DESP",
            Config.YT_DESP if hasattr(Config, "YT_DESP") else "Not Set (Uses Default)",
        )

        buttons.data_button("YT Tags", f"userset {user_id} menu YT_TAGS")
        yt_tags_val = user_dict.get(
            "YT_TAGS",
            Config.YT_TAGS if hasattr(Config, "YT_TAGS") else "Not Set (Uses Default)",
        )
        if isinstance(yt_tags_val, list):
            yt_tags_val = ",".join(yt_tags_val)

        buttons.data_button("YT Category ID", f"userset {user_id} menu YT_CATEGORY_ID")
        yt_cat_id_val = user_dict.get(
            "YT_CATEGORY_ID",
            (
                Config.YT_CATEGORY_ID
                if hasattr(Config, "YT_CATEGORY_ID")
                else "Not Set (Uses Default)"
            ),
        )

        buttons.data_button(
            "YT Privacy Status", f"userset {user_id} menu YT_PRIVACY_STATUS"
        )
        yt_privacy_val = user_dict.get(
            "YT_PRIVACY_STATUS",
            (
                Config.YT_PRIVACY_STATUS
                if hasattr(Config, "YT_PRIVACY_STATUS")
                else "Not Set (Uses Default)"
            ),
        )

        buttons.data_button("◀️ Back", f"userset {user_id} back mirror", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        btns = buttons.build_menu(2)

        text = f"""<b>▶️ YouTube Upload Tools Settings</b>

<blockquote>• <b>User:</b> {user_name}
• <b>Description:</b> <code>{escape(str(yt_desp_val))}</code>
• <b>Tags:</b> <code>{escape(str(yt_tags_val))}</code>
• <b>Category ID:</b> <code>{escape(str(yt_cat_id_val))}</code>
• <b>Privacy Status:</b> <code>{escape(str(yt_privacy_val))}</code></blockquote>"""

    return text, btns


async def update_user_settings(query, stype="main"):
    handler_dict[query.from_user.id] = False
    msg, button = await get_user_settings(query.from_user, stype)
    await edit_message(query.message, msg, button)


@new_task
async def send_user_settings(_, message):
    from_user = message.from_user
    handler_dict[from_user.id] = False
    msg, button = await get_user_settings(from_user)
    await send_message(message, msg, button)


@new_task
async def add_file(_, message, ftype, rfunc, target_user_id=None):
    user = message.from_user or message.sender_chat
    user_id = target_user_id or (user.id if user else 0)
    if not user_id:
        return
    handler_dict[user_id] = False
    des_dir = ""
    if ftype == "THUMBNAIL":
        if message.text and message.text.startswith(("http://", "https://")):
            url = message.text.strip()
            downloaded = await download_image_thumb(url)
            if downloaded and await aiopath.exists(downloaded):
                des_dir = f"thumbnails/{user_id}.jpg"
                await makedirs("thumbnails", exist_ok=True)
                await move(downloaded, des_dir)
            else:
                await delete_message(message)
                await send_message(message, "Failed to download thumbnail from Image URL!")
                await rfunc()
                return
        else:
            des_dir = await create_thumb(message, user_id)
    elif ftype in ["THUMB_WM_IMAGE", "WM_IMAGE"]:
        await makedirs("watermark", exist_ok=True)
        filename = f"{user_id}_thumb_wm.jpg" if ftype == "THUMB_WM_IMAGE" else f"{user_id}_wm.jpg"
        target_path = f"watermark/{filename}"
        if message.text and message.text.startswith(("http://", "https://")):
            url = message.text.strip()
            downloaded = await download_image_thumb(url)
            if downloaded and await aiopath.exists(downloaded):
                await move(downloaded, target_path)
                des_dir = target_path
            else:
                await delete_message(message)
                await send_message(message, "Failed to download image from URL!")
                await rfunc()
                return
        else:
            dl_path = await create_thumb(message, f"{user_id}_wm_tmp")
            if dl_path and await aiopath.exists(dl_path):
                await move(dl_path, target_path)
                des_dir = target_path
            else:
                await delete_message(message)
                await send_message(message, "Failed to process photo!")
                await rfunc()
                return
    elif ftype == "RCLONE_CONFIG":
        rpath = f"{getcwd()}/rclone/"
        await makedirs(rpath, exist_ok=True)
        des_dir = f"{rpath}{user_id}.conf"
        await message.download(file_name=des_dir)
    elif ftype == "TOKEN_PICKLE":
        tpath = f"{getcwd()}/tokens/"
        await makedirs(tpath, exist_ok=True)
        des_dir = f"{tpath}{user_id}.pickle"
        await message.download(file_name=des_dir)
    elif ftype == "USER_COOKIE_FILE":
        cpath = f"{getcwd()}/cookies/{user_id}"
        await makedirs(cpath, exist_ok=True)
        des_dir = f"{cpath}/cookies.txt"
        await message.download(file_name=des_dir)
        report = normalize_cookie_file(des_dir)
        if report["error"] or not report["total"]:
            await send_message(
                message,
                f"❌ Cookies not saved: {describe_cookie_report(report)}\n"
                "Export Netscape-format cookies.txt while logged in to YouTube.",
            )
            with suppress(Exception):
                await remove(des_dir)
            des_dir = ""
        else:
            await send_message(
                message, f"🍪 Cookies saved: {describe_cookie_report(report)}"
            )
    await delete_message(message)
    if des_dir:
        update_user_ldata(user_id, ftype, des_dir)
        if ftype == "THUMBNAIL":
            update_user_ldata(user_id, "THUMBNAIL_MODE", "custom")
        await database.update_user_doc(user_id, ftype, des_dir)
    await rfunc()


def validate_ffmpeg_cmds(value):
    if not isinstance(value, dict):
        raise ValueError("Input must be a Python dictionary!")
    for key, cmds in list(value.items()):
        k_lower = key.strip().lower()
        if k_lower == "watermark" and not Config.ENABLE_WATERMARK:
            raise ValueError("Watermark command option is blocked/disabled by Bot Owner!")
        if k_lower == "compress" and not Config.ENABLE_COMPRESS:
            raise ValueError("Compress command option is blocked/disabled by Bot Owner!")
        if k_lower == "encode" and not Config.ENABLE_ENCODE:
            raise ValueError("Encode command option is blocked/disabled by Bot Owner!")
        if isinstance(cmds, str):
            cmds = [cmds]
            value[key] = cmds
        if not isinstance(cmds, (list, tuple)) or not cmds:
            raise ValueError(f"'{key}' must be a non-empty list of command strings")
        for cmd in cmds:
            if not isinstance(cmd, str) or not cmd.strip():
                raise ValueError(f"'{key}' has an empty or non-string command")
            if "-i" not in cmd.split():
                raise ValueError(f"'{key}' has a command without an -i input: {cmd}")


@new_task
async def add_one(_, message, option, rfunc, target_user_id=None):
    user = message.from_user or message.sender_chat
    user_id = target_user_id or (user.id if user else 0)
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    value = message.text
    if value.startswith("{") and value.endswith("}"):
        try:
            value = literal_eval(value)
            if not isinstance(value, dict):
                raise ValueError("Expected a dict")
            if option == "DRIVE_CAT":
                parsed = {}
                for k, v in value.items():
                    if k.strip().casefold() == "default":
                        raise ValueError(
                            '"Default" is reserved and cannot be used as a category name'
                        )
                    parts = str(v).split("|", 1)
                    did = parts[0].strip()
                    ilink = parts[1].strip() if len(parts) > 1 else ""
                    parsed[k.strip()] = {"drive_id": did, "index_link": ilink}
                value = parsed
            elif option == "FFMPEG_CMDS":
                validate_ffmpeg_cmds(value)
            if user_dict.get(option):
                user_dict[option].update(value)
            else:
                update_user_ldata(user_id, option, value)
        except Exception as e:
            await send_message(message, str(e))
            return
    else:
        await send_message(message, "Input must be a valid Python dictionary!")
        return
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


@new_task
async def remove_one(_, message, option, rfunc, target_user_id=None):
    user = message.from_user or message.sender_chat
    user_id = target_user_id or (user.id if user else 0)
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    names = [name.strip() for name in message.text.split("/") if name.strip()]
    opt_dict = user_dict.get(option)
    if isinstance(opt_dict, dict):
        for name in names:
            opt_dict.pop(name, None)
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


@new_task
async def set_option(_, message, option, rfunc, target_user_id=None):
    user = message.from_user or message.sender_chat
    user_id = target_user_id or (user.id if user else 0)
    handler_dict[user_id] = False
    value = message.text
    if option == "LEECH_SPLIT_SIZE":
        if not value.isdigit():
            value = get_size_bytes(value)
        value = min(int(value), TgClient.MAX_SPLIT_SIZE)
    elif option == "EXCLUDED_EXTENSIONS":
        fx = value.split()
        value = ["aria2", "!qB"]
        for x in fx:
            x = x.lstrip(".")
            value.append(x.strip().lower())
    elif option == "YT_TAGS":
        if isinstance(value, str):
            value = [tag.strip() for tag in value.split(",") if tag.strip()]
        elif not isinstance(value, list):
            await send_message(message, "YT Tags must be a comma-separated string.")
            return
    elif option == "YT_CATEGORY_ID":
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        elif not isinstance(value, int):
            await send_message(message, "YT Category ID must be a whole number.")
            return
    elif option == "YT_PRIVACY_STATUS":
        allowed_statuses = ["public", "private", "unlisted"]
        if not isinstance(value, str) or value.lower() not in allowed_statuses:
            await send_message(
                message,
                f"YT Privacy Status must be one of: {', '.join(allowed_statuses)}.",
            )
            return
        value = value.lower()
    elif option in [
        "SET_ALL_METADATA",
        "METADATA",
        "AUDIO_METADATA",
        "VIDEO_METADATA",
        "SUBTITLE_METADATA",
    ]:
        parsed_metadata_dict = {}
        if value and isinstance(value, str):
            if value.strip() == "":
                value = {}
            else:
                parts = []
                current = ""
                i = 0
                while i < len(value):
                    if value[i] == "\\" and i + 1 < len(value) and value[i + 1] == "|":
                        current += "|"
                        i += 2
                    elif value[i] == "|":
                        parts.append(current)
                        current = ""
                        i += 1
                    else:
                        current += value[i]
                        i += 1
                if current:
                    parts.append(current)

                for part in parts:
                    if "=" in part:
                        key, val_str = part.split("=", 1)
                        parsed_metadata_dict[key.strip()] = val_str.strip()
                if not parsed_metadata_dict and value.strip() != "":
                    await send_message(
                        message,
                        "Malformed metadata string. Format: key1=value1|key2=value2. Use \\| to escape pipe characters.",
                    )
                    return
                value = parsed_metadata_dict
        else:
            value = {}

    elif option == "FFMPEG_DUMP":
        user_dump = user_data.get(user_id, {}).get("FFMPEG_DUMP", {})
        if not isinstance(user_dump, dict):
            user_dump = {}
        if value.startswith("{") and value.endswith("}"):
            try:
                parsed = literal_eval(value)
                if not isinstance(parsed, dict):
                    raise ValueError("Expected a dict")
                for k, dest in parsed.items():
                    user_dump[k.lower().strip()] = str(dest).strip()
            except Exception as e:
                await send_message(message, f"Invalid dict format: {e}")
                return
        elif ":" in value:
            parts = value.split(":", 1)
            k = parts[0].strip().lower()
            dest = parts[1].strip()
            user_dump[k] = dest
        else:
            await send_message(message, "Format must be KEY: DUMP_DEST or a dict {'KEY': 'DUMP_DEST'}")
            return
        value = user_dump
    elif option == "FFMPEG_CMDS":
        user_ff = user_data.get(user_id, {}).get("FFMPEG_CMDS", {})
        if not isinstance(user_ff, dict):
            user_ff = {}
        if value.startswith("{") and value.endswith("}"):
            try:
                parsed = literal_eval(value)
                if not isinstance(parsed, dict):
                    raise ValueError("Expected a dict")
                validate_ffmpeg_cmds(parsed)
                for k, cmds in parsed.items():
                    user_ff[k.lower().strip()] = cmds if isinstance(cmds, list) else [cmds]
            except Exception as e:
                await send_message(message, f"Invalid dict format: {e}")
                return
        elif ":" in value:
            parsed = {}
            for line in value.split("\n"):
                if ":" in line:
                    parts = line.split(":", 1)
                    k = parts[0].strip().lower()
                    cmd = parts[1].strip()
                    if k and cmd:
                        if k not in parsed:
                            parsed[k] = []
                        parsed[k].append(cmd)
            if parsed:
                try:
                    validate_ffmpeg_cmds(parsed)
                    user_ff.update(parsed)
                except Exception as e:
                    await send_message(message, f"Invalid command: {e}")
                    return
            else:
                await send_message(message, "Invalid format! Format must be 'KEY: command' or a Python dict")
                return
        else:
            await send_message(message, "Format must be 'KEY: command' or a dict {'KEY': ['cmd']}")
            return
        value = user_ff
    elif option in ["THUMB_WM_IMAGE", "WM_IMAGE"]:
        if value and value.startswith(("http://", "https://")):
            downloaded = await download_image_thumb(value.strip())
            if downloaded and await aiopath.exists(downloaded):
                await makedirs("watermark", exist_ok=True)
                filename = f"{user_id}_thumb_wm.jpg" if option == "THUMB_WM_IMAGE" else f"{user_id}_wm.jpg"
                target_path = f"watermark/{filename}"
                await move(downloaded, target_path)
                value = target_path
            else:
                await send_message(message, "Failed to download image from URL!")
                return
    elif option in ["UPLOAD_PATHS", "YT_DLP_OPTIONS", "DRIVE_CAT"]:
        if value.startswith("{") and value.endswith("}"):
            try:
                value = literal_eval(sub(r"\s+", " ", value))
                if not isinstance(value, dict):
                    raise ValueError("Expected a dict")
                if option == "DRIVE_CAT":
                    parsed = {}
                    for k, v in value.items():
                        if k.strip().casefold() == "default":
                            raise ValueError(
                                '"Default" is reserved and cannot be used as a category name'
                            )
                        parts = str(v).split("|", 1)
                        did = parts[0].strip()
                        ilink = parts[1].strip() if len(parts) > 1 else ""
                        parsed[k.strip()] = {"drive_id": did, "index_link": ilink}
                    value = parsed
            except Exception as e:
                await send_message(message, str(e))
                return
        else:
            await send_message(message, "Input must be a valid Python dictionary!")
            return
    update_user_ldata(user_id, option, value)
    if option == "SET_ALL_METADATA":
        update_user_ldata(user_id, "SET_ALL_METADATA_ENABLE", True)
    await delete_message(message)
    await rfunc()
    await database.update_user_data(user_id)


async def get_menu(option, message, user_id, start=0):
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})

    file_dict = {
        "THUMBNAIL": f"thumbnails/{user_id}.jpg",
        "RCLONE_CONFIG": f"rclone/{user_id}.conf",
        "TOKEN_PICKLE": f"tokens/{user_id}.pickle",
        "USER_COOKIE_FILE": f"cookies/{user_id}/cookies.txt",
        "THUMB_WM_IMAGE": f"watermark/{user_id}_thumb_wm.jpg",
        "WM_IMAGE": f"watermark/{user_id}_wm.jpg",
    }

    buttons = ButtonMaker()
    if option in ["THUMBNAIL", "RCLONE_CONFIG", "TOKEN_PICKLE", "USER_COOKIE_FILE", "THUMB_WM_IMAGE", "WM_IMAGE"]:
        key = "file"
    else:
        key = "set"
    if option == "FFMPEG_CMDS":
        buttons.data_button("Add/Edit Preset", f"userset {user_id} set FFMPEG_CMDS", "header")
        buttons.data_button("Add Multiple Presets", f"userset {user_id} addone FFMPEG_CMDS", "header")
        if user_dict.get("FFMPEG_CMDS", False):
            buttons.data_button("Delete Specific Preset", f"userset {user_id} rmone FFMPEG_CMDS")
            buttons.data_button("Reset All Presets", f"userset {user_id} reset FFMPEG_CMDS")
    else:
        buttons.data_button(
            "Change" if user_dict.get(option, False) else "Set",
            f"userset {user_id} {key} {option}",
        )
        if option in ["THUMB_WM_IMAGE", "WM_IMAGE"]:
            buttons.data_button("Set Image URL Text", f"userset {user_id} set {option}")
        if user_dict.get(option, False):
            if option == "THUMBNAIL":
                buttons.data_button(
                    "View Thumb", f"userset {user_id} view THUMBNAIL", "header"
                )
            elif option in ["YT_DLP_OPTIONS", "UPLOAD_PATHS", "DRIVE_CAT"]:
                buttons.data_button(
                    "Add One", f"userset {user_id} addone {option}", "header"
                )
                buttons.data_button(
                    "Remove One", f"userset {user_id} rmone {option}", "header"
                )

            if key != "file":
                buttons.data_button("Reset", f"userset {user_id} reset {option}")
            elif await aiopath.exists(file_dict[option]):
                buttons.data_button("Remove", f"userset {user_id} remove {option}")

    if option == "FFMPEG_CMDS":
        user_ff = user_dict.get("FFMPEG_CMDS") or {}
        global_ff = Config.FFMPEG_CMDS or {}
        merged_ff = {**global_ff, **user_ff} if isinstance(global_ff, dict) else dict(user_ff)
        avail_keys = list(merged_ff.keys())
        if avail_keys:
            page_items = avail_keys[start : start + 5]
            lines = []
            for idx, k in enumerate(page_items, start=start):
                source_tag = " (User)" if k in user_ff else " (Global)"
                cmds = merged_ff[k]
                cmds_str = ", ".join(cmds) if isinstance(cmds, list) else str(cmds)
                lines.append(f"{idx + 1}. • <code>-ff {escape(str(k))}</code>{source_tag}: <code>{escape(cmds_str)}</code>")
            val = "\n" + "\n".join(lines)
            if len(avail_keys) > 5:
                for x in range(0, len(avail_keys), 5):
                    buttons.data_button(
                        f"{int(x / 5) + 1}", f"userset {user_id} ffpage {x}", position="footer"
                    )
        else:
            val = "<b>No commands configured.</b>"

    if option in leech_options:
        back_to = "leech"
    elif option in rclone_options:
        back_to = "rclone"
    elif option in gdrive_options:
        back_to = "gdrive"
    elif option in yt_options:
        back_to = "yttools"
    elif option in ffset_options:
        back_to = "ffset"
    elif option in advanced_options:
        back_to = "advanced"
    elif option in uphoster_options:
        if option.endswith("_UPLOAD_URL") or option.endswith("_API_KEY"):
            back_to = "host_api_tools"
        else:
            back_to = option.split("_")[0].lower()
    elif option in mega_options:
        back_to = "mega"
    elif option in seedr_options:
        back_to = "seedr"
    elif option.startswith("ENC_"):
        back_to = "encode_menu"
    elif option.startswith("COM_"):
        back_to = "compress_menu"
    elif option.startswith("WM_"):
        back_to = "watermark_menu"
    else:
        back_to = "back"
    buttons.data_button("◀️ Back", f"userset {user_id} {back_to}", "footer")
    buttons.data_button(
        "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
    )
    val_setting = user_dict.get(option)
    val = ""
    if option in file_dict and await aiopath.exists(file_dict[option]):
        val = "<b>Exists</b>"
    elif option == "LEECH_SPLIT_SIZE":
        val = get_readable_file_size(val_setting) if val_setting else "<b>Not Set</b>"
    elif option in ["LEECH_PREFIX", "LEECH_SUFFIX", "LEECH_CAPTION", "LEECH_FONT", "WM_TEXT", "WM_COLOR", "WM_SIZE", "WM_POSITION"]:
        val = f"<code>{escape(str(val_setting))}</code>" if val_setting else "<b>Not Set</b>"
    elif option in ["SET_ALL_METADATA", "METADATA", "AUDIO_METADATA", "VIDEO_METADATA", "SUBTITLE_METADATA"]:
        current_meta_val = user_dict.get(option)
        if isinstance(current_meta_val, dict) and current_meta_val:
            val = ", ".join(
                f"{k}={escape(str(v))}" for k, v in current_meta_val.items()
            )
            val = f"<code>{val}</code>"
        elif isinstance(current_meta_val, str) and current_meta_val:
            val = (
                f"<code>{escape(current_meta_val)}</code> [<i>Legacy format</i>]"
            )
        elif not current_meta_val:
            val = "<b>Not Set</b>"

        if val is None:
            val = "<b>Not Set</b>"

    elif option == "DRIVE_CAT":
        default_id = user_dict.get("GDRIVE_ID") or Config.GDRIVE_ID
        default_index = user_dict.get("INDEX_URL") or Config.INDEX_URL
        lines = [f"• <b>Default:</b> <code>{escape(str(default_id))}</code>"]
        if default_index:
            lines[0] += f" | <code>{escape(default_index)}</code>"
        if isinstance(val_setting, dict):
            for k, v in val_setting.items():
                did = v.get("drive_id", "")
                ilink = v.get("index_link", "")
                ilink_part = f" | <code>{escape(ilink)}</code>" if ilink else ""
                lines.append(
                    f"• <b>{escape(k)}:</b> <code>{escape(did)}</code>{ilink_part}"
                )
            val = "\n".join(lines)
        elif not val_setting:
            val = "<b>Not Set</b>"
    elif option == "FFMPEG_DUMP":
        user_dump = user_dict.get("FFMPEG_DUMP") or Config.FFMPEG_DUMP or {}
        if isinstance(user_dump, dict) and user_dump:
            val = "\n" + "\n".join([f"• <b>{escape(str(k)).upper()}:</b> <code>{escape(str(v))}</code>" for k, v in user_dump.items()])
        else:
            val = "<b>Not Set (Output sent to default DM)</b>"
    elif option in ["YT_DLP_OPTIONS", "UPLOAD_PATHS"]:
        val = f"<code>{escape(str(val))}</code>" if val else "<b>Not Set</b>"

    text = f"""<b>⚙️ Setting Configuration: {option}</b>

<blockquote>• <b>Current Value:</b> {val if val else "<b>Not Set</b>"}
• <b>Expected Input Type:</b> {user_settings_text[option][0]}
• <b>Description:</b> {user_settings_text[option][1]}</blockquote>"""

    await edit_message(message, text, buttons.build_menu(2))


async def event_handler(client, query, pfunc, rfunc, photo=False, document=False):
    user_id = query.from_user.id
    handler_dict[user_id] = True
    start_time = update_time = time()

    async def event_filter(_, __, event):
        user = event.from_user or event.sender_chat
        if not user or user.id != user_id or event.chat.id != query.message.chat.id:
            return False
        if photo:
            mtype = event.photo or event.document or (event.text and event.text.startswith(("http://", "https://")))
        elif document:
            mtype = event.document
        else:
            mtype = event.text
        return bool(mtype)

    handler = client.add_handler(
        MessageHandler(pfunc, filters=create(event_filter)), group=-1
    )

    while handler_dict[user_id]:
        await sleep(0.5)
        if time() - start_time > 60:
            handler_dict[user_id] = False
            await rfunc()
        elif time() - update_time > 8 and handler_dict[user_id]:
            update_time = time()
            msg = await client.get_messages(query.message.chat.id, query.message.id)
            lines = msg.text.split("\n")
            lines[-1] = (
                f"⏱️ <b>Time Left:</b> <code>{round(60 - (time() - start_time), 1)}s</code>"
            )
            await edit_message(msg, "\n".join(lines), msg.reply_markup)
    client.remove_handler(*handler)


@new_task
async def edit_user_settings(client, query):
    from_user = query.from_user
    user_id = from_user.id
    name = from_user.mention
    message = query.message
    data = query.data.split()

    handler_dict[user_id] = False
    thumb_path = f"thumbnails/{user_id}.jpg"
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"
    yt_cookie_path = f"cookies/{user_id}/cookies.txt"

    user_dict = user_data.get(user_id, {})
    if user_id != int(data[1]):
        return await query.answer("This menu is not for you!", show_alert=True)
    elif data[2] == "setevent":
        await query.answer()
    elif data[2] in [
        "enc_com_wm",
        "encode_menu",
        "compress_menu",
        "watermark_menu",
    ]:
        from ..helper.telegram_helper.filters import CustomFilters
        if not await CustomFilters.sudo(client, query):
            return await query.answer(
                "Not allowed! This feature is restricted to Owner/Sudo users only.",
                show_alert=True,
            )
        if data[2] == "encode_menu" and not Config.ENABLE_ENCODE:
            return await query.answer("Encode command option is blocked/disabled by Bot Owner!", show_alert=True)
        if data[2] == "compress_menu" and not Config.ENABLE_COMPRESS:
            return await query.answer("Compress command option is blocked/disabled by Bot Owner!", show_alert=True)
        if data[2] == "watermark_menu" and not Config.ENABLE_WATERMARK:
            return await query.answer("Watermark command option is blocked/disabled by Bot Owner!", show_alert=True)
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] in [
        "general",
        "mirror",
        "leech",
        "thumb_select",
        "thumb_wm_menu",
        "lfont",
        "vtools",
        "uphoster",
        "gofile",
        "buzzheavier",
        "pixeldrain",
        "devuploads",
        "vikingfile",
        "ffset",
        "advanced",
        "gdrive",
        "rclone",
    ]:
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] == "thumb_mode":
        mode = data[3]
        update_user_ldata(user_id, "THUMBNAIL_MODE", mode)
        await database.update_user_data(user_id)
        if mode == "custom" and not await aiopath.exists(thumb_path):
            await query.answer("Please set a custom thumbnail image!", show_alert=True)
        else:
            await query.answer()
        await update_user_settings(query, "thumb_select")
    elif data[2] == "mega":
        await query.answer()
        msg, button = await get_user_settings(query.from_user, "mega")
        await edit_message(message, msg, button)
        mega_email = user_dict.get("MEGA_EMAIL", "")
        mega_password = user_dict.get("MEGA_PASSWORD", "")
        if mega_email and mega_password:
            info_text = await get_mega_account_info(mega_email, mega_password)
            msg += f"\n\n{info_text}"
            await edit_message(message, msg, button)
    elif data[2] == "seedr":
        await query.answer()
        msg, button = await get_user_settings(query.from_user, "seedr")
        await edit_message(message, msg, button)
        seedr_email = user_dict.get("SEEDR_EMAIL", "")
        seedr_password = user_dict.get("SEEDR_PASSWORD", "")
        if seedr_email and seedr_password:
            try:
                sc = SeedrClient(seedr_email, seedr_password)
                await sc.login()
                space_max, space_used = await sc.get_space()
                msg += f"\n\n<b>Seedr Storage Space:</b> <code>{get_readable_file_size(space_used)} / {get_readable_file_size(space_max)}</code>"
            except Exception as e:
                msg += f"\n\n<b>Seedr Login Failed:</b> {escape(str(e))}"
            await edit_message(message, msg, button)
    elif data[2] == "clear_seedr":
        await query.answer("Clearing Seedr storage...", show_alert=False)
        seedr_email = user_dict.get("SEEDR_EMAIL", "")
        seedr_password = user_dict.get("SEEDR_PASSWORD", "")
        if seedr_email and seedr_password:
            try:
                from .mirror_leech import clear_seedr_account

                t_c, f_c = await clear_seedr_account(seedr_email, seedr_password)
                await query.answer(
                    f"Removed {t_c} torrents and {f_c} folders!", show_alert=True
                )
            except Exception as e:
                await query.answer(f"Failed: {e}"[:180], show_alert=True)
        await update_user_settings(query, "seedr")
    elif data[2] == "yttools":
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] == "wm_color_select":
        await query.answer()
        user_dict = user_data.get(user_id, {})
        if len(data) > 3:
            new_color = data[3]
            update_user_ldata(user_id, "WM_COLOR", new_color)
            await database.update_user_data(user_id)
            await update_user_settings(query, "watermark_menu")
        else:
            curr_color = user_dict.get("WM_COLOR", "white")
            buttons = ButtonMaker()
            colors = ["white", "black", "red", "green", "blue", "yellow", "cyan", "magenta"]
            for col in colors:
                state = "✓ " if col == curr_color else ""
                buttons.data_button(f"{state}{col.capitalize()}", f"userset {user_id} wm_color_select {col}")
            buttons.data_button("Custom Hex Color", f"userset {user_id} menu WM_COLOR", "header")
            buttons.data_button("◀️ Back", f"userset {user_id} watermark_menu", "footer")
            buttons.data_button("❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER)
            await edit_message(message, "<b>🎨 Select Text Watermark Color:</b>", buttons.build_menu(2))
    elif data[2] == "thumb_wm_color_select":
        await query.answer()
        user_dict = user_data.get(user_id, {})
        if len(data) > 3:
            new_color = data[3]
            update_user_ldata(user_id, "THUMB_WM_COLOR", new_color)
            await database.update_user_data(user_id)
            await update_user_settings(query, "thumb_wm_menu")
        else:
            curr_color = user_dict.get("THUMB_WM_COLOR") or user_dict.get("WM_COLOR") or "white"
            buttons = ButtonMaker()
            colors = ["white", "black", "red", "green", "blue", "yellow", "cyan", "magenta"]
            for col in colors:
                state = "✓ " if col == curr_color else ""
                buttons.data_button(f"{state}{col.capitalize()}", f"userset {user_id} thumb_wm_color_select {col}")
            buttons.data_button("Custom Hex Color", f"userset {user_id} menu THUMB_WM_COLOR", "header")
            buttons.data_button("◀️ Back", f"userset {user_id} thumb_wm_menu", "footer")
            buttons.data_button("❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER)
            await edit_message(message, "<b>🎨 Select Thumbnail Text Watermark Color:</b>", buttons.build_menu(2))
    elif data[2] in ["thumb_wm_img_pos_select", "thumb_wm_text_pos_select"]:
        await query.answer()
        user_dict = user_data.get(user_id, {})
        opt_key = "THUMB_WM_IMAGE_POSITION" if data[2] == "thumb_wm_img_pos_select" else "THUMB_WM_TEXT_POSITION"
        if len(data) > 3:
            new_pos = data[3]
            update_user_ldata(user_id, opt_key, new_pos)
            await database.update_user_data(user_id)
            await update_user_settings(query, "thumb_wm_menu")
        else:
            curr_pos = user_dict.get(opt_key) or user_dict.get("THUMB_WM_POSITION") or user_dict.get("WM_POSITION") or "Top-Left"
            buttons = ButtonMaker()
            positions = [
                "Top-Left", "Top-Center", "Top-Right",
                "Center-Left", "Center", "Center-Right",
                "Bottom-Left", "Bottom-Center", "Bottom-Right"
            ]
            for pos in positions:
                state = "✓ " if pos == curr_pos else ""
                buttons.data_button(f"{state}{pos}", f"userset {user_id} {data[2]} {pos}")
            buttons.data_button("◀️ Back", f"userset {user_id} thumb_wm_menu", "footer")
            buttons.data_button("❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER)
            title = "🖼️ Image" if "img" in data[2] else "📝 Text"
            await edit_message(message, f"<b>📍 Select Thumbnail {title} Watermark Position:</b>", buttons.build_menu(3))
    elif data[2] in ["wm_img_pos_select", "wm_text_pos_select", "wm_pos_select"]:
        await query.answer()
        user_dict = user_data.get(user_id, {})
        opt_key = "WM_IMAGE_POSITION" if data[2] == "wm_img_pos_select" else ("WM_TEXT_POSITION" if data[2] == "wm_text_pos_select" else "WM_POSITION")
        if len(data) > 3:
            new_pos = data[3]
            update_user_ldata(user_id, opt_key, new_pos)
            await database.update_user_data(user_id)
            await update_user_settings(query, "watermark_menu")
        else:
            curr_pos = user_dict.get(opt_key) or user_dict.get("WM_POSITION") or "Top-Left"
            buttons = ButtonMaker()
            positions = [
                "Top-Left", "Top-Center", "Top-Right",
                "Center-Left", "Center", "Center-Right",
                "Bottom-Left", "Bottom-Center", "Bottom-Right"
            ]
            for pos in positions:
                state = "✓ " if pos == curr_pos else ""
                buttons.data_button(f"{state}{pos}", f"userset {user_id} {data[2]} {pos}")
            buttons.data_button("◀️ Back", f"userset {user_id} watermark_menu", "footer")
            buttons.data_button("❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER)
            title = "🖼️ Image" if "img" in data[2] else ("📝 Text" if "text" in data[2] else "")
            await edit_message(message, f"<b>📍 Select {title} Watermark Position:</b>", buttons.build_menu(3))
    elif data[2] == "uphoster_destinations":
        await query.answer()
        user_dict = user_data.get(user_id, {})
        uphoster_service = user_dict.get("UPHOSTER_SERVICE", "gofile")
        selected_services = uphoster_service.split(",") if uphoster_service else []

        if len(data) > 3:
            service = data[3]
            if service in selected_services:
                if len(selected_services) > 1:
                    selected_services.remove(service)
                else:
                    await query.answer(
                        "At least one destination service must be selected!", show_alert=True
                    )
            else:
                selected_services.append(service)
            new_services = ",".join(selected_services)
            update_user_ldata(user_id, "UPHOSTER_SERVICE", new_services)
            await database.update_user_data(user_id)
            selected_services = new_services.split(",")
        else:
            selected_services = (
                uphoster_service.split(",") if uphoster_service else ["gofile"]
            )

        buttons = ButtonMaker()
        for service in [
            "gofile",
            "buzzheavier",
            "pixeldrain",
            "devuploads",
            "vikingfile",
            "gdflix", "hubcloud", "filepress", "lulustream",
            "streamtape", "filemoon", "uploadhub", "filestreams",
        ]:
            state = "✓" if service in selected_services else ""
            buttons.data_button(
                f"{service.capitalize()} {state}",
                f"userset {user_id} uphoster_destinations {service}",
            )

        buttons.data_button("◀️ Back", f"userset {user_id} back uphoster", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )

        text = "<b>🌐 Select Active Uphoster Destinations:</b>"
        await edit_message(message, text, buttons.build_menu(2))
    elif data[2] == "session_menu":
        await query.answer()
        user_dict = user_data.get(user_id, {})
        mode = user_dict.get("TELEGRAM_SESSION_MODE", "disabled")
        labels = {
            "telegram": "Telegram Links",
            "upload": "Upload",
            "both": "Telegram Links + Upload",
            "disabled": "Disabled",
        }
        buttons = ButtonMaker()
        if user_dict.get("TELEGRAM_SESSION_STRING"):
            buttons.data_button("✏️ Change Session String", f"userset {user_id} session_set")
            buttons.data_button("🗑️ Reset Session String", f"userset {user_id} session_reset")
            buttons.data_button(
                f"Telegram Links: {'✓' if mode in ('telegram', 'both') else '✗'}",
                f"userset {user_id} session_mode telegram",
            )
            buttons.data_button(
                f"Upload: {'✓' if mode in ('upload', 'both') else '✗'}",
                f"userset {user_id} session_mode upload",
            )
            buttons.data_button(
                f"Both: {'✓' if mode == 'both' else '✗'}",
                f"userset {user_id} session_mode both",
            )
            buttons.data_button("Disable", f"userset {user_id} session_mode disabled")
            current = labels.get(mode, "Disabled")
            status = "Configured"
        else:
            buttons.data_button("➕ Set Session String", f"userset {user_id} session_set")
            current = "Disabled"
            status = "Not configured"
        buttons.data_button("◀️ Back", f"userset {user_id} advanced", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        await edit_message(
            message,
            f"""<b>🔐 Personal Telegram Session</b>

<blockquote>• <b>Status:</b> {status}
• <b>Mode:</b> <b>{current}</b>

<b>Telegram Links</b> = use this session for Telegram-link downloads.
<b>Upload</b> = use this session for Telegram uploads.
<b>Both</b> = use it for both.
The session string is a private login credential and is never shown back.</blockquote>""",
            buttons.build_menu(2),
        )
    elif data[2] == "session_mode":
        await query.answer()
        mode = data[3] if len(data) > 3 else "disabled"
        user_dict = user_data.get(user_id, {})
        if mode not in {"disabled", "telegram", "upload", "both"}:
            return
        if mode != "disabled" and not user_dict.get("TELEGRAM_SESSION_STRING"):
            return await query.answer("Set a session string first.", show_alert=True)
        update_user_ldata(user_id, "TELEGRAM_SESSION_MODE", mode)
        await database.update_user_data(user_id)
        if mode == "disabled":
            await TgClient.stop_personal_user(user_id)
        await query.answer(f"Session mode: {mode}")
        await update_user_settings(query, stype="advanced")
    elif data[2] == "session_reset":
        await query.answer("Resetting personal session...", show_alert=False)
        user_dict = user_data.get(user_id, {})
        user_dict.pop("TELEGRAM_SESSION_STRING", None)
        user_dict.pop("TELEGRAM_SESSION_MODE", None)
        await TgClient.reset_personal_user(user_id)
        await database.update_user_data(user_id)
        await update_user_settings(query, stype="advanced")
    elif data[2] == "session_set":
        await query.answer()
        buttons = ButtonMaker()
        buttons.data_button("Stop", f"userset {user_id} session_menu")
        buttons.data_button("◀️ Back", f"userset {user_id} session_menu", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        await edit_message(
            message,
            "<b>🔐 Set Personal Telegram Session</b>\n\n"
            "<blockquote>Send your Pyrogram session string now. "
            "It will be validated, stored privately, and never echoed back.\n"
            "Do not send your bot token or any other credential.</blockquote>",
            buttons.build_menu(1),
        )

        async def _save_session(_, msg):
            session = (msg.text or "").strip()
            if not session or " " in session:
                await send_message(msg, "Invalid session string format.")
                return
            await TgClient.stop_personal_user(user_id)
            personal = await TgClient.get_personal_user(user_id, session)
            if not personal:
                await send_message(
                    msg,
                    "❌ Session validation failed. The session was not saved.",
                )
                return
            update_user_ldata(user_id, "TELEGRAM_SESSION_STRING", session)
            if not user_data.get(user_id, {}).get("TELEGRAM_SESSION_MODE"):
                update_user_ldata(user_id, "TELEGRAM_SESSION_MODE", "disabled")
            await database.update_user_data(user_id)
            await send_message(msg, "✅ Personal Telegram session saved and validated.")
            await update_user_settings(query, stype="advanced")

        rfunc = partial(update_user_settings, query, stype="advanced")
        await event_handler(client, query, _save_session, rfunc)
    elif data[2] == "menu":
        if data[3] == "FFMPEG_CMDS" and not Config.ENABLE_FFMPEG_CMDS:
            return await query.answer("FFmpeg CMDs preset option is blocked/disabled by Bot Owner!", show_alert=True)
        if data[3].startswith("ENC_") and not Config.ENABLE_ENCODE:
            return await query.answer("Encode command option is blocked/disabled by Bot Owner!", show_alert=True)
        if data[3].startswith("COM_") and not Config.ENABLE_COMPRESS:
            return await query.answer("Compress command option is blocked/disabled by Bot Owner!", show_alert=True)
        if data[3].startswith("WM_") and not Config.ENABLE_WATERMARK:
            return await query.answer("Watermark command option is blocked/disabled by Bot Owner!", show_alert=True)
        await query.answer()
        await get_menu(data[3], message, user_id)
    elif data[2] == "ffpage":
        await query.answer()
        start = int(data[3]) if len(data) > 3 and data[3].isdigit() else 0
        await get_menu("FFMPEG_CMDS", message, user_id, start=start)
    elif data[2] == "tog":
        if data[3] in ["ENABLE_ENCODE", "ENABLE_COMPRESS", "ENABLE_WATERMARK"]:
            from ..helper.telegram_helper.filters import CustomFilters
            if not await CustomFilters.sudo(client, query):
                return await query.answer(
                    "Not allowed! This feature is restricted to Owner/Sudo users only.",
                    show_alert=True,
                )
        await query.answer()
        update_user_ldata(user_id, data[3], data[4] == "t")
        if len(data) > 5:
            back_to = data[5]
        else:
            if data[3] == "STOP_DUPLICATE":
                back_to = "gdrive"
            elif data[3] == "drive_cat_mode":
                back_to = "mirror"
            elif data[3] in ["USER_TOKENS", "USE_DEFAULT_COOKIE"]:
                back_to = "general"
            elif data[3] == "GOFILE_AUTO_CREATE_FOLDER":
                back_to = "gofile"
            elif data[3] == "SEEDR_DELETE_FOLDER":
                back_to = "seedr"
            elif data[3] in ["AUTO_MERGE", "SAVE_FILES"]:
                back_to = "vtools"
            elif data[3] in ["SET_ALL_METADATA_ENABLE", "STRIP_METADATA_ENABLE"]:
                back_to = "ffset"
            elif data[3] == "ENABLE_ENCODE":
                back_to = "encode_menu"
            elif data[3] == "ENABLE_COMPRESS":
                back_to = "compress_menu"
            elif data[3] == "ENABLE_WATERMARK":
                back_to = "watermark_menu"
            elif data[3] == "ENABLE_FFMPEG_CMDS":
                back_to = "ffset"
            elif data[3] == "AUTO_MIRROR":
                back_to = "mirror"
            elif data[3] == "AUTO_DDL":
                back_to = "uphoster"
            else:
                back_to = "leech"
        await update_user_settings(query, stype=back_to)
        await database.update_user_data(user_id)
    elif data[2] == "file":
        await query.answer()
        buttons = ButtonMaker()
        text = user_settings_text[data[3]][2]
        buttons.data_button("Stop", f"userset {user_id} menu {data[3]} stop")
        buttons.data_button("◀️ Back", f"userset {user_id} menu {data[3]}", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        prompt_title = data[3].replace("_", " ").title()
        new_message_text = f"<b>Upload {prompt_title}</b>\n\n{text}"
        await edit_message(message, new_message_text, buttons.build_menu(1))
        rfunc = partial(get_menu, data[3], message, user_id)
        rfunc_back = partial(update_user_settings, query, stype="thumb_select") if data[3] == "THUMBNAIL" else rfunc
        pfunc = partial(add_file, ftype=data[3], rfunc=rfunc_back, target_user_id=user_id)
        await event_handler(
            client,
            query,
            pfunc,
            rfunc,
            photo=data[3] in ["THUMBNAIL", "THUMB_WM_IMAGE", "WM_IMAGE"],
            document=data[3] not in ["THUMBNAIL", "THUMB_WM_IMAGE", "WM_IMAGE"],
        )
    elif data[2] in ["set", "addone", "rmone"]:
        await query.answer()
        buttons = ButtonMaker()
        if data[2] == "set":
            text = user_settings_text[data[3]][2]
            func = set_option
        elif data[2] == "addone":
            text = f"<blockquote><b>Add entry to {data[3]}:</b>\nExample: <code>{{'key1': 'value1', 'key2': 'value2'}}</code>\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>"
            func = add_one
        elif data[2] == "rmone":
            text = f"<blockquote><b>Remove entry from {data[3]}:</b>\nExample: <code>key1/key2</code>\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>"
            func = remove_one
        buttons.data_button("Stop", f"userset {user_id} menu {data[3]} stop")
        buttons.data_button("◀️ Back", f"userset {user_id} menu {data[3]}", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        await edit_message(
            message, message.text.html + "\n\n" + text, buttons.build_menu(1)
        )
        rfunc = partial(get_menu, data[3], message, user_id)
        pfunc = partial(func, option=data[3], rfunc=rfunc, target_user_id=user_id)
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == "remove":
        await query.answer("Removed configuration!", show_alert=True)
        if data[3] in [
            "THUMBNAIL",
            "RCLONE_CONFIG",
            "TOKEN_PICKLE",
            "USER_COOKIE_FILE",
            "THUMB_WM_IMAGE",
            "WM_IMAGE",
        ]:
            if data[3] == "THUMBNAIL":
                fpath = thumb_path
            elif data[3] == "RCLONE_CONFIG":
                fpath = rclone_conf
            elif data[3] == "USER_COOKIE_FILE":
                fpath = yt_cookie_path
            elif data[3] == "TOKEN_PICKLE":
                fpath = token_pickle
            elif data[3] == "THUMB_WM_IMAGE":
                fpath = f"watermark/{user_id}_thumb_wm.jpg"
            else:
                fpath = f"watermark/{user_id}_wm.jpg"
            if await aiopath.exists(fpath):
                await remove(fpath)
            del user_dict[data[3]]
            if data[3] == "THUMBNAIL":
                update_user_ldata(user_id, "THUMBNAIL_MODE", "none")
            await database.update_user_doc(user_id, data[3])
        else:
            update_user_ldata(user_id, data[3], "")
            if data[3] == "MEGA_EMAIL":
                update_user_ldata(user_id, "MEGA_PASSWORD", "")
            elif data[3] == "SEEDR_EMAIL":
                update_user_ldata(user_id, "SEEDR_PASSWORD", "")
            await database.update_user_data(user_id)
        if data[3] == "THUMBNAIL":
            await update_user_settings(query, "thumb_select")
        else:
            await get_menu(data[3], message, user_id)
    elif data[2] == "reset":
        await query.answer("Reset option to default!", show_alert=True)
        user_dict.pop(data[3], None)
        await database.update_user_data(user_id)
        await get_menu(data[3], message, user_id)
    elif data[2] == "confirm_reset_all":
        await query.answer()
        buttons = ButtonMaker()
        buttons.data_button("Yes, Reset", f"userset {user_id} do_reset_all yes")
        buttons.data_button("No, Cancel", f"userset {user_id} do_reset_all no")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        text = "<blockquote><b>⚠️ Warning:</b> Are you sure you want to reset all your personal user settings? This action cannot be undone.</blockquote>"
        await edit_message(query.message, text, buttons.build_menu(2))
    elif data[2] == "do_reset_all":
        if data[3] == "yes":
            await query.answer("All user settings reset!", show_alert=True)
            user_dict = user_data.get(user_id, {})
            for k in list(user_dict.keys()):
                if k not in ("SUDO", "AUTH", "VERIFY_TOKEN", "VERIFY_TIME"):
                    del user_dict[k]
            for fpath in [thumb_path, rclone_conf, token_pickle, yt_cookie_path]:
                if await aiopath.exists(fpath):
                    await remove(fpath)
            await TgClient.reset_personal_user(user_id)
            await update_user_settings(query)
            await database.update_user_data(user_id)
        else:
            await query.answer("Reset cancelled.", show_alert=True)
            await update_user_settings(query)
    elif data[2] == "view":
        await query.answer()
        await send_file(message, thumb_path, name)
    elif data[2] == "export_settings":
        await query.answer("Exporting user settings...", show_alert=False)
        zip_path = f"US{user_id}.zip"
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                excluded_keys = (
                    "THUMBNAIL",
                    "RCLONE_CONFIG",
                    "TOKEN_PICKLE",
                    "USER_COOKIE_FILE",
                    "TELEGRAM_SESSION_STRING",
                    "TELEGRAM_SESSION_MODE",
                    "SUDO",
                    "AUTH",
                    "is_sudo",
                    "is_auth",
                    "VERIFY_TOKEN",
                    "VERIFY_TIME",
                    "BLACKLIST",
                )
                user_dict_copy = {
                    k: v for k, v in user_dict.items() if k not in excluded_keys
                }
                zipf.writestr("settings.json", json.dumps(user_dict_copy, indent=4))

                files_to_check = {
                    f"thumbnails/{user_id}.jpg": "thumbnail.jpg",
                    f"rclone/{user_id}.conf": "rclone.conf",
                    f"tokens/{user_id}.pickle": "token.pickle",
                    f"cookies/{user_id}/cookies.txt": "cookies.txt",
                }
                for src, arc in files_to_check.items():
                    if os.path.exists(src):
                        zipf.write(src, arc)

            await TgClient.bot.send_document(
                chat_id=user_id,
                document=zip_path,
                caption=f"<b>Exported User Settings Backup Archive</b>\n\nFilename: <code>{zip_path}</code>",
            )
            await query.answer("Exported settings archive sent to DM!", show_alert=True)
        except Exception as e:
            await query.answer(f"Export failed: {e}"[:180], show_alert=True)
        finally:
            if os.path.exists(zip_path):
                os.remove(zip_path)
    elif data[2] == "import_settings":
        await query.answer()
        buttons = ButtonMaker()
        buttons.data_button("Stop", f"userset {user_id} back main")
        buttons.data_button("◀️ Back", f"userset {user_id} back main", "footer")
        buttons.data_button(
            "❌ Close", f"userset {user_id} close", "footer", style=ButtonStyle.DANGER
        )
        prompt_text = f"<b>Import User Settings Backup</b>\n\n<blockquote><b>📥 Action Required:</b> Send your exported <code>US{user_id}.zip</code> file to restore configurations.\n⏱️ <b>Time Left:</b> <code>60 sec</code></blockquote>"
        await edit_message(message, prompt_text, buttons.build_menu(1))

        @new_task
        async def import_file_handler(_, msg):
            handler_dict[user_id] = False
            doc = msg.document
            if not doc or not doc.file_name.endswith(".zip"):
                await send_message(msg, "Invalid file! Please send a valid backup ZIP archive.")
                return
            temp_zip = os.path.abspath(f"import_{user_id}.zip")
            try:
                await msg.download(file_name=temp_zip)
                with zipfile.ZipFile(temp_zip, "r") as zipf:
                    namelist = zipf.namelist()
                    if "settings.json" in namelist:
                        settings_data = json.loads(zipf.read("settings.json").decode("utf-8"))
                        if isinstance(settings_data, dict):
                            forbidden_keys = (
                                "SUDO",
                                "AUTH",
                                "is_sudo",
                                "is_auth",
                                "VERIFY_TOKEN",
                                "VERIFY_TIME",
                                "BLACKLIST",
                                "THUMBNAIL",
                                "RCLONE_CONFIG",
                                "TOKEN_PICKLE",
                                "USER_COOKIE_FILE",
                                "TELEGRAM_SESSION_STRING",
                            )
                            for k, v in settings_data.items():
                                if k not in forbidden_keys:
                                    update_user_ldata(user_id, k, v)

                    for member in namelist:
                        if member == "settings.json" or member.endswith("/"):
                            continue
                        norm_member = os.path.normpath(member).replace("\\", "/")
                        if norm_member.startswith("..") or norm_member.startswith("/"):
                            continue

                        data_bytes = zipf.read(member)
                        if norm_member == "thumbnail.jpg" or norm_member.startswith("thumbnails/"):
                            dest = f"thumbnails/{user_id}.jpg"
                            await makedirs("thumbnails", exist_ok=True)
                            with open(dest, "wb") as f:
                                f.write(data_bytes)
                            update_user_ldata(user_id, "THUMBNAIL", dest)
                            await database.update_user_doc(user_id, "THUMBNAIL", dest)
                        elif norm_member == "rclone.conf" or norm_member.startswith("rclone/"):
                            dest = f"rclone/{user_id}.conf"
                            await makedirs("rclone", exist_ok=True)
                            with open(dest, "wb") as f:
                                f.write(data_bytes)
                            update_user_ldata(user_id, "RCLONE_CONFIG", dest)
                            await database.update_user_doc(user_id, "RCLONE_CONFIG", dest)
                        elif norm_member == "token.pickle" or norm_member.startswith("tokens/"):
                            dest = f"tokens/{user_id}.pickle"
                            await makedirs("tokens", exist_ok=True)
                            with open(dest, "wb") as f:
                                f.write(data_bytes)
                            update_user_ldata(user_id, "TOKEN_PICKLE", dest)
                            await database.update_user_doc(user_id, "TOKEN_PICKLE", dest)
                        elif norm_member == "cookies.txt" or norm_member.startswith("cookies/"):
                            dest = f"cookies/{user_id}/cookies.txt"
                            await makedirs(f"cookies/{user_id}", exist_ok=True)
                            with open(dest, "wb") as f:
                                f.write(data_bytes)
                            update_user_ldata(user_id, "USER_COOKIE_FILE", dest)
                            await database.update_user_doc(user_id, "USER_COOKIE_FILE", dest)

                await database.update_user_data(user_id)
                await send_message(msg, "<b>Settings imported successfully!</b>")
            except Exception as e:
                await send_message(msg, f"Failed to import settings: {e}")
            finally:
                if os.path.exists(temp_zip):
                    os.remove(temp_zip)
                await delete_message(msg)
                await update_user_settings(query, stype="main")

        rfunc = partial(update_user_settings, query, stype="main")
        await event_handler(client, query, import_file_handler, rfunc, document=True)
    elif data[2] == "setfont":
        await query.answer()
        tag = data[3]
        if tag == "none":
            user_dict.pop("LEECH_FONT", None)
        else:
            user_dict["LEECH_FONT"] = tag
        await update_user_settings(query, stype="leech")
        if Config.DATABASE_URL:
            await database.update_user_data(user_id)
    elif data[2] == "set_merge_mode":
        await query.answer()
        update_user_ldata(user_id, "AUTO_MERGE_MODE", data[3])
        await update_user_settings(query, stype="vtools")
        await database.update_user_data(user_id)
    elif data[2] == "split_mode":
        await query.answer()
        update_user_ldata(user_id, "SPLIT_MODE", data[3])
        await update_user_settings(query, stype="leech")
        await database.update_user_data(user_id)
    elif data[2] == "name_source":
        await query.answer()
        update_user_ldata(user_id, "NAME_SOURCE", data[3])
        await update_user_settings(query, stype="advanced")
        await database.update_user_data(user_id)
    elif data[2] == "range_mode":
        await query.answer()
        update_user_ldata(user_id, "RANGE_LINK_MODE", data[3])
        await update_user_settings(query, stype="advanced")
        await database.update_user_data(user_id)
    elif data[2] in ["gd", "rc"]:
        await query.answer()
        du = "rc" if data[2] == "gd" else "gd"
        update_user_ldata(user_id, "DEFAULT_UPLOAD", du)
        await update_user_settings(query, stype="general")
        await database.update_user_data(user_id)
    elif data[2] == "back":
        await query.answer()
        stype = data[3] if len(data) == 4 else "main"
        await update_user_settings(query, stype)
    else:
        await query.answer()
        await delete_message(message, message.reply_to_message)


@new_task
async def get_users_settings(_, message):
    msg = ""
    if auth_chats:
        msg += f"AUTHORIZED_CHATS: {auth_chats}\n"
    if sudo_users:
        msg += f"SUDO_USERS: {sudo_users}\n\n"
    if user_data:
        for u, d in user_data.items():
            try:
                user_obj = await TgClient.bot.get_users(u)
                user_info = f"{user_obj.mention(style='html')} (<code>{u}</code>)"
            except Exception:
                user_info = f"User <code>{u}</code>"
            kmsg = f"\n<b>{user_info}:</b>\n"
            if vmsg := "".join(
                f"• {k}: <code>{v or None}</code>\n" for k, v in d.items()
            ):
                msg += kmsg + vmsg
        if not msg:
            await send_message(message, "No user settings data found!")
            return
        msg_ecd = msg.encode()
        if len(msg_ecd) > 4000:
            with BytesIO(msg_ecd) as ofile:
                ofile.name = "users_settings.txt"
                await send_file(message, ofile)
        else:
            await send_message(message, msg)
    else:
        await send_message(message, "No user settings data found!")
