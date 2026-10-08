import re
from ast import literal_eval
from contextlib import suppress
from PIL import Image
from hashlib import md5, sha256
from aiofiles import open as aiopen
from aiofiles.os import remove, path as aiopath, makedirs
import json
from asyncio import (
    create_subprocess_exec,
    gather,
    wait_for,
    sleep,
)
from asyncio.subprocess import PIPE
from os import path as ospath
from re import search as re_search, escape
from time import time
from aioshutil import move, rmtree
from langcodes import Language
from niquests import AsyncSession

from ... import LOGGER, DOWNLOAD_DIR
from ...core.cpu import ffmpeg_layout
from ...core.config_manager import Config, BinConfig
from .bot_utils import cmd_exec, sync_to_async
from .files_utils import get_mime_type, is_archive, is_archive_split
from .status_utils import time_to_seconds


def get_md5_hash(up_path):
    md5_hash = md5()
    with open(up_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)
        return md5_hash.hexdigest()


def _convert_image(src, dst):
    with Image.open(src) as im:
        im = im.convert("RGB")
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        im.thumbnail((320, 320), resample)
        quality = 90
        im.save(dst, "JPEG", quality=quality)
        while ospath.getsize(dst) > 195 * 1024 and quality > 10:
            quality -= 10
            im.save(dst, "JPEG", quality=quality)


def format_tg_thumbnail(src_path, dst_path=None):
    if not src_path or not ospath.exists(src_path):
        return None
    if not dst_path:
        dst_path = f"{src_path}_tg.jpg"

    try:
        with Image.open(src_path) as img:
            img = img.convert("RGB")
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            img.thumbnail((320, 320), resample)

            quality = 90
            img.save(dst_path, "JPEG", quality=quality)

            while ospath.getsize(dst_path) > 195 * 1024 and quality > 10:
                quality -= 10
                img.save(dst_path, "JPEG", quality=quality)

        return dst_path
    except Exception as e:
        LOGGER.warning(f"Failed to format Telegram thumbnail: {e}")
        return src_path


async def create_thumb(msg, _id=""):
    if not _id:
        _id = int(time() * 1000)
        path = f"{DOWNLOAD_DIR}thumbnails"
    else:
        path = "thumbnails"
    await makedirs(path, exist_ok=True)
    output = ospath.join(path, f"{_id}.jpg")

    if isinstance(msg, str):
        if msg.startswith(("http://", "https://")):
            dl = await download_image_thumb(msg)
            if dl and await aiopath.exists(dl):
                await move(dl, output)
                return output
            return ""
        elif await aiopath.exists(msg):
            try:
                await sync_to_async(_convert_image, msg, output)
                return output
            except Exception as e:
                LOGGER.error(f"Failed to convert image path thumb: {e}")
                return ""
        return ""

    try:
        photo_dir = await msg.download()
    except Exception as e:
        LOGGER.error(f"Failed to download photo: {e}")
        return ""

    try:
        await sync_to_async(_convert_image, photo_dir, output)
    except Exception as e:
        LOGGER.error(f"Failed to process thumb: {e}")
        await remove(photo_dir)
        return ""
    await remove(photo_dir)
    return output


async def download_image_thumb(url):
    NON_IMAGE_TYPES = (
        "text/",
        "application/json",
        "application/xml",
        "application/javascript",
        "video/",
        "audio/",
    )
    path = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(path, exist_ok=True)

    try:
        async with AsyncSession() as client:
            try:
                head_resp = await client.head(url, allow_redirects=True)
                ct = head_resp.headers.get("content-type", "")
                if ct and any(ct.startswith(t) for t in NON_IMAGE_TYPES):
                    LOGGER.error(f"Thumb URL is not an image: {ct}")
                    return ""
            except Exception:
                pass

            resp = await client.get(url, allow_redirects=True, timeout=30)
            if resp.status_code != 200:
                LOGGER.error(f"Failed to download thumb URL: HTTP {resp.status_code}")
                return ""

            data = resp.content
    except Exception as e:
        LOGGER.error(f"Error downloading thumb from URL: {e}")
        return ""

    tag = sha256(url.encode()).hexdigest()[:12]
    tmp_path = ospath.join(path, f"{tag}_tmp")
    output = ospath.join(path, f"{tag}.jpg")

    try:
        async with aiopen(tmp_path, "wb") as f:
            await f.write(data)
    except Exception as e:
        LOGGER.error(f"Failed to write thumb temp file: {e}")
        return ""

    try:
        await sync_to_async(_convert_image, tmp_path, output)
    except Exception as e:
        LOGGER.error(f"Failed to process thumb image: {e}")
        with suppress(Exception):
            await remove(tmp_path)
        return ""
    with suppress(Exception):
        await remove(tmp_path)
    return output


async def get_media_info(path, extra_info=False):
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ]
        )
    except Exception as e:
        LOGGER.error(f"Get Media Info: {e}. Mostly File not found! - File: {path}")
        return (0, "", "", "", "") if extra_info else (0, None, None)
    if result[0] and result[2] == 0:
        ffresult = literal_eval(result[0])
        if not isinstance(ffresult, dict):
            LOGGER.error(f"get_media_info: unexpected ffprobe payload: {result}")
            return (0, "", "", "", "") if extra_info else (0, None, None)
        fields = ffresult.get("format")
        if fields is None:
            LOGGER.error(f"get_media_info: {result}")
            return (0, "", "", "", "") if extra_info else (0, None, None)
        duration = round(float(fields.get("duration", 0)))
        if extra_info:
            lang, langr, qual, stitles = "", "", "", ""
            if (streams := ffresult.get("streams")) and streams[0].get(
                "codec_type"
            ) == "video":
                qual = int(streams[0].get("height"))
                qual = f"{480 if qual <= 480 else 540 if qual <= 540 else 720 if qual <= 720 else 1080 if qual <= 1080 else 2160 if qual <= 2160 else 4320 if qual <= 4320 else 8640}p"
                for stream in streams:
                    if stream.get("codec_type") == "audio" and (
                        lc := stream.get("tags", {}).get("language")
                    ):
                        d_name = lc
                        native_name = lc
                        with suppress(Exception):
                            l_obj = Language.get(lc)
                            d_name = l_obj.display_name()
                            native_name = l_obj.autonym()
                        if d_name not in lang:
                            lang += f"{d_name}, "
                        if native_name not in langr:
                            langr += f"{native_name}, "
                    if stream.get("codec_type") == "subtitle" and (
                        st := stream.get("tags", {}).get("language")
                    ):
                        with suppress(Exception):
                            st = Language.get(st).display_name()
                        if st not in stitles:
                            stitles += f"{st}, "
            return duration, qual, lang[:-2], stitles[:-2], langr[:-2]
        tags = fields.get("tags", {})
        artist = tags.get("artist") or tags.get("ARTIST") or tags.get("Artist")
        title = tags.get("title") or tags.get("TITLE") or tags.get("Title")
        return duration, artist, title
    return (0, "", "", "", "") if extra_info else (0, None, None)


async def get_document_type(path):
    is_video, is_audio, is_image = False, False, False
    if (
        is_archive(path)
        or is_archive_split(path)
        or re_search(r".+(\.|_)(rar|7z|zip|bin)(\.0*\d+)?$", path)
    ):
        return is_video, is_audio, is_image
    mime_type = await sync_to_async(get_mime_type, path)
    if mime_type.startswith("image"):
        return False, False, True
    if mime_type.startswith("text"):
        return False, False, False
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                path,
            ]
        )
        if result[1] and mime_type.startswith("video"):
            is_video = True
    except Exception as e:
        LOGGER.error(f"Get Document Type: {e}. Mostly File not found! - File: {path}")
        if mime_type.startswith("audio"):
            return False, True, False
        if not mime_type.startswith("video") and not mime_type.endswith("octet-stream"):
            return is_video, is_audio, is_image
        if mime_type.startswith("video"):
            is_video = True
        return is_video, is_audio, is_image
    if result[0] and result[2] == 0:
        fields = literal_eval(result[0]).get("streams")
        if fields is None:
            LOGGER.error(f"get_document_type: {result}")
            return is_video, is_audio, is_image
        is_video = False
        for stream in fields:
            if stream.get("codec_type") == "video":
                codec_name = stream.get("codec_name", "").lower()
                if codec_name not in {"mjpeg", "png", "bmp"}:
                    is_video = True
            elif stream.get("codec_type") == "audio":
                is_audio = True
    return is_video, is_audio, is_image


async def get_streams(file):
    cmd = [
        "ffprobe",
        "-hide_banner",
        "-loglevel",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        file,
    ]
    process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        LOGGER.error(f"Error getting stream info: {stderr.decode().strip()}")
        return None

    try:
        raw_streams = json.loads(stdout).get("streams", [])
        valid_streams = []
        for st in raw_streams:
            st_type = st.get("codec_type")
            codec_name = st.get("codec_name", "").lower()
            if not codec_name or codec_name in ("none", "unknown", "n/a"):
                continue
            if st_type == "audio":
                channels = int(st.get("channels", 0) or 0)
                if channels <= 0:
                    continue
            valid_streams.append(st)
        return valid_streams
    except Exception as e:
        LOGGER.error(f"Error parsing ffprobe output: {e}")
        return None


async def take_ss(video_file, ss_nb) -> bool:
    cores, threads = ffmpeg_layout()
    duration = (await get_media_info(video_file))[0]
    if duration != 0:
        dirpath, name = video_file.rsplit("/", 1)
        name, _ = ospath.splitext(name)
        dirpath = f"{dirpath}/{name}_mltbss"
        await makedirs(dirpath, exist_ok=True)
        interval = duration // (ss_nb + 1)
        cap_time = interval
        cmds = []
        for i in range(ss_nb):
            output = f"{dirpath}/SS.{name}_{i:02}.png"
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{cap_time}",
                "-i",
                video_file,
                "-q:v",
                "1",
                "-frames:v",
                "1",
                "-threads",
                f"{threads}",
                output,
            ]
            cap_time += interval
            cmds.append(cmd_exec(cmd))
        try:
            resutls = await wait_for(gather(*cmds), timeout=60)
            if resutls[0][2] != 0:
                LOGGER.error(
                    f"Error while creating screenshots from video. Path: {video_file}. stderr: {resutls[0][1]}"
                )
                await rmtree(dirpath, ignore_errors=True)
                return False
        except Exception:
            LOGGER.error(
                f"Error while creating screenshots from video. Path: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
            )
            await rmtree(dirpath, ignore_errors=True)
            return False
        return dirpath
    else:
        LOGGER.error("take_ss: Can't get the duration of video")
        return False


async def get_audio_thumbnail(audio_file):
    cores, threads = ffmpeg_layout()
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        audio_file,
        "-an",
        "-vcodec",
        "copy",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.warning(
                f"Could not extract thumbnail from audio. Name: {audio_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.warning(
            f"Could not extract thumbnail from audio. Name: {audio_file}. Timeout or ffmpeg issue."
        )
        return None
    return output


async def get_video_thumbnail(video_file, duration):
    cores, threads = ffmpeg_layout()
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if duration == 0:
        duration = 3
    duration = duration // 2
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{duration}",
        "-i",
        video_file,
        "-vf",
        "thumbnail,format=yuv420p",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while extracting thumbnail from video. Name: {video_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.error(
            f"Error while extracting thumbnail from video. Name: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    return output


async def get_multiple_frames_thumbnail(video_file, layout, keep_screenshots):
    cores, threads = ffmpeg_layout()
    layout = re.sub(r"(\d+)\D+(\d+)", r"\1x\2", layout)
    ss_nb = layout.split("x")
    if len(ss_nb) != 2 or not ss_nb[0].isdigit() or not ss_nb[1].isdigit():
        LOGGER.error(f"Invalid layout value: {layout}")
        return None
    ss_nb = int(ss_nb[0]) * int(ss_nb[1])
    if ss_nb == 0:
        LOGGER.error(f"Invalid layout value: {layout}")
        return None
    dirpath = await take_ss(video_file, ss_nb)
    if not dirpath:
        return None
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-pattern_type",
        "glob",
        "-i",
        f"{escape(dirpath)}/*.png",
        "-vf",
        f"tile={layout},thumbnail,format=yuv420p",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-f",
        "mjpeg",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while combining thumbnails for video. Name: {video_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.error(
            f"Error while combining thumbnails from video. Name: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    finally:
        if not keep_screenshots:
            await rmtree(dirpath, ignore_errors=True)
    return output


class FFMpeg:
    def __init__(self, listener):
        self._listener = listener
        self._processed_bytes = 0
        self._last_processed_bytes = 0
        self._processed_time = 0
        self._last_processed_time = 0
        self._speed_raw = 0
        self._progress_raw = 0
        self._total_time = 0
        self._eta_raw = 0
        self._time_rate = 0.1
        self._start_time = 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    @property
    def speed_raw(self):
        return self._speed_raw

    @property
    def progress_raw(self):
        return self._progress_raw

    @property
    def eta_raw(self):
        return self._eta_raw

    async def get_streams(self, file):
        return await get_streams(file)

    def clear(self):
        self._start_time = time()
        self._processed_bytes = 0
        self._processed_time = 0
        self._speed_raw = 0
        self._progress_raw = 0
        self._eta_raw = 0
        self._time_rate = 0.1
        self._last_processed_time = 0
        self._last_processed_bytes = 0

    async def _ffmpeg_progress(self):
        while not (
            self._listener.subproc.returncode is not None
            or self._listener.is_cancelled
            or self._listener.subproc.stdout.at_eof()
        ):
            try:
                line = await wait_for(self._listener.subproc.stdout.readline(), 60)
            except Exception:
                break
            line = line.decode().strip()
            if not line:
                break
            if "=" in line:
                key, value = line.split("=", 1)
                if value != "N/A":
                    if key == "total_size":
                        self._processed_bytes = int(value) + self._last_processed_bytes
                        self._speed_raw = self._processed_bytes / (
                            time() - self._start_time
                        )
                    elif key == "speed":
                        self._time_rate = max(0.1, float(value.strip("x")))
                    elif key == "out_time":
                        self._processed_time = (
                            time_to_seconds(value) + self._last_processed_time
                        )
                        try:
                            self._progress_raw = (
                                self._processed_time * 100
                            ) / self._total_time
                            if (
                                hasattr(self._listener, "subsize")
                                and self._listener.subsize
                                and self._progress_raw > 0
                            ):
                                self._processed_bytes = int(
                                    self._listener.subsize * (self._progress_raw / 100)
                                )
                            if (time() - self._start_time) > 0:
                                self._speed_raw = self._processed_bytes / (
                                    time() - self._start_time
                                )
                            else:
                                self._speed_raw = 0
                            self._eta_raw = (
                                self._total_time - self._processed_time
                            ) / self._time_rate
                        except ZeroDivisionError:
                            self._progress_raw = 0
                            self._eta_raw = 0
            await sleep(0.05)

    async def ffmpeg_cmds(self, ffmpeg, f_path):
        self.clear()
        self._total_time = (await get_media_info(f_path))[0]
        base_name, ext = ospath.splitext(f_path)
        dir, base_name = base_name.rsplit("/", 1)
        indices = [
            index
            for index, item in enumerate(ffmpeg)
            if item.startswith("mltb") or item == "mltb"
        ]
        outputs = []
        for index in indices:
            output_file = ffmpeg[index]
            if output_file != "mltb" and output_file.startswith("mltb"):
                bo, oext = ospath.splitext(output_file)
                if oext:
                    if ext == oext:
                        prefix = f"ffmpeg{index}." if bo == "mltb" else ""
                    else:
                        prefix = ""
                    ext = ""
                else:
                    prefix = ""
            else:
                prefix = f"ffmpeg{index}."
            output = f"{dir}/{prefix}{output_file.replace('mltb', base_name)}{ext}"
            outputs.append(output)
            ffmpeg[index] = output
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *ffmpeg, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return outputs
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while running ffmpeg cmd, mostly file requires different/specific arguments. Path: {f_path}"
            )
            for op in outputs:
                if await aiopath.exists(op):
                    await remove(op)
            return False

    async def convert_video(self, video_file, ext, retry=False):
        cores, threads = ffmpeg_layout()
        self.clear()
        self._total_time = (await get_media_info(video_file))[0]
        base_name = ospath.splitext(video_file)[0]
        output = f"{base_name}.{ext}"
        if retry:
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
                "-i",
                video_file,
                "-map",
                "0",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-threads",
                f"{threads}",
                output,
            ]
            if ext == "mp4":
                cmd[17:17] = ["-c:s", "mov_text"]
            elif ext == "mkv":
                cmd[17:17] = ["-c:s", "ass"]
            else:
                cmd[17:17] = ["-c:s", "copy"]
        else:
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
                "-i",
                video_file,
                "-map",
                "0",
                "-c",
                "copy",
                "-threads",
                f"{threads}",
                output,
            ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            if await aiopath.exists(output):
                await remove(output)
            if not retry:
                return await self.convert_video(video_file, ext, True)
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while converting video, mostly file need specific codec. Path: {video_file}"
            )
        return False

    async def convert_audio(self, audio_file, ext):
        cores, threads = ffmpeg_layout()
        self.clear()
        self._total_time = (await get_media_info(audio_file))[0]
        base_name = ospath.splitext(audio_file)[0]
        output = f"{base_name}.{ext}"
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
            "-i",
            audio_file,
            "-threads",
            f"{threads}",
            output,
        ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while converting audio, mostly file need specific codec. Path: {audio_file}"
            )
            if await aiopath.exists(output):
                await remove(output)
        return False

    async def sample_video(self, video_file, sample_duration, part_duration):
        cores, threads = ffmpeg_layout()
        self.clear()
        self._total_time = sample_duration
        dir, name = video_file.rsplit("/", 1)
        output_file = f"{dir}/SAMPLE.{name}"
        segments = [(0, part_duration)]
        duration = (await get_media_info(video_file))[0]
        remaining_duration = duration - (part_duration * 2)
        parts = (sample_duration - (part_duration * 2)) // part_duration
        time_interval = remaining_duration // parts
        next_segment = time_interval
        for _ in range(parts):
            segments.append((next_segment, next_segment + part_duration))
            next_segment += time_interval
        segments.append((duration - part_duration, duration))

        filter_complex = ""
        for i, (start, end) in enumerate(segments):
            filter_complex += (
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]; "
            )
            filter_complex += (
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]; "
            )

        for i in range(len(segments)):
            filter_complex += f"[v{i}][a{i}]"

        filter_complex += f"concat=n={len(segments)}:v=1:a=1[vout][aout]"

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
            "-i",
            video_file,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-threads",
            f"{threads}",
            output_file,
        ]

        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == -9:
            self._listener.is_cancelled = True
            return False
        elif code == 0:
            return output_file
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while creating sample video, mostly file is corrupted. Path: {video_file}"
            )
            if await aiopath.exists(output_file):
                await remove(output_file)
            return False

    async def split(self, f_path, file_, parts, split_size):
        cores, threads = ffmpeg_layout()
        self.clear()
        multi_streams = True
        self._total_time = duration = (await get_media_info(f_path))[0]
        base_name, extension = ospath.splitext(file_)
        split_size -= 3000000
        start_time = 0
        i = 1
        split_mode = getattr(self._listener, "split_mode", "part")
        digits = max(2, len(str(parts)))
        while i <= parts or start_time < duration - 4:
            suffix = f"part{i:0{digits}d}" if split_mode == "part" else f"{i:0{digits}d}"
            out_name = f"{base_name}.{suffix}{extension}"
            out_path = ospath.join(ospath.dirname(f_path), out_name)
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
                "-ss",
                str(start_time),
                "-i",
                f_path,
                "-fs",
                str(split_size),
                "-map",
                "0",
                "-map_chapters",
                "-1",
                "-async",
                "1",
                "-strict",
                "-2",
                "-c",
                "copy",
                "-threads",
                f"{threads}",
                out_path,
            ]
            if not multi_streams:
                del cmd[15]
                del cmd[15]
            if self._listener.is_cancelled:
                return False
            self._listener.subproc = await create_subprocess_exec(
                *cmd, stdout=PIPE, stderr=PIPE
            )
            await self._ffmpeg_progress()
            _, stderr = await self._listener.subproc.communicate()
            code = self._listener.subproc.returncode
            if self._listener.is_cancelled:
                return False
            if code == -9:
                self._listener.is_cancelled = True
                return False
            elif code != 0:
                try:
                    stderr = stderr.decode().strip()
                except Exception:
                    stderr = "Unable to decode the error!"
                with suppress(Exception):
                    await remove(out_path)
                if multi_streams:
                    LOGGER.warning(
                        f"{stderr}. Retrying without map, -map 0 not working in all situations. Path: {f_path}"
                    )
                    multi_streams = False
                    continue
                else:
                    LOGGER.warning(
                        f"{stderr}. Unable to split this video, if it's size less than {self._listener.max_split_size} will be uploaded as it is. Path: {f_path}"
                    )
                return False
            out_size = await aiopath.getsize(out_path)
            if out_size > self._listener.max_split_size:
                split_size -= (out_size - self._listener.max_split_size) + 5000000
                LOGGER.warning(
                    f"Part size is {out_size}. Trying again with lower split size!. Path: {f_path}"
                )
                await remove(out_path)
                continue
            lpd = (await get_media_info(out_path))[0]
            if lpd == 0:
                LOGGER.error(
                    f"Something went wrong while splitting, mostly file is corrupted. Path: {f_path}"
                )
                break
            elif duration == lpd:
                LOGGER.warning(
                    f"This file has been split with default stream and audio, so you will only see one part with less size from original one because it doesn't have all streams and audios. This happens mostly with MKV videos. Path: {f_path}"
                )
                break
            elif lpd <= 3:
                await remove(out_path)
                break
            self._last_processed_time += lpd
            self._last_processed_bytes += out_size
            start_time += lpd - 3
            i += 1
        return True

    async def encode_video(self, video_file, quality="", crf="", preset="", codec="", resolution="", fps=""):
        cores, threads = ffmpeg_layout()
        self.clear()
        self._total_time = (await get_media_info(video_file))[0]
        base_name, ext = ospath.splitext(video_file)
        output = f"{base_name}_encoded{ext}"

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
            "-i",
            video_file,
            "-map",
            "0",
        ]

        if codec:
            cmd.extend(["-c:v", codec])
        else:
            cmd.extend(["-c:v", "libx264"])

        cmd.extend(["-c:a", "copy", "-c:s", "copy"])

        if crf:
            cmd.extend(["-crf", str(crf)])
        if preset:
            cmd.extend(["-preset", str(preset)])
        if resolution and "x" in str(resolution):
            cmd.extend(["-s", str(resolution)])
        if fps:
            cmd.extend(["-r", str(fps)])

        cmd.extend(["-threads", f"{threads}", output])

        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode

        if code == 0 and await aiopath.exists(output):
            return output
        if await aiopath.exists(output):
            await remove(output)
        return False

    async def compress_video(self, video_file, quality="", crf="", preset="", audio_bitrate="", audio_codec=""):
        cores, threads = ffmpeg_layout()
        self.clear()
        self._total_time = (await get_media_info(video_file))[0]
        base_name, ext = ospath.splitext(video_file)
        output = f"{base_name}_compressed{ext}"

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
            "-i",
            video_file,
            "-map",
            "0",
            "-c:v",
            "libx264",
        ]

        cmd.extend(["-crf", str(crf) if crf else "28"])
        cmd.extend(["-preset", str(preset) if preset else "faster"])

        if audio_codec:
            cmd.extend(["-c:a", str(audio_codec)])
        else:
            cmd.extend(["-c:a", "aac"])

        if audio_bitrate:
            cmd.extend(["-b:a", str(audio_bitrate)])

        cmd.extend(["-c:s", "copy", "-threads", f"{threads}", output])

        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode

        if code == 0 and await aiopath.exists(output):
            return output
        if await aiopath.exists(output):
            await remove(output)
        return False

    async def apply_watermark(self, video_file, text="", image_path="", position="Top-Left", color="white", size="", image_position="", text_position=""):
        cores, threads = ffmpeg_layout()
        self.clear()
        self._total_time = (await get_media_info(video_file))[0]
        base_name, ext = ospath.splitext(video_file)
        output = f"{base_name}_wm{ext}"

        pos_map_text = {
            "Top-Left": "x=10:y=10",
            "Top-Center": "x=(w-text_w)/2:y=10",
            "Top-Right": "x=w-text_w-10:y=10",
            "Center-Left": "x=10:y=(h-text_h)/2",
            "Center": "x=(w-text_w)/2:y=(h-text_h)/2",
            "Center-Right": "x=w-text_w-10:y=(h-text_h)/2",
            "Bottom-Left": "x=10:y=h-text_h-10",
            "Bottom-Center": "x=(w-text_w)/2:y=h-text_h-10",
            "Bottom-Right": "x=w-text_w-10:y=h-text_h-10",
        }

        pos_map_img = {
            "Top-Left": "10:10",
            "Top-Center": "(main_w-overlay_w)/2:10",
            "Top-Right": "main_w-overlay_w-10:10",
            "Center-Left": "10:(main_h-overlay_h)/2",
            "Center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
            "Center-Right": "main_w-overlay_w-10:(main_h-overlay_h)/2",
            "Bottom-Left": "10:main_h-overlay_h-10",
            "Bottom-Center": "(main_w-overlay_w)/2:main_h-overlay_h-10",
            "Bottom-Right": "main_w-overlay_w-10:main_h-overlay_h-10",
        }

        img_pos = image_position or position
        txt_pos = text_position or position

        if image_path and await aiopath.exists(image_path):
            overlay_pos = pos_map_img.get(img_pos, "10:10")
            if size and str(size).strip().isdigit():
                scale_w = int(str(size).strip())
                filter_str = f"[1:v]scale={scale_w}:-1[wm];[0:v][wm]overlay={overlay_pos}[outv]"
            elif size and "x" in str(size).lower():
                scale_dim = str(size).strip().lower().replace("x", ":")
                filter_str = f"[1:v]scale={scale_dim}[wm];[0:v][wm]overlay={overlay_pos}[outv]"
            else:
                filter_str = f"[0:v][1:v]overlay={overlay_pos}[outv]"
            cmd = [
                "taskset", "-c", f"{cores}", BinConfig.FFMPEG_NAME,
                "-hide_banner", "-loglevel", "error", "-progress", "pipe:1",
                "-i", video_file, "-i", image_path,
                "-filter_complex", filter_str,
                "-map", "[outv]", "-map", "0:a?", "-map", "0:s?",
                "-c:v", "libx264", "-c:a", "copy", "-c:s", "copy",
                "-threads", f"{threads}", output
            ]
        elif text:
            escaped_text = text.replace(":", r"\:").replace("'", r"'\''")
            text_pos = pos_map_text.get(txt_pos, "x=10:y=10")
            font_color = color or "white"
            font_size = str(size).strip() if size and str(size).strip().isdigit() else "24"
            vf = f"drawtext=text='{escaped_text}':fontcolor={font_color}:fontsize={font_size}:{text_pos}"
            cmd = [
                "taskset", "-c", f"{cores}", BinConfig.FFMPEG_NAME,
                "-hide_banner", "-loglevel", "error", "-progress", "pipe:1",
                "-i", video_file,
                "-vf", vf,
                "-map", "0", "-c:v", "libx264", "-c:a", "copy", "-c:s", "copy",
                "-threads", f"{threads}", output
            ]
        else:
            return video_file

        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode

        if code == 0 and await aiopath.exists(output):
            return output
        if await aiopath.exists(output):
            await remove(output)
        return False

    async def merge_tracks(self, video_files, audio_files, sub_files, output_file, gid, a_langs=None, s_langs=None):
        cores, threads = ffmpeg_layout()
        self.clear()
        a_langs = a_langs or []
        s_langs = s_langs or []

        total_dur = 0
        all_inputs = video_files + audio_files + sub_files
        for f in all_inputs:
            dur = (await get_media_info(f))[0]
            if dur > total_dur:
                total_dur = dur
        self._total_time = total_dur or 1

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
        ]

        list_file_path = None

        if len(video_files) > 1:
            list_file_path = f"{output_file}.txt"
            async with aiopen(list_file_path, "w") as f:
                for vf in video_files:
                    escaped_vf = vf.replace("'", r"'\''")
                    await f.write(f"file '{escaped_vf}'\n")
            cmd.extend(["-f", "concat", "-safe", "0", "-i", list_file_path])
        elif len(video_files) == 1:
            cmd.extend(["-i", video_files[0]])

        for af in audio_files:
            cmd.extend(["-i", af])

        for sf in sub_files:
            cmd.extend(["-i", sf])

        total_streams_num = (1 if len(video_files) > 1 else len(video_files)) + len(audio_files) + len(sub_files)

        if len(video_files) > 0:
            cmd.extend(["-map", "0:v?", "-map", "0:a?", "-map", "0:s?"])
            for idx in range(1, total_streams_num):
                cmd.extend(["-map", f"{idx}:a?", "-map", f"{idx}:s?"])
        else:
            for idx in range(total_streams_num):
                cmd.extend(["-map", f"{idx}"])

        for idx, alang in enumerate(a_langs):
            if alang:
                cmd.extend([f"-metadata:s:a:{idx}", f"language={alang}", f"-metadata:s:a:{idx}", f"title={alang}"])
        for idx, slang in enumerate(s_langs):
            if slang:
                cmd.extend([f"-metadata:s:s:{idx}", f"language={slang}", f"-metadata:s:s:{idx}", f"title={slang}"])

        cmd.extend(["-c", "copy", "-threads", f"{threads}", output_file])

        if self._listener.is_cancelled:
            if list_file_path:
                with suppress(Exception):
                    await remove(list_file_path)
            return False

        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode

        if list_file_path:
            with suppress(Exception):
                await remove(list_file_path)

        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output_file
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            if await aiopath.exists(output_file):
                await remove(output_file)
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while merging tracks. Output: {output_file}"
            )
            return False

    async def merge_videos(self, video_files, output_file, gid):
        return await self.merge_tracks(video_files, [], [], output_file, gid)

    async def remove_streams(self, f_path, selected_indices):
        out_path = f"{f_path}.rm_stream.mkv"
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", f_path]
        for idx in selected_indices:
            cmd.extend(["-map", f"0:{idx}"])
        cmd.extend(["-c", "copy", out_path])
        res, err, code = await cmd_exec(cmd)
        if code == 0 and await aiopath.exists(out_path):
            return out_path
        return None

    async def reorder_tracks(self, f_path, aud_swaps, sub_swaps, aud_select=None, sub_select=None, aud_order=None, sub_order=None):
        streams = await self.get_streams(f_path)
        if not streams:
            return None
        out_path = f"{f_path}.reorder.mkv"
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        sub_streams = [s for s in streams if s.get("codec_type") == "subtitle"]
        video_streams = [s for s in streams if s.get("codec_type") == "video"]

        if aud_order is not None:
            new_aud = []
            for idx in aud_order:
                if 0 <= idx < len(audio_streams):
                    new_aud.append(audio_streams[idx])
            audio_streams = new_aud
        elif aud_select is not None:
            audio_streams = [a for idx, a in enumerate(audio_streams) if idx in aud_select]
        elif aud_swaps:
            for swap in aud_swaps:
                if len(swap) == 2 and isinstance(swap[0], int) and isinstance(swap[1], int):
                    i1, i2 = swap[0] - 1, swap[1] - 1
                    if 0 <= i1 < len(audio_streams) and 0 <= i2 < len(audio_streams):
                        audio_streams[i1], audio_streams[i2] = audio_streams[i2], audio_streams[i1]

        if sub_order is not None:
            new_sub = []
            for idx in sub_order:
                if 0 <= idx < len(sub_streams):
                    new_sub.append(sub_streams[idx])
            sub_streams = new_sub
        elif sub_select is not None:
            sub_streams = [s for idx, s in enumerate(sub_streams) if idx in sub_select]
        elif sub_swaps:
            for swap in sub_swaps:
                if len(swap) == 2 and isinstance(swap[0], int) and isinstance(swap[1], int):
                    i1, i2 = swap[0] - 1, swap[1] - 1
                    if 0 <= i1 < len(sub_streams) and 0 <= i2 < len(sub_streams):
                        sub_streams[i1], sub_streams[i2] = sub_streams[i2], sub_streams[i1]

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", f_path]
        for v in video_streams:
            cmd.extend(["-map", f"0:{v.get('index')}"])
        for a in audio_streams:
            cmd.extend(["-map", f"0:{a.get('index')}"])
        for s in sub_streams:
            cmd.extend(["-map", f"0:{s.get('index')}"])
        cmd.extend(["-c", "copy", out_path])

        res, err, code = await cmd_exec(cmd)
        if code == 0 and await aiopath.exists(out_path):
            await remove(f_path)
            await move(out_path, f_path)
            return f_path
        return None

    async def trim_media(self, f_path, start_time, end_time):
        out_path = f"{f_path}.trim.mkv"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            start_time,
            "-to",
            end_time,
            "-i",
            f_path,
            "-c",
            "copy",
            out_path,
        ]
        res, err, code = await cmd_exec(cmd)
        if code == 0 and await aiopath.exists(out_path):
            await remove(f_path)
            await move(out_path, f_path)
            return f_path
        return None

    async def extract_tracks(self, f_path, extract_types):
        streams = await self.get_streams(f_path)
        if not streams:
            return None
        dir_name = ospath.dirname(f_path)
        base_name = ospath.splitext(ospath.basename(f_path))[0]

        for st in streams:
            st_type = st.get("codec_type")
            st_idx = st.get("index")
            lang = st.get("tags", {}).get("language", "und")

            if st_type == "video" and ("video" in extract_types or "file" in extract_types):
                ext = st.get("codec_name", "mkv")
                out_file = ospath.join(dir_name, f"{base_name}_video_{st_idx}_{lang}.{ext}")
                cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", f_path, "-map", f"0:{st_idx}", "-c", "copy", out_file]
                await cmd_exec(cmd)
            elif st_type == "audio" and "audio" in extract_types:
                ext = st.get("codec_name", "m4a")
                out_file = ospath.join(dir_name, f"{base_name}_audio_{st_idx}_{lang}.{ext}")
                cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", f_path, "-map", f"0:{st_idx}", "-c", "copy", out_file]
                await cmd_exec(cmd)
            elif st_type == "subtitle" and "subtitle" in extract_types:
                ext = "srt" if st.get("codec_name") in ["subrip", "srt"] else "ass"
                out_file = ospath.join(dir_name, f"{base_name}_sub_{st_idx}_{lang}.{ext}")
                cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", f_path, "-map", f"0:{st_idx}", "-c", "copy", out_file]
                await cmd_exec(cmd)

        return f_path


def _calc_wm_position(pos_str: str, bg_w: int, bg_h: int, wm_w: int, wm_h: int, margin: int = 15) -> tuple:
    pos = str(pos_str).strip().lower()

    if pos == "center":
        x = (bg_w - wm_w) // 2
        y = (bg_h - wm_h) // 2
        return max(0, x), max(0, y)

    if "center" in pos and "left" not in pos and "right" not in pos:
        x = (bg_w - wm_w) // 2
    elif "right" in pos:
        x = bg_w - wm_w - margin
    else:
        x = margin

    if "center" in pos and "top" not in pos and "bottom" not in pos:
        y = (bg_h - wm_h) // 2
    elif "bottom" in pos:
        y = bg_h - wm_h - margin
    else:
        y = margin

    return max(0, x), max(0, y)


async def apply_thumbnail_watermark(thumb_path: str, user_dict: dict) -> str:
    import os
    if not thumb_path or not await aiopath.exists(str(thumb_path)):
        return thumb_path

    if str(thumb_path).endswith("_wm.jpg"):
        return thumb_path

    wm_text = (
        user_dict.get("THUMB_WM_TEXT")
        or user_dict.get("WM_TEXT")
        or getattr(Config, "WM_TEXT", "")
        or ""
    )
    wm_img = (
        user_dict.get("THUMB_WM_IMAGE")
        or user_dict.get("WM_IMAGE")
        or getattr(Config, "WM_IMAGE", "")
        or ""
    )
    wm_size = (
        user_dict.get("THUMB_WM_SIZE")
        or user_dict.get("WM_SIZE")
        or getattr(Config, "WM_SIZE", "30")
        or "30"
    )
    wm_img_pos = (
        user_dict.get("THUMB_WM_IMAGE_POSITION")
        or user_dict.get("THUMB_WM_POSITION")
        or user_dict.get("WM_IMAGE_POSITION")
        or user_dict.get("WM_POSITION")
        or getattr(Config, "WM_POSITION", "Top-Left")
        or "Top-Left"
    )
    wm_text_pos = (
        user_dict.get("THUMB_WM_TEXT_POSITION")
        or user_dict.get("THUMB_WM_POSITION")
        or user_dict.get("WM_TEXT_POSITION")
        or user_dict.get("WM_POSITION")
        or getattr(Config, "WM_POSITION", "Top-Left")
        or "Top-Left"
    )
    wm_color = (
        user_dict.get("THUMB_WM_COLOR")
        or user_dict.get("WM_COLOR")
        or getattr(Config, "WM_COLOR", "white")
        or "white"
    )

    if not wm_text and not wm_img:
        return thumb_path

    try:
        def _apply():
            with Image.open(thumb_path) as base_img:
                base_img = base_img.convert("RGBA")
                w, h = base_img.size

                if wm_img and os.path.exists(str(wm_img)):
                    with Image.open(wm_img) as watermark:
                        watermark = watermark.convert("RGBA")
                        scale_pct = 20
                        try:
                            scale_pct = int(str(wm_size).replace("%", "").strip())
                        except ValueError:
                            scale_pct = 20
                        wm_w = int(w * (scale_pct / 100.0))
                        aspect = watermark.height / watermark.width
                        wm_h = int(wm_w * aspect)
                        watermark = watermark.resize(
                            (max(1, wm_w), max(1, wm_h)),
                            Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS,
                        )

                        x, y = _calc_wm_position(wm_img_pos, w, h, wm_w, wm_h, margin=15)
                        base_img.paste(watermark, (x, y), watermark)

                elif wm_text:
                    from PIL import ImageDraw, ImageFont
                    draw = ImageDraw.Draw(base_img)
                    try:
                        font_size = int(str(wm_size).strip())
                    except ValueError:
                        font_size = max(16, int(h * 0.05))
                    try:
                        font = ImageFont.truetype("arial.ttf", font_size)
                    except Exception:
                        font = ImageFont.load_default()

                    bbox = draw.textbbox((0, 0), wm_text, font=font)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]

                    x, y = _calc_wm_position(wm_text_pos, w, h, text_w, text_h, margin=15)
                    font_fill = wm_color or "white"
                    try:
                        draw.text((x, y), wm_text, fill=font_fill, font=font)
                    except Exception:
                        draw.text((x, y), wm_text, fill=(255, 255, 255, 230), font=font)

                out_path = f"{thumb_path}_wm.jpg"
                base_img.convert("RGB").save(out_path, "JPEG", quality=90)
                return out_path

        return await sync_to_async(_apply)
    except Exception as e:
        LOGGER.warning(f"Error applying thumbnail watermark: {e}")
        return thumb_path
