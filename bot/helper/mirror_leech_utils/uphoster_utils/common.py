from io import BufferedReader
from json import loads as json_loads
from pathlib import Path


class ProgressFileReader(BufferedReader):
    def __init__(self, filename, read_callback=None):
        super().__init__(open(filename, "rb"))
        self.__read_callback = read_callback
        self.length = Path(filename).stat().st_size

    def read(self, size=None):
        size = size or (self.length - self.tell())
        if self.__read_callback:
            self.__read_callback(self.tell())
        return super().read(size)

    def __len__(self):
        return self.length


def extract_id(response):
    """Extract an ID from nested API response formats.

    Handles dict, nested dict with 'data' key, and JSON string variants.
    Used by BuzzHeavier but available for any service with similar responses.
    """
    if isinstance(response, str):
        try:
            response = json_loads(response)
        except Exception:
            return response.strip().strip('"')
    if isinstance(response, dict):
        if "id" in response:
            return response["id"]
        if isinstance(response.get("data"), dict) and "id" in response["data"]:
            return response["data"]["id"]
    return response
