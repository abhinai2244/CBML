from logging import getLogger

from tenacity import RetryError

from bot.helper.ext_utils.bot_utils import SetInterval

LOGGER = getLogger(__name__)


class BaseUpload:
    """Shared base for all DDL uploaders (GoFile, BuzzHeavier, PixelDrain).

    Subclasses must override:
        SERVICE_NAME, _TOKEN_KEY, _CONFIG_KEY
        _validate_token()
        _upload_process()
    """

    SERVICE_NAME = ""

    def __init__(self, listener, path, folder_name=""):
        self.listener = listener
        self._path = path
        self.folder_name = folder_name
        self._updater = None
        self._is_errored = False
        self._processed_bytes = 0
        self.last_uploaded = 0
        self.total_time = 0
        self.total_files = 0
        self.total_folders = 0
        self.is_uploading = True
        self.update_interval = 3
        self.token = self._resolve_token()

    def _resolve_token(self):
        from bot import user_data
        from bot.core.config_manager import Config

        user_dict = user_data.get(self.listener.user_id, {})
        return user_dict.get(self._TOKEN_KEY) or getattr(Config, self._CONFIG_KEY, "")

    @property
    def speed(self):
        try:
            return self._processed_bytes / self.total_time
        except Exception:
            return 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    def _progress_callback(self, current):
        chunk = current - self.last_uploaded
        self.last_uploaded = current
        self._processed_bytes += chunk

    async def progress(self):
        self.total_time += self.update_interval

    async def _validate_token(self):
        """Override to validate API token before upload."""
        pass

    async def _upload_process(self):
        """Override: handle file vs dir dispatch, call on_upload_complete."""
        raise NotImplementedError

    async def upload(self):
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            if self.listener.is_cancelled:
                return
            try:
                LOGGER.info(f"{self.SERVICE_NAME} Uploading (Attempt {attempt}/{max_attempts}): {self._path}")
                self._updater = SetInterval(self.update_interval, self.progress)
                await self._validate_token()
                await self._upload_process()
                break
            except Exception as err:
                if isinstance(err, RetryError):
                    LOGGER.info(f"Total Attempts: {err.last_attempt.attempt_number}")
                    err = err.last_attempt.exception()
                err_msg = str(err).replace(">", "").replace("<", "")
                LOGGER.error(f"{self.SERVICE_NAME} attempt {attempt} failed: {err_msg}")
                if attempt < max_attempts and not self.listener.is_cancelled:
                    from asyncio import sleep as asleep
                    self.last_uploaded = 0
                    self._processed_bytes = 0
                    await asleep(2)
                    continue
                await self.listener.on_upload_error(err_msg)
                self._is_errored = True
            finally:
                if self._updater:
                    self._updater.cancel()
                    self._updater = None

    async def cancel_task(self):
        self.listener.is_cancelled = True
        if self.is_uploading:
            LOGGER.info(f"Cancelling {self.SERVICE_NAME} Upload: {self.listener.name}")
            await self.listener.on_upload_error(
                f"{self.SERVICE_NAME} upload has been cancelled!"
            )
