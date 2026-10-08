from logging import getLogger
from os import path as ospath
from os import walk as oswalk

from aiofiles.os import path as aiopath
from aiohttp import ClientSession, FormData
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bot.helper.ext_utils.bot_utils import sync_to_async
from bot.helper.ext_utils.telegraph_helper import telegraph

from bot.core.config_manager import Config

from ..base import BaseUpload
from ..common import ProgressFileReader

LOGGER = getLogger(__name__)


class VikingFileUpload(BaseUpload):
    SERVICE_NAME = "VikingFile"
    _TOKEN_KEY = "VIKINGFILE_HASH"
    _CONFIG_KEY = "VIKINGFILE_HASH"

    def __init__(self, listener, path, folder_name=""):
        super().__init__(listener, path, folder_name)
        self.base_url = "https://vikingfile.com/api"
        self._server = None
        self._user_folder = self._resolve_user_folder()

    def _resolve_user_folder(self):
        from bot import user_data

        user_dict = user_data.get(self.listener.user_id, {})
        return user_dict.get("VIKINGFILE_FOLDER") or Config.VIKINGFILE_FOLDER or ""

    async def __get_server(self):
        if self._server:
            return self._server
        async with ClientSession() as session:
            async with session.get(f"{self.base_url}/get-server") as resp:
                res = await resp.json(content_type=None)
                self._server = res.get("server", "https://upload.vikingfile.com")
                return self._server

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
    )
    async def upload_file(self, path: str, folder_path: str = ""):
        if self.listener.is_cancelled:
            return None
        server = await self.__get_server()
        file_name = ospath.basename(path)
        with ProgressFileReader(
            filename=path, read_callback=self._progress_callback
        ) as file:
            data = FormData()
            data.add_field("file", file, filename=file_name)
            data.add_field("user", self.token or "")
            if folder_path:
                data.add_field("path", folder_path)
            async with ClientSession() as session:
                async with session.post(server, data=data) as resp:
                    res = await resp.json(content_type=None)
                    url = res.get("url")
                    if url:
                        return url
                    raise Exception(f"Upload failed: {res}")

    async def _upload_dir(self, input_directory):
        links = []
        for root, _, files in await sync_to_async(oswalk, input_directory):
            for file in sorted(files):
                if self.listener.is_cancelled:
                    return links
                file_path = ospath.join(root, file)
                rel_root = ospath.relpath(root, ospath.dirname(input_directory))
                if self._user_folder:
                    folder_path = f"{self._user_folder}/{rel_root}"
                else:
                    folder_path = rel_root
                url = await self.upload_file(file_path, folder_path=folder_path)
                if url:
                    links.append((file, url))
                    self.total_files += 1
        return links

    async def _make_telegraph_page(self, links):
        content = "".join(
            f'<p>{i}. <a href="{url}">{name}</a></p>'
            for i, (name, url) in enumerate(links, 1)
        )
        page = await telegraph.create_page(
            title=self.listener.name,
            content=content,
        )
        return f"https://telegra.ph/{page['path']}"

    async def _validate_token(self):
        if not self.token:
            LOGGER.warning("VikingFile User Hash not set — uploading anonymously.")

    async def _upload_process(self):
        if await aiopath.isfile(self._path):
            url = await self.upload_file(self._path, folder_path=self._user_folder)
            if not url:
                raise ValueError("Failed to upload file to VikingFile")
            link = url
            mime_type = "File"
            self.total_files = 1
        elif await aiopath.isdir(self._path):
            links = await self._upload_dir(self._path)
            if not links:
                raise ValueError("Failed to upload folder to VikingFile")
            mime_type = "Folder"
            self.total_folders = 1
            if len(links) == 1:
                link = links[0][1]
            else:
                link = await self._make_telegraph_page(links)
        else:
            raise ValueError("Invalid file path!")

        if self.listener.is_cancelled:
            return

        LOGGER.info(f"Uploaded To VikingFile: {self.listener.name}")
        await self.listener.on_upload_complete(
            link,
            self.total_files,
            self.total_folders,
            mime_type,
            dir_id="",
        )
