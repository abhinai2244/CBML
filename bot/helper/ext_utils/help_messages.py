# ruff: noqa: F403, F405
mirror = """<b>Send a link along with command options:</b>

<code>/cmd link</code>

<b>Or reply to a link/file:</b>

<code>/cmd -n "New Name" -e -up "Upload Destination"</code>

<blockquote><b>Note:</b> Commands starting with <b>qb</b> are ONLY for torrent tasks.</blockquote>"""

clone = """<b>Clone Google Drive or Rclone path:</b>

Send link or path along with command or reply to it.
Example: <code>/cmd rcl/rclone_path -up rcl/rclone_path/rc -sync</code>

<blockquote>Use <b>-sync</b> flag to perform rclone sync method.</blockquote>"""

new_name = """<b>Rename Task File:</b> -n

<code>/cmd link -n New Name</code>

<blockquote>Note: Does not work directly with multi-file torrents without selector.</blockquote>"""

multi_link = """<b>Process Multiple Links:</b> -i

Reply to the first link or file with:
<code>/cmd -i 10</code> (number of links to process)"""

same_dir = """<b>Move Files into Single Folder:</b> -m

Combine contents of multiple links or files into one output folder.

<code>/cmd link -m FolderName</code>
<code>/cmd -i 10 -m FolderName</code>

<blockquote>Example for bulk list:
link1 -m Folder1
link2 -m Folder1
link3 -m Folder2
link4</blockquote>"""

thumb = """<b>Custom Thumbnail:</b> -t

<code>/cmd link -t image-url</code> or reply to Telegram photo/doc

<blockquote>Supports direct image URLs (JPG, PNG, WEBP) and Telegram photo links. Pass <b>none</b> to disable thumbnail.</blockquote>"""

split_size = """<b>Split Size Limit:</b> -sp

<code>/cmd link -sp 500mb</code> or <code>/cmd link -sp 2gb</code>

<blockquote>Supports MB, GB, or exact byte size without unit.</blockquote>"""

upload = """<b>Upload Destination:</b> -up

<code>/cmd link -up rcl/gdl</code>

<blockquote><b>Examples:</b>
• Remote path: <code>-up remote:dir/subdir</code>
• Drive ID: <code>-up Gdrive_id</code>
• Telegram Chat: <code>-up id/@username</code> or <code>-up id/@username|topic_id</code>

Use <b>mrcc:</b> for user rclone config or <b>mtp:</b> for user gdrive token.</blockquote>"""

user_download = """<b>User Account Download:</b>

<code>/cmd tp:link</code> (Owner token)
<code>/cmd sa:link</code> (Service account)
<code>/cmd mtp:gdrive_id</code> (User token)
<code>/cmd mrcc:remote:path</code> (User rclone)"""

rcf = """<b>Custom Rclone Flags:</b> -rcf

<code>/cmd link -up path -rcf --buffer-size:8M|--drive-starred-only</code>

<blockquote>Overrides default flags except --exclude. Check <a href='https://rclone.org/flags/'>Rclone Flags Documentation</a>.</blockquote>"""

bulk = """<b>Bulk Download Task:</b> -b

Reply to a message or text file with links separated by new line:
<code>/cmd -b</code>
<code>/cmd -b start:end</code>

<blockquote>Use start:end range to process specific links from bulk file. Default starts from 0 to end.</blockquote>"""

rclone_dl = """<b>Rclone Download:</b>

<code>/cmd main:dump/ubuntu.iso</code> or <code>rcl</code> to open selection buttons.

<blockquote>Add <b>mrcc:</b> before path to use your personal rclone configuration.</blockquote>"""

extract_zip = """<b>Extract / Zip Archive:</b> -e -z

<code>/cmd link -e password</code> (Extract archive)
<code>/cmd link -z password</code> (Zip content)
<code>/cmd link -z password -e</code> (Extract first then zip)"""

join = """<b>Join Split Files:</b> -j

<code>/cmd -i 3 -j -m FolderName</code>
<code>/cmd link -j</code>

<blockquote>Merges split files (.001, .002, etc.) prior to archiving or upload.</blockquote>"""

tg_links = """<b>Telegram File Links:</b>

<code>https://t.me/channel_name/100</code> (Public)
<code>tg://openmessage?user_id=123&message_id=456</code> (Private)
<code>https://t.me/c/123456/100-110</code> (Message Range)

<blockquote>Requires USER_SESSION_STRING if accessing private channels or restricted chats.</blockquote>"""

sample_video = """<b>Sample Video Generation:</b> -sv

<code>/cmd link -sv</code> (Default 60s sample, 4s clips)
<code>/cmd link -sv 70:5</code> (70s sample, 5s clips)"""

screenshot = """<b>Video Screenshots:</b> -ss

<code>/cmd link -ss</code> (Default 10 frame captures)
<code>/cmd link -ss 6</code> (Generate 6 screenshots)"""

seed = """<b>BitTorrent Seeding:</b> -d

<code>/cmd link -d ratio:time</code>

<blockquote>Example: <code>-d 0.7:10</code> (Seed ratio 0.7 or 10 minutes seeding time).</blockquote>"""

zip_arg = """<b>Zip Compression:</b> -z

<code>/cmd link -z</code> (Create zip)
<code>/cmd link -z password</code> (Password protected zip)"""

qual = """<b>Quality Selector:</b> -s

<code>/cmd link -s</code>

<blockquote>Opens interactive resolution and format selection menu.</blockquote>"""

yt_opt = """<b>Custom yt-dlp Options:</b> -opt

<code>/cmd link -opt {"format": "bv*+ba/b", "writesubtitles": True}</code>

<blockquote>Pass key-value dictionary parameters accepted by yt-dlp Python API.</blockquote>"""

convert_media = """<b>Convert Audio/Video Format:</b> -ca -cv

<code>/cmd link -ca mp3 -cv mp4</code>
<code>/cmd link -ca mp3 + flac ogg</code> (Convert only FLAC/OGG)
<code>/cmd link -cv mkv - webm flv</code> (Convert all except WEBM/FLV)"""

force_start = """<b>Force Start Queued Task:</b> -f -fd -fu

<code>/cmd link -f</code> (Force start download & upload)
<code>/cmd link -fd</code> (Force download only)
<code>/cmd link -fu</code> (Force upload directly after download)"""

gdrive = """<b>Google Drive Tasks:</b>

<code>/cmd gdriveLink -up gdl</code>
<code>/cmd tp:gdriveLink</code> (Force token.pickle)
<code>/cmd sa:gdriveLink</code> (Force service account)
<code>/cmd mtp:gdriveLink</code> (User token.pickle)"""

rclone_cl = """<b>Rclone Tasks:</b>

<code>/cmd rcl/path -up rcl/dest_path -rcf key:val</code>
<code>/cmd mrcc:path -up rc</code> (User rclone config)"""

name_swap = r"""<b>Name Substitution:</b> -ns

<code>/cmd link -ns word1/word2/s | filter/replacement</code>

<blockquote>Replaces words or patterns in filenames prior to upload.
Format: <code>old/new/s</code> (Add <b>s</b> for case sensitive). Escape special characters using backslash.</blockquote>"""

transmission = """<b>Telegram Transmission Mode:</b> -hl -ut -bt

<code>/cmd link -hl</code> (Hybrid mode: User for >2GB, Bot for ≤2GB)
<code>/cmd link -bt</code> (Bot account only)
<code>/cmd link -ut</code> (User account string session only)"""

thumbnail_layout = """<b>Thumbnail Grid Layout:</b> -tl

<code>/cmd link -tl 3x3</code> (Generates 3x3 grid thumbnail image)"""

leech_as = """<b>Leech File Type:</b> -doc -med

<code>/cmd link -doc</code> (Upload as document)
<code>/cmd link -med</code> (Upload as streamable video/audio media)"""

ffmpeg_cmds = """<b>FFmpeg Post-Processing:</b> -ff

<code>/cmd link -ff ["-i mltb.mkv -c copy -c:s srt mltb.mkv", "-del"]</code>

<blockquote><b>Dynamic Placeholders:</b>
• <code>mltb.mkv</code> - Applies to MKV files
• <code>mltb.video</code> - Applies to video streams
• <code>mltb.audio</code> - Applies to audio streams
Add <code>-del</code> inside command array to delete original files upon completion.</blockquote>"""

alldebrid_arg = """<b>AllDebrid Downloader:</b> -ad

<code>/cmd link -ad</code>

<blockquote>Unlocks direct links and magnet files via AllDebrid API for high-speed server downloads.
Requires <b>ALLDEBRID_API_KEY</b> configured.</blockquote>"""

seedr_arg = """<b>Seedr Cloud Downloader:</b> -seedr

<code>/cmd magnet -seedr</code>

<blockquote>Sends torrents to Seedr.cc cloud storage and downloads completed files via fast HTTP stream.
Requires <b>SEEDR_EMAIL</b> and <b>SEEDR_PASSWORD</b>.</blockquote>"""

metadata = """<b>Media Metadata Tagging:</b> -meta

Apply custom title, artist, audio and subtitle language tags.

<code>/cmd link -meta key1=value1|key2=value2</code>

<blockquote><b>Dynamic Placeholders:</b>
• <code>{filename}</code> - Full file name
• <code>{basename}</code> - File name without extension
• <code>{extension}</code> - Extension type
• <code>{audiolang}</code> - Detected audio language
• <code>{sublang}</code> - Detected subtitle language
• <code>{year}</code> - Detected release year

<b>Example:</b>
<code>/mirror link -meta title=Movie|artist={audiolang} Edition</code></blockquote>"""

track_manager_help = """<b>Audio & Subtitle Track Manager:</b> -tm

<code>/cmd link -tm</code>
<code>/cmd link -tr</code>
<code>/cmd link -track</code>

<blockquote>Opens an interactive visual menu to reorder (arrange) audio tracks and select or remove unwanted audio/subtitle streams before uploading.
• Supports individual file track editing or batch <b>Apply to All</b>.</blockquote>"""

MIRROR_HELP_DICT = {
    "main": mirror,
    "New-Name": new_name,
    "DL-Auth": "<b>Direct Link Authorization:</b> -au -ap\n\n<code>/cmd link -au username -ap password</code>",
    "Headers": "<b>Custom HTTP Headers:</b> -h\n\n<code>/cmd link -h key1: value1 key2: value2</code>",
    "Extract/Zip": extract_zip,
    "Select-Files": "<b>File Selection:</b> -s\n\n<code>/cmd link -s</code> or reply to torrent/NZB link",
    "Torrent-Seed": seed,
    "Multi-Link": multi_link,
    "Same-Directory": same_dir,
    "Thumb": thumb,
    "Split-Size": split_size,
    "Upload-Destination": upload,
    "Rclone-Flags": rcf,
    "Bulk": bulk,
    "Join": join,
    "Rclone-DL": rclone_dl,
    "Tg-Links": tg_links,
    "Sample-Video": sample_video,
    "Screenshot": screenshot,
    "Convert-Media": convert_media,
    "Force-Start": force_start,
    "User-Download": user_download,
    "Name-Swap": name_swap,
    "TG-Transmission": transmission,
    "Thumb-Layout": thumbnail_layout,
    "Leech-Type": leech_as,
    "FFmpeg-Cmds": ffmpeg_cmds,
    "Track-Manager": track_manager_help,
    "Metadata": metadata,
    "AllDebrid": alldebrid_arg,
    "Seedr": seedr_arg,
}

CLONE_HELP_DICT = {
    "main": clone,
    "Multi-Link": multi_link,
    "Bulk": bulk,
    "Gdrive": gdrive,
    "Rclone": rclone_cl,
}

RSS_HELP_MESSAGE = """
<b>Add RSS Feed Subscriptions:</b>

Title1 link (required)
Title2 link -c cmd -inf xx -exf xx
Title3 link -c cmd -d ratio:time -z password

<blockquote><b>Filter Options:</b>
• <b>-inf</b> Included words filter
• <b>-exf</b> Excluded words filter
• <b>-stv true/false</b> Case sensitive matching

<b>Example:</b>
<code>Title https://example.com/rss -inf 1080 or 720|mkv or mp4 -exf sample</code>
Parses items containing (1080 or 720) AND (mkv or mp4) without "sample".</blockquote>
"""

PASSWORD_ERROR_MESSAGE = """
<blockquote><b>This link requires a password!</b>
Insert <b>::</b> after the link followed by the password.

<b>Example:</b> <code>https://link.com::mypassword</code></blockquote>
"""


def get_bot_commands():
    from ...core.plugin_manager import get_plugin_manager

    static_commands = {
        "Mirror": "[link/file] Mirror task to cloud destination",
        "QbMirror": "[magnet/torrent] Mirror using qBittorrent",
        "Ytdl": "[link] Mirror YouTube and supported websites",
        "Socialdl": "[link] Download social-media and other yt-dlp supported media",
        "CookieSettings": "Manage per-platform social-media cookies",
        "UpHoster": "[link/file] Upload to DDL hosters",
        "Leech": "[link/file] Leech task to Telegram",
        "QbLeech": "[magnet/torrent] Leech using qBittorrent",
        "YtdlLeech": "[link] Leech YouTube and supported websites",
        "Clone": "[link] Copy files/folders to Google Drive or Rclone",
        "UserSet": "Manage personal user settings",
        "ForceStart": "[gid/reply] Force start queued task",
        "Count": "[link] Count items in Google Drive link",
        "List": "[query] Search files in Google Drive",
        "Search": "[query] Search torrents via qBittorrent plugins",
        "Select": "[gid/reply] Select files from Torrent or NZB",
        "Ping": "Check bot response latency",
        "Status": "[id/me] View active tasks status",
        "Stats": "Display system and bot performance statistics",
        "Rss": "Manage RSS subscriptions",
        "CancelAll": "Cancel active tasks",
        "Help": "Show detailed usage help",
        "BotSet": "[SUDO] Manage global bot settings",
        "Log": "[SUDO] Get bot execution log",
        "Memory": "[SUDO] Check memory allocation and usage",
        "Restart": "[SUDO] Reboot bot process",
        "RestartSessions": "[SUDO] Reboot user sessions",
    }

    commands = static_commands.copy()

    plugin_manager = get_plugin_manager()
    if plugin_manager:
        for plugin_info in plugin_manager.list_plugins():
            if plugin_info.enabled and plugin_info.commands:
                for cmd in plugin_info.commands:
                    key = cmd.capitalize()
                    if key not in commands:
                        commands[key] = (
                            plugin_info.description or f"Plugin command: {cmd}"
                        )

    return commands


BOT_COMMANDS = get_bot_commands()


def get_help_string():
    from ..telegram_helper.bot_commands import BotCommands

    help_lines = [
        "<blockquote><b>Tip:</b> Run any command without arguments to view specific parameters and options.</blockquote>\n"
    ]

    commands = BotCommands.get_commands()

    for key, cmds in commands.items():
        cmd_attr = getattr(BotCommands, f"{key}Command", None)
        if not cmd_attr:
            continue

        if isinstance(cmd_attr, list):
            cmd_str = f"/{' or /'.join(cmd_attr)}"
        else:
            cmd_str = f"/{cmd_attr}"

        if key == "Mirror":
            help_lines.append(f"<b>{cmd_str}</b>: Mirror task to cloud storage.")
        elif key == "QbMirror":
            help_lines.append(f"<b>{cmd_str}</b>: Mirror torrent via qBittorrent.")
        elif key == "JdMirror":
            help_lines.append(f"<b>{cmd_str}</b>: Mirror link via JDownloader.")
        elif key == "NzbMirror":
            help_lines.append(f"<b>{cmd_str}</b>: Mirror NZB via SABnzbd.")
        elif key == "Ytdl":
            help_lines.append(f"<b>{cmd_str}</b>: Mirror link via yt-dlp.")
        elif key == "Socialdl":
            help_lines.append(f"<b>{cmd_str}</b>: Download social-media media via yt-dlp; supports the full downloader argument/flag set.")
        elif key == "SocialdlTelegram":
            help_lines.append(f"<b>{cmd_str}</b>: Social-media yt-dlp download and upload directly to Telegram; supports the full downloader argument/flag set.")
        elif key == "CookieSettings":
            help_lines.append(f"<b>{cmd_str}</b>: Manage Facebook/Instagram/X/TikTok/Reddit cookie files.")
        elif key == "UpHoster":
            help_lines.append(f"<b>{cmd_str}</b>: Upload to DDL Hoster services.")
        elif key == "Leech":
            help_lines.append(f"<b>{cmd_str}</b>: Leech files to Telegram.")
        elif key == "QbLeech":
            help_lines.append(f"<b>{cmd_str}</b>: Leech torrent via qBittorrent.")
        elif key == "JdLeech":
            help_lines.append(f"<b>{cmd_str}</b>: Leech link via JDownloader.")
        elif key == "NzbLeech":
            help_lines.append(f"<b>{cmd_str}</b>: Leech NZB via SABnzbd.")
        elif key == "SeedrLink":
            help_lines.append(f"<b>{cmd_str}</b>: Get direct Seedr HTTP links.")
        elif key == "YtdlLeech":
            help_lines.append(f"<b>{cmd_str}</b>: Leech link via yt-dlp.")
        elif key == "Clone":
            help_lines.append(
                f"<b>{cmd_str}</b> [drive_url]: Copy files/folders in Google Drive."
            )
        elif key == "Count":
            help_lines.append(
                f"<b>{cmd_str}</b> [drive_url]: Count items in Google Drive folder."
            )
        elif key == "Delete":
            help_lines.append(
                f"<b>{cmd_str}</b> [drive_url]: Delete item from Google Drive (SUDO)."
            )
        elif key == "UserSet":
            help_lines.append(f"<b>{cmd_str}</b>: Open personal user settings menu.")
        elif key == "BotSet":
            help_lines.append(f"<b>{cmd_str}</b>: Open bot settings menu (SUDO).")
        elif key == "Select":
            help_lines.append(
                f"<b>{cmd_str}</b>: Select specific files from torrent or NZB task."
            )
        elif key == "CancelTask":
            help_lines.append(f"<b>{cmd_str}</b> [gid]: Cancel running task by GID.")
        elif key == "ForceStart":
            help_lines.append(f"<b>{cmd_str}</b> [gid]: Force start queued task.")
        elif key == "CancelAll":
            help_lines.append(f"<b>{cmd_str}</b>: Cancel active or queued tasks.")
        elif key == "List":
            help_lines.append(f"<b>{cmd_str}</b> [query]: Search Google Drive files.")
        elif key == "Search":
            help_lines.append(
                f"<b>{cmd_str}</b> [query]: Search torrents via qBittorrent."
            )
        elif key == "Status":
            help_lines.append(f"<b>{cmd_str}</b>: View current tasks status.")
        elif key == "Stats":
            help_lines.append(f"<b>{cmd_str}</b>: View system hardware & bot stats.")
        elif key == "Ping":
            help_lines.append(f"<b>{cmd_str}</b>: Check bot latency and ping response.")
        elif key == "Authorize":
            help_lines.append(
                f"<b>{cmd_str}</b>: Authorize user or chat (SUDO)."
            )
        elif key == "UnAuthorize":
            help_lines.append(
                f"<b>{cmd_str}</b>: Unauthorize user or chat (SUDO)."
            )
        elif key == "Users":
            help_lines.append(f"<b>{cmd_str}</b>: View authorized users (SUDO).")
        elif key == "AddSudo":
            help_lines.append(f"<b>{cmd_str}</b>: Add new sudo user (OWNER).")
        elif key == "RmSudo":
            help_lines.append(f"<b>{cmd_str}</b>: Remove sudo user (OWNER).")
        elif key == "BlackList":
            help_lines.append(f"<b>{cmd_str}</b>: Blacklist user or chat (SUDO).")
        elif key == "RmBlackList":
            help_lines.append(f"<b>{cmd_str}</b>: Unblacklist user or chat (SUDO).")
        elif key == "AddImage":
            help_lines.append(f"<b>{cmd_str}</b>: Add image to wallpaper gallery.")
        elif key == "Images":
            help_lines.append(f"<b>{cmd_str}</b>: View and manage wallpaper gallery.")
        elif key == "Restart":
            help_lines.append(f"<b>{cmd_str}</b>: Restart bot process (SUDO).")
        elif key == "Log":
            help_lines.append(f"<b>{cmd_str}</b>: Download recent bot log (SUDO).")
        elif key == "Shell":
            help_lines.append(f"<b>{cmd_str}</b>: Execute shell command (OWNER).")
        elif key == "AExec":
            help_lines.append(f"<b>{cmd_str}</b>: Execute async Python snippet (OWNER).")
        elif key == "Exec":
            help_lines.append(f"<b>{cmd_str}</b>: Execute Python snippet (OWNER).")
        elif key == "ClearLocals":
            help_lines.append(f"<b>{cmd_str}</b>: Clear execution local variables (OWNER).")
        elif key == "Rss":
            help_lines.append(f"<b>{cmd_str}</b>: Open RSS feed manager.")
        elif key in BOT_COMMANDS:
            help_lines.append(f"<b>{cmd_str}</b>: {BOT_COMMANDS[key]}")

    return "\n".join(help_lines)


yt = """<b>yt-dlp Supported Link Mirroring & Leeching</b>

<code>/yt link</code>
<code>/yl link</code>

<b>Arguments:</b>
• <code>-n new_name</code>: Custom output filename.
• <code>-s</code>: Quality & format selection buttons.
• <code>-opt options</code>: Custom yt-dlp option dict or pipe-separated string.
• <code>-sp split_size</code>: Leech split size.
• <code>-z</code>: Zip output after download.
• <code>-b</code>: Bulk download from links in text file / reply.
• <code>-i count</code>: Multi-part download.
• <code>-up upload_path</code>: Custom upload destination.
• <code>-m folder_name</code>: Folder name for same-directory downloads."""

socialdl_help = """<b>Social Media Downloader</b>\n\n<code>/sdl link</code> or <code>/socialdl link</code>\n• Uses the existing yt-dlp engine and quality/format selector.\n• Platform cookies can be configured with <code>/cookiesettings</code>.\n• Supports the existing command suffix and downloader arguments."""

yt_opt = """<b>yt-dlp Options Format:</b>

<b>String Format:</b>
<code>-opt format:bv*+ba/b|check_certificate:False</code>

<b>Dict Format:</b>
<code>-opt {'format': 'bv*+ba/b', 'check_certificate': False}</code>"""

YT_HELP_DICT = {
    "main": yt,
    "New-Name": f"{new_name}\nNote: Don't add file extension",
    "Zip": zip_arg,
    "Quality": qual,
    "Options": yt_opt,
    "Multi-Link": multi_link,
    "Same-Directory": same_dir,
    "Thumb": thumb,
    "Split-Size": split_size,
    "Upload-Destination": upload,
}


help_string = get_help_string()
