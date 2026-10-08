from html import escape
from logging import getLogger
from os import path as ospath, listdir
from re import search as re_search
from contextlib import suppress
from shutil import which
from secrets import token_hex
from yt_dlp import YoutubeDL, DownloadError

from .... import task_dict_lock, task_dict
from ....core.config_manager import BinConfig
from ...ext_utils.bot_utils import sync_to_async, async_to_sync
from ...ext_utils.task_manager import (
    check_running_tasks,
    stop_duplicate_check,
    limit_checker,
)
from ...mirror_leech_utils.status_utils.queue_status import QueueStatus
from ...ext_utils.cookie_utils import (
    describe_cookie_report,
    ensure_cookie_file,
    get_social_cookie_file,
)
from ...telegram_helper.message_utils import send_message, send_status_message
from ..status_utils.yt_dlp_status import YtDlpStatus

LOGGER = getLogger(__name__)


# Workaround for YouTube "The page needs to be reloaded" (yt-dlp issues
# #17389 / #17405): the `tv_downgraded` client returns UNPLAYABLE, mostly when
# cookies are used. Exclude it. A user's own `extractor_args` (-opt or
# YT_DLP_OPTIONS) is applied later and overrides this default.
YT_EXTRACTOR_ARGS = {
    "youtube": {
        "player_client": ["default", "web_safari", "web_embedded", "-tv_downgraded"]
    }
}
# Formats are dropped (-> "Requested format is not available") when YouTube's
# JS challenge can't be solved. Allow both runtimes the Dockerfile installs and
# let yt-dlp fetch a matching solver script if the pip yt-dlp-ejs is out of sync.
def get_yt_js_options():
    """Use only supported runtimes actually present on the VPS."""
    runtimes = {}
    deno = which("deno")
    if deno:
        runtimes["deno"] = {"path": deno}
    node = which("node")
    if node:
        try:
            import subprocess
            version = subprocess.run(
                [node, "--version"], capture_output=True, text=True, timeout=3
            ).stdout.strip().lstrip("v")
            major = int(version.split(".", 1)[0])
            if major >= 20:
                runtimes["node"] = {"path": node}
            else:
                LOGGER.warning(
                    f"Ignoring unsupported Node.js {version}; yt-dlp requires a newer JS runtime."
                )
        except Exception:
            pass
    if not runtimes:
        LOGGER.warning(
            "No supported YouTube JavaScript runtime found. Install Deno or a supported Node.js."
        )
    return {
        "js_runtimes": runtimes,
        "remote_components": ["ejs:github"],
    }


YT_JS_OPTS = get_yt_js_options()


YT_LINK_RE = r"(?:youtube\.com|youtu\.be|youtube-nocookie\.com)"

# Tried in order until one returns REAL (non-storyboard) formats.
YT_ATTEMPTS = (
    ("default clients + cookies", YT_EXTRACTOR_ARGS, True),
    ("default clients, no cookies", YT_EXTRACTOR_ARGS, False),
    ("android_vr client, no cookies", {"youtube": {"player_client": ["android_vr"]}}, False),
)

_KEY_LINE = (
    r"warning|error|challenge|js runtime|jsc|sabr|po token|cookies|sign in|"
    r"nsig|n function|no longer valid|skipped|not available|unavailable|bot|"
    r"formats? (?:may|have)|player response|drm"
)


def is_youtube_link(link):
    return bool(re_search(YT_LINK_RE, str(link), 2))  # 2 == re.IGNORECASE


class YtProbeError(Exception):
    """Raised when YouTube returned no downloadable formats; str() is user-facing."""


class ProbeLogger:
    """Captures everything yt-dlp says so the REAL cause can be logged/shown."""

    def __init__(self):
        self.lines = []

    def debug(self, msg):
        self.lines.append(str(msg))

    info = debug

    def warning(self, msg):
        self.lines.append(f"WARNING: {msg}")

    def error(self, msg):
        self.lines.append(f"ERROR: {msg}")


def real_formats(info):
    return [
        f
        for f in (info.get("formats") or [])
        if f.get("ext") != "mhtml"
        and f.get("protocol") != "mhtml"
        and f.get("format_note") != "storyboard"
        and (f.get("vcodec") != "none" or f.get("acodec") != "none")
    ]


def probe_youtube(link, options):
    """Extract info trying several client/cookie setups. Returns (info, cfg, lines)."""
    tried, collected = [], []
    for label, eargs, use_cookies in YT_ATTEMPTS:
        if not use_cookies and not options.get("cookiefile") and tried:
            if eargs is YT_EXTRACTOR_ARGS:
                continue  # identical to attempt 1 when no cookies are in use
        opts = {k: v for k, v in options.items() if k != "format"}
        opts["extractor_args"] = eargs
        if not use_cookies:
            opts.pop("cookiefile", None)
        plog = ProbeLogger()
        opts.update(
            logger=plog, verbose=True, ignore_no_formats_error=True, quiet=False
        )
        outcome = ""
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(link, download=False)
            if info is None:
                outcome = "no info returned"
            elif info.get("entries") is not None or real_formats(info):
                LOGGER.info(f"YouTube probe OK using: {label}")
                return info, {"extractor_args": eargs, "use_cookies": use_cookies}, plog.lines
            else:
                n = len(info.get("formats") or [])
                outcome = f"only {n} non-downloadable format(s) (storyboards)"
        except Exception as e:
            outcome = f"exception: {e}"
        tried.append(f"{label} -> {outcome}")
        collected.extend(f"[{label}] {line}" for line in plog.lines)
        LOGGER.error(f"YouTube probe failed ({label}): {outcome}")

    # Full yt-dlp output goes to the bot log, the relevant lines go to the user.
    for line in collected:
        LOGGER.error(f"yt-dlp: {line}")
    key, seen = [], set()
    for line in collected:
        clean = line.split("] ", 1)[-1] if line.startswith("[") else line
        if re_search(_KEY_LINE, clean, 2) and clean not in seen:
            seen.add(clean)
            key.append(clean[:260])
    msg = "ERROR: [youtube] Requested format is not available (YouTube returned no downloadable streams)\n\nTried:\n"
    msg += "\n".join(f"• {t}" for t in tried)
    msg += "\n\nWhat yt-dlp reported:\n" + (
        "\n".join(f"• {k}" for k in key[:12]) or "• (nothing relevant captured, see bot log)"
    )
    if options.get("cookiefile"):
        msg += f"\n\nCookie file: {describe_cookie_report(ensure_cookie_file(options['cookiefile']))}"
    msg += (
        "\n\nUsual causes: cookies expired/rotated (re-export from a private window), "
        "JS runtime/solver not working (deno/node + matching yt-dlp-ejs), or YouTube forcing "
        "SABR for this server IP (try another IP/proxy)."
    )
    raise YtProbeError(msg)


def get_cookie_file(user_dict=None):
    user_dict = user_dict or {}
    if not user_dict.get("USE_DEFAULT_COOKIE", False):
        usr_cookie = user_dict.get("USER_COOKIE_FILE", "")
        if usr_cookie and ospath.exists(usr_cookie):
            ensure_cookie_file(usr_cookie)
            return usr_cookie
    if ospath.exists("cookies.txt"):
        ensure_cookie_file("cookies.txt")
        return "cookies.txt"
    return None


class MyLogger:
    def __init__(self, obj, listener):
        self._obj = obj
        self._listener = listener

    def debug(self, msg):
        if re_search(_KEY_LINE, str(msg), 2):
            LOGGER.info(f"yt-dlp: {msg}")
        # Hack to fix changing extension
        if not self._obj.is_playlist:
            if match := re_search(
                r".Merger..Merging formats into..(.*?).$", msg
            ) or re_search(r".ExtractAudio..Destination..(.*?)$", msg):
                LOGGER.info(msg)
                newname = match.group(1)
                newname = newname.rsplit("/", 1)[-1]
                self._listener.name = newname

    @staticmethod
    def warning(msg):
        LOGGER.warning(msg)

    @staticmethod
    def error(msg):
        if msg != "ERROR: Cancelling...":
            LOGGER.error(msg)


class YoutubeDLHelper:
    def __init__(self, listener):
        self._last_downloaded = 0
        self._progress = 0
        self._downloaded_bytes = 0
        self._download_speed = 0
        self._eta = "-"
        self._listener = listener
        self._gid = ""
        self._ext = ""
        self.is_playlist = False
        self.keep_thumb = False
        self.playlist_count = 0
        self.opts = {
            "progress_hooks": [self._on_download_progress],
            "logger": MyLogger(self, self._listener),
            "usenetrc": True,
            "allow_multiple_video_streams": True,
            "allow_multiple_audio_streams": True,
            "noprogress": True,
            "allow_playlist_files": True,
            "overwrites": True,
            "writethumbnail": True,
            "trim_file_name": 220,
            "ffmpeg_location": f"/bin/{BinConfig.FFMPEG_NAME}",
            "extractor_args": YT_EXTRACTOR_ARGS,
            **get_yt_js_options(),
            "fragment_retries": 10,
            "retries": 10,
            "retry_sleep_functions": {
                "http": lambda n: 3,
                "fragment": lambda n: 3,
                "file_access": lambda n: 3,
                "extractor": lambda n: 3,
            },
        }
        cookie_to_use = get_cookie_file(self._listener.user_dict)
        yt_cfg = getattr(self._listener, "yt_cfg", None)
        if yt_cfg:
            self.opts["extractor_args"] = yt_cfg["extractor_args"]
            if not yt_cfg["use_cookies"]:
                cookie_to_use = None
        if cookie_to_use:
            self.opts["cookiefile"] = cookie_to_use
            LOGGER.info(
                f"Using cookies.txt file: {cookie_to_use} | User ID : {self._listener.user_id}"
            )

        # Optional per-platform login method. yt-dlp supports username/password
        # for extractors that expose native login; unsupported sites will fall
        # back to their normal authentication flow rather than being bypassed.
        try:
            from ...ext_utils.cookie_utils import get_social_platform
            from .... import user_data
            platform = get_social_platform(getattr(self._listener, "link", ""))
            methods = self._listener.user_dict.get("SOCIAL_AUTH_METHODS", {}) or {}
            creds = self._listener.user_dict.get("SOCIAL_LOGIN", {}) or {}
            if platform and methods.get(platform) == "login" and creds.get(platform):
                self.opts["username"] = creds[platform].get("username", "")
                self.opts["password"] = creds[platform].get("password", "")
                LOGGER.info(f"Using configured login method for {platform} | User ID: {self._listener.user_id}")
        except Exception as e:
            LOGGER.debug(f"Login-method setup skipped: {e}")

    @property
    def download_speed(self):
        return self._download_speed

    @property
    def downloaded_bytes(self):
        return self._downloaded_bytes

    @property
    def size(self):
        return self._listener.size

    @property
    def progress(self):
        return self._progress

    @property
    def eta(self):
        return self._eta

    def _on_download_progress(self, d):
        if self._listener.is_cancelled:
            raise ValueError("Cancelling...")
        if d["status"] == "finished":
            if self.is_playlist:
                self._last_downloaded = 0
        elif d["status"] == "downloading":
            self._download_speed = d["speed"] or 0
            if self.is_playlist:
                downloadedBytes = d["downloaded_bytes"] or 0
                chunk_size = downloadedBytes - self._last_downloaded
                self._last_downloaded = downloadedBytes
                self._downloaded_bytes += chunk_size
            else:
                if d.get("total_bytes"):
                    self._listener.size = d["total_bytes"] or 0
                elif d.get("total_bytes_estimate"):
                    self._listener.size = d["total_bytes_estimate"] or 0
                self._downloaded_bytes = d["downloaded_bytes"] or 0
                self._eta = d.get("eta", "-") or "-"
            try:
                self._progress = (self._downloaded_bytes / self._listener.size) * 100
            except ZeroDivisionError:
                pass

    async def _on_download_start(self, from_queue=False):
        async with task_dict_lock:
            task_dict[self._listener.mid] = YtDlpStatus(self._listener, self, self._gid)
        if not from_queue:
            await self._listener.on_download_start()
            if self._listener.multi <= 1 and not self._listener.is_rss:
                await send_status_message(self._listener.message)

    def _on_download_error(self, error):
        self._listener.is_cancelled = True
        async_to_sync(self._listener.on_download_error, error)

    def _send_formats_table(self):
        """Tell the user which formats really exist (like `yt-dlp -F`)."""
        opts = {
            k: v
            for k, v in self.opts.items()
            if k not in ("format", "postprocessors", "progress_hooks", "logger")
        }
        opts.update(
            quiet=True,
            no_warnings=True,
            ignore_no_formats_error=True,
            playlist_items="1",
        )
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self._listener.link, download=False)
                if info and info.get("entries"):
                    info = next((e for e in info["entries"] if e), None)
                table = ydl.render_formats_table(info) if info else None
        except Exception as e:
            LOGGER.error(f"Could not list formats: {e}")
            return
        if not table:
            table = "No downloadable formats were returned by YouTube."
        lines = table.splitlines()
        text, size = [], 0
        for line in lines:
            if size + len(line) > 3300:
                text.append("...")
                break
            text.append(line)
            size += len(line) + 1
        msg = (
            "<b>Requested format is not available.</b> Formats YouTube returned:\n"
            f"<pre>{escape(chr(10).join(text))}</pre>\n"
            "Only storyboard (<code>sb*</code>) rows = YouTube is hiding the real streams: "
            "refresh cookies, update yt-dlp and make sure deno/node works."
        )
        async_to_sync(send_message, self._listener.message, msg)

    def _extract_meta_data(self):
        qual = self.opts.get("format") or "bv*+ba/b"
        candidates = [qual]
        if not qual.startswith("ba/b"):
            candidates.append("bv*+ba/b")
        candidates.append("b")
        candidates = list(dict.fromkeys(candidates))
        for idx, fmt in enumerate(candidates):
            self.opts["format"] = fmt
            last = idx == len(candidates) - 1
            if self._extract_meta_data_once(last) != "retry":
                return
            LOGGER.warning(f"Format '{fmt}' not available, trying '{candidates[idx + 1]}'")

    def _extract_meta_data_once(self, last=True):
        with YoutubeDL(self.opts) as ydl:
            try:
                result = ydl.extract_info(self._listener.link, download=False)
                if result is None:
                    raise ValueError("Info result is None")
            except Exception as e:
                if "Requested format is not available" in str(e):
                    if not last:
                        return "retry"
                    self._send_formats_table()
                return self._on_download_error(str(e))
            if self.is_playlist:
                self.playlist_count = result.get("playlist_count", 0)
            if "entries" in result:
                for entry in result["entries"]:
                    if not entry:
                        continue
                    if entry.get("ext") == "unknown_video":
                        entry["ext"] = "mp4"
                    if "filesize_approx" in entry:
                        self._listener.size += entry.get("filesize_approx", 0) or 0
                    elif "filesize" in entry:
                        self._listener.size += entry.get("filesize", 0) or 0
                    if not self._listener.name:
                        outtmpl_ = "%(series,playlist_title,channel)s%(season_number& |)s%(season_number&S|)s%(season_number|)02d.%(ext)s"
                        self._listener.name, ext = ospath.splitext(
                            ydl.prepare_filename(entry, outtmpl=outtmpl_)
                        )
                        if not self._ext:
                            self._ext = ext
            else:
                if result.get("ext") == "unknown_video":
                    result["ext"] = "mp4"
                if "filesize_approx" in result:
                    self._listener.size = result.get("filesize_approx", 0) or 0
                elif "filesize" in result:
                    self._listener.size = result.get("filesize", 0) or 0
                outtmpl_ = "%(title,fulltitle,alt_title)s%(season_number& |)s%(season_number&S|)s%(season_number|)02d%(episode_number&E|)s%(episode_number|)02d%(height& |)s%(height|)s%(height&p|)s%(fps|)s%(fps&fps|)s%(tbr& |)s%(tbr|)d.%(ext)s"
                realName = ydl.prepare_filename(result, outtmpl=outtmpl_)
                ext = ospath.splitext(realName)[-1]
                self._listener.name = (
                    f"{self._listener.name}{ext}" if self._listener.name else realName
                )
                if not self._ext:
                    self._ext = ext

    def _download(self, path):
        try:
            with YoutubeDL(self.opts) as ydl:
                try:
                    ydl.download([self._listener.link])
                except DownloadError as e:
                    if not self._listener.is_cancelled:
                        self._on_download_error(str(e))
                    return
            if self.is_playlist and (
                not ospath.exists(path) or len(listdir(path)) == 0
            ):
                self._on_download_error(
                    "No video available to download from this playlist. Check logs for more details"
                )
                return
            if self._listener.is_cancelled:
                return
            async_to_sync(self._listener.on_download_complete)
        except Exception as e:
            if not self._listener.is_cancelled:
                self._on_download_error(str(e))
        return

    async def add_download(self, path, qual, playlist, options):
        if playlist:
            self.opts["ignoreerrors"] = True
            self.is_playlist = True

        self._gid = token_hex(5)

        await self._on_download_start()

        self.opts["postprocessors"] = [
            {
                "add_chapters": True,
                "add_infojson": "if_exists",
                "add_metadata": True,
                "key": "FFmpegMetadata",
            }
        ]

        if qual.startswith("ba/b-"):
            audio_info = qual.split("-")
            qual = audio_info[0]
            audio_format = audio_info[1]
            rate = audio_info[2]
            self.opts["postprocessors"].append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": rate,
                }
            )
            if audio_format == "vorbis":
                self._ext = ".ogg"
            elif audio_format == "alac":
                self._ext = ".m4a"
            else:
                self._ext = f".{audio_format}"

        if not self._listener.is_leech or getattr(self._listener, "thumbnail_layout", None):
            self.opts["writethumbnail"] = False

        if options:
            self._set_options(options)

        self.opts["format"] = qual

        await sync_to_async(self._extract_meta_data)
        if self._listener.is_cancelled:
            return

        base_name, ext = ospath.splitext(self._listener.name)
        trim_name = self._listener.name if self.is_playlist else base_name
        if len(trim_name.encode()) > 200:
            self._listener.name = (
                self._listener.name[:200]
                if self.is_playlist
                else f"{base_name[:200]}{ext}"
            )
            base_name = ospath.splitext(self._listener.name)[0]

        start_path = path if self.keep_thumb else f"{path}/yt-dlp-thumb"
        opts_check = options or {}
        if self.is_playlist:
            self.opts["outtmpl"] = {
                "default": f"{path}/{self._listener.name}/%(title,fulltitle,alt_title)s%(season_number& |)s%(season_number&S|)s%(season_number|)02d%(episode_number&E|)s%(episode_number|)02d%(height& |)s%(height|)s%(height&p|)s%(fps|)s%(fps&fps|)s%(tbr& |)s%(tbr|)d.%(ext)s",
                "thumbnail": f"{start_path}/%(title,fulltitle,alt_title)s%(season_number& |)s%(season_number&S|)s%(season_number|)02d%(episode_number&E|)s%(episode_number|)02d%(height& |)s%(height|)s%(height&p|)s%(fps|)s%(fps&fps|)s%(tbr& |)s%(tbr|)d.%(ext)s",
            }
        elif "download_ranges" in opts_check:
            self.opts["outtmpl"] = {
                "default": f"{path}/{base_name}/%(section_number|)s%(section_number&.|)s%(section_title|)s%(section_title&-|)s%(title,fulltitle,alt_title)s %(section_start)s to %(section_end)s.%(ext)s",
                "thumbnail": f"{start_path}/%(section_number|)s%(section_number&.|)s%(section_title|)s%(section_title&-|)s%(title,fulltitle,alt_title)s %(section_start)s to %(section_end)s.%(ext)s",
            }
        elif any(
            key in opts_check
            for key in [
                "writedescription",
                "writeinfojson",
                "writeannotations",
                "writedesktoplink",
                "writewebloclink",
                "writelink",
                "writeurllink",
                "writesubtitles",
                "write_all_thumbnails",
            ]
        ):
            self.opts["outtmpl"] = {
                "default": f"{path}/{base_name}/{self._listener.name}",
                "thumbnail": f"{start_path}/{base_name}.%(ext)s",
            }
        else:
            self.opts["outtmpl"] = {
                "default": f"{path}/{self._listener.name}",
                "thumbnail": f"{start_path}/{base_name}.%(ext)s",
            }

        if qual.startswith("ba/b"):
            self._listener.name = f"{base_name}{self._ext}"

        if self.opts.get("writethumbnail"):
            self.opts["postprocessors"].append(
                {
                    "format": "jpg",
                    "key": "FFmpegThumbnailsConvertor",
                    "when": "before_dl",
                }
            )
            if self._ext in [
                ".mp3",
                ".mkv",
                ".mka",
                ".ogg",
                ".opus",
                ".flac",
                ".m4a",
                ".mp4",
                ".mov",
                ".m4v",
            ]:
                self.opts["postprocessors"].append(
                    {
                        "already_have_thumbnail": True,
                        "key": "EmbedThumbnail",
                    }
                )

        msg, button = await stop_duplicate_check(self._listener)
        if msg:
            await self._listener.on_download_error(msg, button)
            return

        if limit_exceeded := await limit_checker(self._listener, self.playlist_count):
            await self._listener.on_download_error(limit_exceeded, is_limit=True)
            return

        add_to_queue, event = await check_running_tasks(self._listener)
        if add_to_queue:
            LOGGER.info(f"Added to Queue/Download: {self._listener.name}")
            async with task_dict_lock:
                task_dict[self._listener.mid] = QueueStatus(
                    self._listener, self._gid, "dl"
                )
            await event.wait()
            if self._listener.is_cancelled:
                return
            LOGGER.info(f"Start Queued Download from YT_DLP: {self._listener.name}")
            await self._on_download_start(True)

        if not add_to_queue:
            LOGGER.info(f"Download with YT_DLP: {self._listener.name}")

        await sync_to_async(self._download, path)

    async def cancel_task(self):
        self._listener.is_cancelled = True
        LOGGER.info(f"Cancelling Download: {self._listener.name}")
        await self._listener.on_download_error("Stopped by User!")

    def _set_options(self, options):
        if isinstance(options, str):
            yt_opt = options.split("|")
            for ytopt in yt_opt:
                if ":" not in ytopt:
                    continue
                key, value = map(str.strip, ytopt.split(":", 1))
                if value.startswith("^"):
                    if "." in value or value == "^inf":
                        value = float(value.split("^", 1)[1])
                    else:
                        value = int(value.split("^", 1)[1])
                elif value.lower() == "true":
                    value = True
                elif value.lower() == "false":
                    value = False
                elif value.startswith(("{", "[", "(")) and value.endswith(("}", "]", ")")):
                    try:
                        from ast import literal_eval
                        value = literal_eval(value)
                    except Exception:
                        pass
                if key == "writethumbnail" and value is True:
                    self.keep_thumb = True
                self.opts[key] = value
        elif isinstance(options, dict):
            for key, value in options.items():
                if key == "postprocessors":
                    if isinstance(value, list):
                        self.opts[key].extend(tuple(value))
                    elif isinstance(value, dict):
                        self.opts[key].append(value)
                elif key == "download_ranges":
                    if isinstance(value, list):
                        self.opts[key] = lambda info, ytdl: value
                else:
                    if key == "writethumbnail" and value is True:
                        self.keep_thumb = True
                    self.opts[key] = value
