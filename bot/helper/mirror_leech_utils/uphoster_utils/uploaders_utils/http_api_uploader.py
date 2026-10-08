"""Configurable HTTP API upload destination.

Supports generic multipart upload endpoints. Named destinations such as
GDFlix/HubCloud/FilePress/LuluStream are exposed in the UI, but require the
host's current upload endpoint/token to be configured; this avoids pretending
an undocumented endpoint is stable.
"""
from logging import getLogger
from os import path as ospath, walk
from aiohttp import ClientSession, FormData
from aiofiles.os import path as aiopath
from bot.helper.ext_utils.bot_utils import sync_to_async
from ..base import BaseUpload
from ..common import ProgressFileReader

LOGGER = getLogger(__name__)

DEST_CONFIG = {
    "gdflix": ("GDFLIX_UPLOAD_URL", "GDFLIX_API_KEY", "GDFlix"),
    "hubcloud": ("HUBCLOUD_UPLOAD_URL", "HUBCLOUD_API_KEY", "HubCloud"),
    "filepress": ("FILEPRESS_UPLOAD_URL", "FILEPRESS_API_KEY", "FilePress"),
    "lulustream": ("LULUSTREAM_UPLOAD_URL", "LULUSTREAM_API_KEY", "LuluStream"),
    "streamtape": ("STREAMTAPE_UPLOAD_URL", "STREAMTAPE_API_KEY", "StreamTape"),
    "filemoon": ("FILEMOON_UPLOAD_URL", "FILEMOON_API_KEY", "FileMoon"),
    "uploadhub": ("UPLOADHUB_UPLOAD_URL", "UPLOADHUB_API_KEY", "UploadHub"),
    "filestreams": ("FILESTREAMS_UPLOAD_URL", "FILESTREAMS_API_KEY", "FileStreams"),
}

class HttpApiUpload(BaseUpload):
    SERVICE_NAME = "HTTP API"

    def __init__(self, listener, path, folder_name="", service=""):
        self.service = service.lower().strip()
        self._url_key, self._token_key, self._label = DEST_CONFIG.get(
            self.service, ("", "", self.service or "HTTP API")
        )
        super().__init__(listener, path, folder_name)

    def _resolve_token(self):
        from bot import user_data
        from bot.core.config_manager import Config
        ud = user_data.get(self.listener.user_id, {})
        return ud.get(self._token_key) or getattr(Config, self._token_key, "")

    def _resolve_url(self):
        from bot import user_data
        from bot.core.config_manager import Config
        ud = user_data.get(self.listener.user_id, {})
        return ud.get(self._url_key) or getattr(Config, self._url_key, "")

    async def _validate_token(self):
        self.api_url = self._resolve_url()
        if not self.api_url:
            raise ValueError(
                f"{self._label} upload endpoint is not configured. "
                f"Set {self._url_key} to the current official upload API endpoint."
            )

    async def _upload_one(self, file_path):
        name = ospath.basename(file_path)
        data = FormData()
        with ProgressFileReader(file_path, self._progress_callback) as fp:
            data.add_field("file", fp, filename=name, content_type="application/octet-stream")
            headers = {}
            if self.token:
                headers["Authorization"] = (
                    self.token if self.token.lower().startswith(("bearer ", "basic "))
                    else f"Bearer {self.token}"
                )
            async with ClientSession() as session:
                async with session.post(self.api_url, data=data, headers=headers) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        raise ValueError(f"HTTP {resp.status}: {body[:500]}")
                    try:
                        payload = await resp.json(content_type=None)
                    except Exception:
                        payload = {}
                    link = (
                        payload.get("url")
                        or payload.get("link")
                        or payload.get("download_url")
                        or (payload.get("data") or {}).get("url")
                        or (payload.get("data") or {}).get("download_url")
                    )
                    if not link:
                        raise ValueError(
                            f"{self._label} upload succeeded but no URL was returned by the API."
                        )
                    return link

    async def _upload_process(self):
        if await aiopath.isfile(self._path):
            link = await self._upload_one(self._path)
            self.total_files = 1
            await self.listener.on_upload_complete(link, 1, 0, "File", dir_id="")
            return

        if await aiopath.isdir(self._path):
            links = []
            for base, _, files in await sync_to_async(walk, self._path):
                for name in files:
                    if self.listener.is_cancelled:
                        return
                    link = await self._upload_one(ospath.join(base, name))
                    links.append(link)
                    self.total_files += 1
            if not links:
                raise ValueError("No files found to upload.")
            await self.listener.on_upload_complete(
                "\n".join(links), self.total_files, 1, "Folder", dir_id=""
            )
            return

        raise ValueError("Invalid upload path.")
