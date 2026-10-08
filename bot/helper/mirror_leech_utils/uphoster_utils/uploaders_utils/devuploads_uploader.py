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


class DevUploadsUpload(BaseUpload):
    SERVICE_NAME = "DevUploads"
    _TOKEN_KEY = "DEVUPLOADS_KEY"
    _CONFIG_KEY = "DEVUPLOADS_KEY"

    def __init__(self, listener, path, folder_name=""):
        super().__init__(listener, path, folder_name)
        self.server_api_url = "https://devuploads.com/api/upload/server"
        self._sess_id = None
        self._server_url = None
        self._user_folder = self._resolve_user_folder()

    def _resolve_user_folder(self):
        from bot import user_data

        user_dict = user_data.get(self.listener.user_id, {})
        return user_dict.get("DEVUPLOADS_FOLDER") or Config.DEVUPLOADS_FOLDER or ""

    async def __get_upload_server(self):
        async with ClientSession() as session:
            async with session.get(f"{self.server_api_url}?key={self.token}") as resp:
                result = await resp.json(content_type=None)
                if result.get("status") == 200:
                    self._sess_id = result.get("sess_id")
                    self._server_url = result.get("result")
                    return True
                raise Exception(f"Failed to get upload server: {result}")

    async def __set_file_folder(self, file_code: str):
        async with ClientSession() as session:
            url = (
                f"https://devuploads.com/api/file/set_folder"
                f"?key={self.token}&file_code={file_code}&fld_id={self._user_folder}"
            )
            async with session.get(url) as resp:
                result = await resp.json(content_type=None)
                if result.get("status") != 200:
                    LOGGER.warning(f"DevUploads set_folder failed: {result}")

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
    )
    async def upload_file(self, path: str):
        if self.listener.is_cancelled:
            return None
        file_name = ospath.basename(path)
        with ProgressFileReader(
            filename=path, read_callback=self._progress_callback
        ) as file:
            data = FormData()
            data.add_field("sess_id", self._sess_id)
            data.add_field("utype", "reg")
            data.add_field("file", file, filename=file_name)
            async with ClientSession() as session:
                async with session.post(
                    self._server_url, data=data, timeout=3600
                ) as resp:
                    result = await resp.json(content_type=None)
                    if isinstance(result, list):
                        result = result[0] if result else {}
                    file_code = result.get("file_code")
                    if file_code:
                        if self._user_folder:
                            await self.__set_file_folder(file_code)
                        return f"https://devuploads.com/{file_code}"
                    raise Exception(f"Upload failed: {result.get('message', result)}")

    async def _upload_dir(self, input_directory):
        links = []
        for root, _, files in await sync_to_async(oswalk, input_directory):
            for file in sorted(files):
                if self.listener.is_cancelled:
                    return links
                file_path = ospath.join(root, file)
                link = await self.upload_file(file_path)
                if link:
                    links.append((file, link))
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
            raise ValueError(
                "DevUploads API Key not configured! Please set DEVUPLOADS_KEY."
            )
        if not await self.__get_upload_server():
            raise Exception(
                "Invalid DevUploads API Key or failed to get upload server!"
            )

    async def _upload_process(self):
        if await aiopath.isfile(self._path):
            link = await self.upload_file(self._path)
            if not link:
                raise ValueError("Failed to upload file to DevUploads")
            mime_type = "File"
            self.total_files = 1
        elif await aiopath.isdir(self._path):
            links = await self._upload_dir(self._path)
            if not links:
                raise ValueError("Failed to upload folder to DevUploads")
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

        LOGGER.info(f"Uploaded To DevUploads: {self.listener.name}")
        await self.listener.on_upload_complete(
            link,
            self.total_files,
            self.total_folders,
            mime_type,
            dir_id="",
        )
