from ...ext_utils.status_utils import (
    MirrorStatus,
    EngineStatus,
    get_readable_file_size,
    get_readable_time,
)


class MegaDownloadStatus:
    def __init__(self, listener, obj, gid, status=""):
        self.listener = listener
        self._obj = obj
        self._gid = gid
        self._status = status
        self._init_size = self.listener.size
        self.engine = EngineStatus().STATUS_MEGA

    def name(self):
        return self.listener.name

    def _size_str(self):
        if self.listener.size > 0:
            return self.listener.size
        if self._status == "up" and hasattr(self._obj, "_size") and self._obj._size > 0:
            return self._obj._size
        if (
            hasattr(self._obj, "_total_folder_size")
            and self._obj._total_folder_size > 0
        ):
            return self._obj._total_folder_size
        if self._init_size > 0:
            return self._init_size
        return None

    def _size(self):
        s = self._size_str()
        return s if s else 1

    def progress_raw(self):
        try:
            return round(self._obj.downloaded_bytes / self._size() * 100, 2)
        except ZeroDivisionError:
            return 0.0

    def progress(self):
        return f"{self.progress_raw()}%"

    def status(self):
        if self._status == "up":
            return MirrorStatus.STATUS_UPLOAD
        elif self._status == "dl":
            return MirrorStatus.STATUS_DOWNLOAD
        elif self._status == "cl":
            return MirrorStatus.STATUS_CLONE

    def processed_bytes(self):
        return get_readable_file_size(self._obj.downloaded_bytes)

    def eta(self):
        if not self._obj.speed:
            return "-"
        try:
            seconds = (self._size() - self._obj.downloaded_bytes) / self._obj.speed
            return get_readable_time(seconds)
        except (ZeroDivisionError, ValueError):
            return "-"

    def size(self):
        s = self._size_str()
        return "Unknown" if s is None else get_readable_file_size(s)

    def speed(self):
        return f"{get_readable_file_size(self._obj.speed)}/s"

    def gid(self):
        return self._gid

    def task(self):
        return self

    async def cancel_task(self):
        await self._obj.cancel_task()
        await self.listener.on_download_error(f"{self._status} stopped by user!")
