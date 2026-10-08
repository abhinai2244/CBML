from asyncio import sleep

from PIL import Image
from pyrogram import StopTransmission
from pyrogram.errors import FloodWait, PhotoInvalidDimensions

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:
    FloodPremiumWait = FloodWait

from os import path as ospath
from aiofiles.os import path as aiopath, remove

from ... import LOGGER
from ...core.config_manager import Config
from ...core.tg_client import TgClient
from ..telegram_helper.tg_transfer import HypertgTransfer
from ..ext_utils.media_utils import (
    apply_thumbnail_watermark,
    format_tg_thumbnail,
    get_audio_thumbnail,
    get_document_type,
    get_media_info,
    get_multiple_frames_thumbnail,
    get_video_thumbnail,
)
from ..ext_utils.bot_utils import sync_to_async
from ..ext_utils.bot_utils import parse_dest
from ..ext_utils.tmdb_utils import get_auto_thumbnail


class HypertgUpload(HypertgTransfer):
    def __init__(self, obj):
        super().__init__(obj)
        self._up_file = ""
        self._file_progress = {}
        if hasattr(obj, "_hu_clients") and obj._hu_clients:
            self.clients = dict(obj._hu_clients)
            self.client_ids = list(self.clients.keys())
            self.work_loads = {k: 0 for k in self.client_ids}
            self.num_clients = len(self.clients)
            from ..telegram_helper.tg_transfer import MtprotoPool
            self._pool = MtprotoPool(self.clients)
            self._use_user_bots = True

    def _auto_thumb_enabled(self):
        return self._listener.user_dict.get("AUTO_THUMBNAIL", False) or (
            "AUTO_THUMBNAIL" not in self._listener.user_dict and getattr(Config, "AUTO_THUMBNAIL", False)
        )

    async def _get_auto_thumb(self, file_path, is_video=False, duration=0, is_audio=False):
        if not self._auto_thumb_enabled():
            return None

        # 1. Try TMDb poster lookup
        auto_t = await get_auto_thumbnail(file_path)
        if auto_t and await aiopath.exists(str(auto_t)):
            return auto_t

        # 2. Local fallback if TMDb fails
        if self._listener.thumbnail_layout and is_video:
            grid_t = await get_multiple_frames_thumbnail(file_path, self._listener.thumbnail_layout, False)
            if grid_t and await aiopath.exists(str(grid_t)):
                return grid_t

        if is_video:
            return await get_video_thumbnail(file_path, duration)
        elif is_audio:
            return await get_audio_thumbnail(file_path)

        return None

    async def _progress(self, current, total, file_path):
        if self._listener.is_cancelled:
            raise StopTransmission()
        self._file_progress[file_path] = current
        self._obj._processed_bytes = sum(self._file_progress.values())

    async def upload(
        self,
        file_path,
        cap_mono,
        reply_target,
        reply_to_message_id,
        force_document=False,
        user_thumb=None,
        user_session=False,
    ):
        self._cancel.clear()
        self._up_file = ospath.basename(file_path)

        is_video, is_audio, is_image = await get_document_type(file_path)

        user_perm = self._listener.user_dict.get("THUMBNAIL") or f"thumbnails/{self._listener.user_id}.jpg"
        has_custom = await aiopath.exists(str(user_perm))
        thumb_mode = self._listener.user_dict.get("THUMBNAIL_MODE", "custom" if has_custom else "none")

        duration = 0
        width = 480
        height = 320
        artist = ""
        title = ""
        if is_video:
            duration = (await get_media_info(file_path))[0]
        elif is_audio:
            duration, artist, title = await get_media_info(file_path)

        thumb = None
        if thumb_mode == "auto":
            thumb = await self._get_auto_thumb(file_path, is_video=is_video, duration=duration, is_audio=is_audio)
        elif thumb_mode == "custom":
            if user_thumb and user_thumb != "none" and await aiopath.exists(str(user_thumb)):
                thumb = user_thumb
            elif self._listener.thumb and self._listener.thumb != "none" and await aiopath.exists(str(self._listener.thumb)):
                thumb = self._listener.thumb
            elif has_custom:
                thumb = user_perm
        elif thumb_mode == "random" and is_video:
            thumb = await get_video_thumbnail(file_path, duration)
        elif thumb_mode == "none":
            thumb = None

        if thumb and thumb != "none" and await aiopath.exists(str(thumb)):
            thumb = await apply_thumbnail_watermark(thumb, self._listener.user_dict)

        if (
            force_document
            or self._listener.as_doc
            or (not is_video and not is_audio and not is_image)
        ):
            key = "documents"
            if thumb and thumb != "none" and await aiopath.exists(str(thumb)):
                doc_thumb = f"{thumb}_320.jpg"
                try:
                    with Image.open(thumb) as img:
                        img = img.convert("RGB")
                        img.thumbnail((320, 320), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
                        img.save(doc_thumb, "JPEG", quality=90)
                    thumb = doc_thumb
                except Exception as e:
                    LOGGER.warning(f"Document thumbnail formatting error: {e}")
        elif is_video:
            key = "videos"
            if thumb and thumb != "none" and await aiopath.exists(str(thumb)):
                try:
                    with Image.open(thumb) as img:
                        img = img.convert("RGB")
                        width, height = img.size
                except Exception:
                    pass
        elif is_audio:
            key = "audios"
        else:
            key = "photos"

        if thumb and thumb != "none" and await aiopath.exists(str(thumb)):
            formatted_t = await sync_to_async(format_tg_thumbnail, thumb)
            if formatted_t and await aiopath.exists(str(formatted_t)):
                thumb = formatted_t

        if thumb == "none":
            thumb = None

        up_size = ospath.getsize(file_path)
        hyper_user_only = False
        personal_user = getattr(self._listener, "tg_user_client", None)
        if personal_user:
            # A per-user session explicitly owns this upload; do not silently
            # switch it to a global helper/user account.
            use_hyper = False
            user_session = True
        elif up_size > 2097152000 and any(k < 0 for k in self.clients):
            if TgClient.user:
                use_hyper = False
                user_session = True
            else:
                use_hyper = True
                hyper_user_only = True
                user_session = False
        else:
            use_hyper = (
            (Config.USE_HYPER or getattr(self, "_use_user_bots", False))
            and self.clients
            and up_size > 10 * 1024 * 1024
            and getattr(self._listener, "tg_user_client", None) is None
        )
        # Upload only to a configured dump destination; otherwise DM the requester.
        # AUTHORIZED_CHATS controls access and is never treated as an upload target.
        raw_auth = str(getattr(Config, "AUTHORIZED_CHATS", "") or "")
        auth_ids = set()
        for raw in raw_auth.split():
            base = raw.split("|", 1)[0].strip()
            if base.lstrip("-").isdigit():
                auth_ids.add(int(base))

        candidate = self._listener.up_dest or Config.LEECH_LOG_CHAT
        if candidate:
            upload_chat_id, thread_id = parse_dest(candidate) if not isinstance(candidate, int) else (candidate, None)
        else:
            upload_chat_id, thread_id = self._listener.user_id, None

        if upload_chat_id in auth_ids:
            upload_chat_id, thread_id = self._listener.user_id, None
            LOGGER.warning(
                "HyperUP blocked AUTHORIZED_CHATS destination; falling back to DM %s",
                self._listener.user_id,
            )
        try:
            if use_hyper:
                hyper_rply = (
                    reply_to_message_id
                    if upload_chat_id == reply_target.chat.id
                    else None
                )
                sent = await self._hyper_send(
                    file_path,
                    key,
                    thumb,
                    cap_mono,
                    upload_chat_id,
                    hyper_rply,
                    thread_id,
                    duration=duration,
                    width=width,
                    height=height,
                    artist=artist,
                    title=title,
                    user_only=hyper_user_only,
                )
            else:
                direct_rply = (
                    reply_to_message_id
                    if upload_chat_id == reply_target.chat.id
                    else None
                )
                sent = await self._direct_send(
                    file_path,
                    key,
                    thumb,
                    cap_mono,
                    upload_chat_id,
                    direct_rply,
                    thread_id,
                    duration=duration,
                    width=width,
                    height=height,
                    artist=artist,
                    title=title,
                    user_session=user_session,
                )

            LOGGER.info(f"HypertgUL uploaded {self._up_file}")
            return sent

        except StopTransmission:
            LOGGER.warning(f"HypertgUL cancelled {self._up_file}")
            raise
        except Exception as e:
            LOGGER.error(f"HypertgUL fail {self._up_file}: {type(e).__name__}: {e}")
            raise
        finally:
            if thumb and (thumb.endswith("_320.jpg") or thumb.endswith("_tg.jpg")) and await aiopath.exists(thumb):
                try:
                    await remove(thumb)
                except Exception:
                    pass
            elif user_thumb is None and thumb is not None and await aiopath.exists(thumb):
                user_perm_thumb = self._listener.user_dict.get("THUMBNAIL") or f"thumbnails/{self._listener.user_id}.jpg"
                if thumb != user_perm_thumb and thumb != f"thumbnails/{self._listener.user_id}.jpg":
                    try:
                        await remove(thumb)
                    except Exception:
                        pass

    async def _send_with_retry(self, send_func, **kwargs):
        while True:
            try:
                return await send_func(**kwargs)
            except (FloodWait, FloodPremiumWait) as f:
                LOGGER.warning(f"HypertgUL flood {f.value}s on {self._up_file}")
                await sleep(f.value + 1)

    async def _try_send(self, key, client, kwargs):
        try:
            if key == "videos":
                return await self._send_with_retry(client.send_video, **kwargs)
            elif key == "audios":
                return await self._send_with_retry(client.send_audio, **kwargs)
            elif key == "photos":
                return await self._send_with_retry(client.send_photo, **kwargs)
            else:
                return await self._send_with_retry(client.send_document, **kwargs)
        except (PhotoInvalidDimensions, Exception) as e:
            err_str = str(e).upper()
            if (
                isinstance(e, PhotoInvalidDimensions)
                or "PHOTO_INVALID_DIMENSIONS" in err_str
                or "WIDTH_INVALID" in err_str
                or "HEIGHT_INVALID" in err_str
                or "MEDIA_EMPTY" in err_str
            ):
                LOGGER.warning(f"Thumbnail invalid dimensions ({e}), retrying upload without thumbnail...")
                kwargs.pop("thumb", None)
                kwargs.pop("video_cover", None)
                kwargs.pop("width", None)
                kwargs.pop("height", None)
                if key == "videos":
                    return await self._send_with_retry(client.send_video, **kwargs)
                elif key == "audios":
                    return await self._send_with_retry(client.send_audio, **kwargs)
                elif key == "photos":
                    return await self._send_with_retry(client.send_photo, **kwargs)
                else:
                    return await self._send_with_retry(client.send_document, **kwargs)
            raise

    async def _hyper_send(
        self,
        file_path,
        key,
        thumb,
        cap_mono,
        chat_id,
        reply_to_message_id,
        thread_id=None,
        duration=0,
        width=0,
        height=0,
        artist="",
        title="",
        user_only=False,
    ):
        if user_only:
            candidates = {k: self.work_loads[k] for k in self.clients if k < 0}
            if not candidates:
                idx = self._pick_client()
            else:
                idx = min(candidates, key=candidates.get)
        else:
            idx = self._pick_client()
        client = self.clients[idx]
        self.work_loads[idx] += 1

        try:
            kwargs = {
                "chat_id": chat_id,
                "disable_notification": True,
                "progress": self._progress,
                "progress_args": (file_path,),
            }
            if cap_mono:
                kwargs["caption"] = cap_mono
            if reply_to_message_id:
                kwargs["reply_to_message_id"] = reply_to_message_id
            elif thread_id:
                kwargs["message_thread_id"] = thread_id

            if key == "videos":
                if duration:
                    kwargs["duration"] = duration
                if width:
                    kwargs["width"] = width
                if height:
                    kwargs["height"] = height
                if thumb:
                    kwargs["video_cover"] = thumb
                    kwargs["thumb"] = thumb
            elif key == "audios":
                if duration:
                    kwargs["duration"] = duration
                if artist:
                    kwargs["performer"] = artist
                if title:
                    kwargs["title"] = title
                if thumb:
                    kwargs["thumb"] = thumb
            else:
                if thumb:
                    kwargs["thumb"] = thumb

            if key == "videos":
                kwargs["video"] = file_path
            elif key == "audios":
                kwargs["audio"] = file_path
            elif key == "photos":
                kwargs["photo"] = file_path
            else:
                kwargs["document"] = file_path

            sent = await self._try_send(key, client, kwargs)
            return sent
        finally:
            self.work_loads[idx] -= 1

    async def _direct_send(
        self,
        file_path,
        key,
        thumb,
        cap_mono,
        chat_id,
        reply_to_message_id,
        thread_id=None,
        duration=0,
        width=0,
        height=0,
        artist="",
        title="",
        user_session=False,
    ):
        client = (
            getattr(self._listener, "tg_user_client", None)
            if user_session and getattr(self._listener, "tg_user_client", None)
            else (TgClient.user if user_session and TgClient.user else self._listener.client)
        )
        kwargs = {
            "chat_id": chat_id,
            "disable_notification": True,
            "progress": self._progress,
            "progress_args": (file_path,),
        }
        if cap_mono:
            kwargs["caption"] = cap_mono
        if reply_to_message_id:
            kwargs["reply_to_message_id"] = reply_to_message_id
        elif thread_id:
            kwargs["message_thread_id"] = thread_id

        if key == "videos":
            if thumb:
                kwargs["thumb"] = thumb
                kwargs["video_cover"] = thumb
            if duration:
                kwargs["duration"] = duration
            if width:
                kwargs["width"] = width
            if height:
                kwargs["height"] = height
        elif key == "audios":
            if thumb:
                kwargs["thumb"] = thumb
            if duration:
                kwargs["duration"] = duration
            if artist:
                kwargs["performer"] = artist
            if title:
                kwargs["title"] = title
        else:
            if thumb:
                kwargs["thumb"] = thumb

        if key == "videos":
            kwargs["video"] = file_path
        elif key == "audios":
            kwargs["audio"] = file_path
        elif key == "photos":
            kwargs["photo"] = file_path
        else:
            kwargs["document"] = file_path

        return await self._try_send(key, client, kwargs)

    async def cancel(self):
        await super().cancel()
