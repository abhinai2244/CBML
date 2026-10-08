import os
from asyncio import Lock as AsyncLock, sleep as asleep
from contextlib import suppress
from secrets import token_hex

from aiofiles.os import makedirs
try:
    from mega import MegaApi, MegaCancelToken
except (ImportError, SyntaxError, Exception):
    try:
        from megasdk import MegaApi, MegaCancelToken
    except (ImportError, SyntaxError, Exception):
        MegaApi = MegaCancelToken = None

from .... import LOGGER, task_dict, task_dict_lock, user_data
from ....core.config_manager import Config
from ...telegram_helper.message_utils import send_status_message
from ...ext_utils.task_manager import (
    check_running_tasks,
    limit_checker,
    stop_duplicate_check,
)
from ...ext_utils.files_utils import clean_download
from ...ext_utils.links_utils import get_mega_subfolder_handle, is_mega_folder_link
from ...ext_utils.status_utils import (
    MirrorStatus,
    EngineStatus,
    get_readable_file_size,
    get_readable_time,
)
from ...listeners.mega_listener import (
    AsyncMega,
    MegaAppListener,
    MegaFolderListener,
    _call_attr,
    _get_node_handle,
    _get_node_name,
    _get_node_size,
    _is_node_folder,
    _mega_error_format,
    _MEGA_SDK_LOCK,
)
from ...mirror_leech_utils.status_utils.mega_status import MegaDownloadStatus
from ...mirror_leech_utils.status_utils.queue_status import QueueStatus


def _patch_mega_py():
    try:
        from mega.errors import RequestError
        if not getattr(RequestError, "_is_patched", False):
            _orig_init = RequestError.__init__
            def _patched_init(self, message):
                if isinstance(message, int):
                    _orig_init(self, message)
                else:
                    self.code = -1
                    self.message = str(message)
            RequestError.__init__ = _patched_init
            RequestError._is_patched = True
    except Exception:
        pass

    try:
        import re
        import json
        import requests
        from mega import Mega
        if hasattr(Mega, "_parse_url") and not getattr(Mega, "_is_patched", False):
            _orig_parse_url = Mega._parse_url
            def _patched_parse_url(self, url):
                m = re.search(r"mega\.(?:co\.)?nz/(file|folder)/([^#]+)#(.+)", url)
                if m:
                    prefix = "#F!" if m.group(1) == "folder" else "#!"
                    url = f"https://mega.nz/{prefix}{m.group(2)}!{m.group(3)}"
                return _orig_parse_url(self, url)
            Mega._parse_url = _patched_parse_url
            Mega._is_patched = True

        from tenacity import retry, retry_if_exception_type, wait_exponential
        if not getattr(getattr(Mega, "_api_request", None), "_is_mega_patched", False):
            def _patched_api_request(self, data):
                req_params = {"id": self.sequence_num}
                self.sequence_num += 1

                if self.sid:
                    req_params.update({"sid": self.sid})

                data_copy = data
                if isinstance(data, dict):
                    data_copy = dict(data)
                    if "folder_id" in data_copy:
                        req_params["n"] = data_copy.pop("folder_id")
                    elif data_copy.get("a") == "f" and "n" in data_copy:
                        req_params["n"] = data_copy.pop("n")
                    data_list = [data_copy]
                elif isinstance(data, list):
                    data_list = data
                else:
                    data_list = [data]

                url = f"{self.schema}://g.api.{self.domain}/cs"
                response = requests.post(
                    url,
                    params=req_params,
                    data=json.dumps(data_list),
                    timeout=self.timeout,
                )
                json_resp = json.loads(response.text)
                try:
                    if isinstance(json_resp, list):
                        int_resp = json_resp[0] if isinstance(json_resp[0], int) else None
                    elif isinstance(json_resp, int):
                        int_resp = json_resp
                    else:
                        int_resp = None
                except IndexError:
                    int_resp = None

                if int_resp is not None:
                    if int_resp == 0:
                        return int_resp
                    if int_resp == -3:
                        msg = "Request failed, retrying"
                        raise RuntimeError(msg)
                    from mega.errors import RequestError
                    raise RequestError(int_resp)
                return json_resp[0]

            patched_fn = retry(
                retry=retry_if_exception_type(RuntimeError),
                wait=wait_exponential(multiplier=2, min=2, max=60),
            )(_patched_api_request)
            patched_fn._is_mega_patched = True
            Mega._api_request = patched_fn
    except Exception:
        pass


def _get_mega_session(email=None, password=None):
    _patch_mega_py()
    from mega import Mega
    if email and password:
        try:
            return Mega().login(email, password)
        except Exception as e:
            LOGGER.warning(f"Mega user login failed, falling back to unauthenticated session: {e}")
    return Mega()


def _execute_mega_py_request(m, request_data, email=None, password=None):
    from mega import Mega
    try:
        return m._api_request(request_data), m
    except Exception as e:
        err_str = str(e)
        if any(err in err_str for err in ("EACCESS", "ESID", "Access violation", "Invalid or expired user session", "-15")):
            LOGGER.warning(f"Mega session error ({e}). Attempting session refresh/fallback...")
            if email and password:
                try:
                    new_m = Mega().login(email, password)
                    res = new_m._api_request(request_data)
                    return res, new_m
                except Exception as login_err:
                    LOGGER.warning(f"Re-login failed ({login_err}), falling back to unauthenticated session...")
            unauth_m = Mega()
            res = unauth_m._api_request(request_data)
            return res, unauth_m
        raise e


def _mega_py_download_sync(listener, path, email, password, status_helper=None):
    _patch_mega_py()
    m = _get_mega_session(email, password)
    try:
        downloaded_path = m.download_url(listener.link, dest_path=path)
        return downloaded_path
    except Exception as e:
        err_str = str(e)
        if any(err in err_str for err in ("EACCESS", "ESID", "Access violation", "Invalid or expired user session", "-15")):
            LOGGER.warning(f"Mega download_url session error ({e}), retrying unauthenticated...")
            from mega import Mega
            return Mega().download_url(listener.link, dest_path=path)
        raise e


class MegaPyStatusHelper:
    def __init__(self, listener, gid):
        self.listener = listener
        self._gid = gid
        self.downloaded_bytes = 0
        self.speed_val = 0
        self._start_time = 0
        self.engine = EngineStatus().STATUS_MEGA

    def name(self):
        return self.listener.name

    def progress_raw(self):
        if getattr(self.listener, "size", 0) > 0:
            return round((self.downloaded_bytes / self.listener.size) * 100, 2)
        return 0.0

    def progress(self):
        return f"{self.progress_raw()}%"

    def status(self):
        return MirrorStatus.STATUS_DOWNLOAD

    def processed_bytes(self):
        return get_readable_file_size(self.downloaded_bytes)

    def eta(self):
        if not self.speed_val:
            return "-"
        try:
            seconds = (self.listener.size - self.downloaded_bytes) / self.speed_val
            return get_readable_time(seconds)
        except Exception:
            return "-"

    def size(self):
        return (
            get_readable_file_size(self.listener.size)
            if getattr(self.listener, "size", 0) > 0
            else "Unknown"
        )

    def speed(self):
        return f"{get_readable_file_size(self.speed_val)}/s"

    def speed_str(self):
        return self.speed()

    def gid(self):
        return self._gid

    def task(self):
        return self

    async def cancel_task(self):
        self.listener.is_cancelled = True
        await self.listener.on_download_error("download stopped by user!")


def _download_file_chunks(
    file_url,
    file_size,
    dest_path,
    k_str,
    iv,
    meta_mac,
    status_helper=None,
    listener=None,
    max_retries=5,
    get_url_cb=None,
    base_downloaded=0,
):
    import requests
    from time import time
    from Cryptodome.Cipher import AES
    from Cryptodome.Util import Counter
    import mega.crypto as c

    downloaded = 0
    start_time = time()
    last_update_time = time()
    last_bytes = status_helper.downloaded_bytes if status_helper else 0

    if os.path.exists(dest_path):
        try:
            downloaded = os.path.getsize(dest_path)
            if downloaded > file_size:
                downloaded = 0
                os.remove(dest_path)
            else:
                downloaded = (downloaded // 16) * 16
                with open(dest_path, "a+b") as f:
                    f.truncate(downloaded)
        except OSError:
            downloaded = 0

    if status_helper:
        status_helper.downloaded_bytes = base_downloaded + downloaded

    initial_ctr = ((iv[0] << 32) + iv[1]) << 64
    current_url = file_url

    for attempt in range(max_retries):
        if listener and getattr(listener, "is_cancelled", False):
            return False

        headers = {}
        if downloaded > 0:
            headers["Range"] = f"bytes={downloaded}-"

        try:
            res = requests.get(current_url, headers=headers, stream=True, timeout=30)
            res.raise_for_status()

            ctr_val = initial_ctr + (downloaded // 16)
            counter = Counter.new(128, initial_value=ctr_val)
            aes = AES.new(k_str, AES.MODE_CTR, counter=counter)

            mode = "r+b" if downloaded > 0 and os.path.exists(dest_path) else "wb"
            with open(dest_path, mode) as f:
                if downloaded > 0:
                    f.seek(downloaded)

                for chunk in res.iter_content(chunk_size=512 * 1024):
                    if listener and getattr(listener, "is_cancelled", False):
                        return False
                    if not chunk:
                        continue

                    dec_chunk = aes.decrypt(chunk)
                    f.write(dec_chunk)
                    chunk_len = len(chunk)
                    downloaded += chunk_len

                    if status_helper:
                        status_helper.downloaded_bytes = base_downloaded + downloaded
                        now = time()
                        elapsed = now - last_update_time
                        if elapsed >= 0.5:
                            speed = (status_helper.downloaded_bytes - last_bytes) / elapsed
                            status_helper.speed_val = max(0, int(speed))
                            last_update_time = now
                            last_bytes = status_helper.downloaded_bytes

            if downloaded >= file_size:
                if status_helper:
                    status_helper.downloaded_bytes = base_downloaded + file_size
                return True

        except Exception as e:
            LOGGER.warning(f"MegaPy download chunk attempt {attempt + 1} failed: {e}")
            if listener and getattr(listener, "is_cancelled", False):
                return False
            if attempt < max_retries - 1:
                if os.path.exists(dest_path):
                    try:
                        downloaded = os.path.getsize(dest_path)
                        downloaded = (downloaded // 16) * 16
                    except OSError:
                        pass
                if get_url_cb:
                    try:
                        new_url = get_url_cb()
                        if new_url:
                            current_url = new_url
                    except Exception as refresh_err:
                        LOGGER.warning(f"Failed to refresh URL for retry: {refresh_err}")
                continue
            raise e

    return downloaded >= file_size


def _mega_py_fetch_info(listener, email, password):
    _patch_mega_py()
    import mega.crypto as c
    from mega import Mega
    import re

    m = _get_mega_session(email, password)

    url = listener.link
    is_folder = is_mega_folder_link(url)

    if not is_folder:
        # File link
        parsed = m._parse_url(url).split("!")
        file_id = parsed[0]
        file_key_str = parsed[1]

        file_key = c.base64_to_a32(file_key_str)
        file_data, m = _execute_mega_py_request(
            m, {"a": "g", "g": 1, "p": file_id}, email, password
        )

        if "g" not in file_data:
            raise RuntimeError("MEGA file not accessible or link expired.")

        file_url = file_data["g"]
        file_size = file_data["s"]
        attribs = c.base64_url_decode(file_data["at"])

        k = (
            file_key[0] ^ file_key[4],
            file_key[1] ^ file_key[5],
            file_key[2] ^ file_key[6],
            file_key[3] ^ file_key[7],
        )
        iv = file_key[4:6] + (0, 0)
        meta_mac = file_key[6:8]

        attribs = c.decrypt_attr(attribs, k)
        file_name = attribs.get("n", f"file_{file_id}") if isinstance(attribs, dict) else f"file_{file_id}"

        listener.name = file_name
        listener.size = file_size

        return {
            "is_folder": False,
            "m": m,
            "file_url": file_url,
            "file_size": file_size,
            "file_name": file_name,
            "k": k,
            "iv": iv,
            "meta_mac": meta_mac,
        }

    else:
        # Folder link
        subfolder_handle = get_mega_subfolder_handle(url)
        folder_id = ""
        folder_key_str = ""

        m_f = re.search(r"mega\.(?:co\.)?nz/folder/([^#]+)#(.+)", url)
        if m_f:
            folder_id = m_f.group(1)
            folder_key_str = m_f.group(2)
        else:
            m_f2 = re.search(r"#F!([^!]+)!(.+)", url)
            if m_f2:
                folder_id = m_f2.group(1)
                folder_key_str = m_f2.group(2)

        if not folder_id or not folder_key_str:
            raise RuntimeError(f"Could not parse MEGA folder link: {url}")

        if "/" in folder_key_str:
            folder_key_str = folder_key_str.split("/")[0]

        k_folder = c.base64_to_a32(folder_key_str)
        nodes_res, m = _execute_mega_py_request(
            m, {"a": "f", "c": 1, "r": 1, "ca": 1, "n": folder_id}, email, password
        )

        if not isinstance(nodes_res, dict) or "f" not in nodes_res:
            raise RuntimeError("Failed to fetch node list for MEGA folder.")

        nodes = nodes_res["f"]
        nodes_dict = {}
        children_map = {}

        # Iteratively decrypt nodes so parent folder keys are resolved before child nodes
        for _ in range(5):
            for n in nodes:
                h = n.get("h")
                if h in nodes_dict:
                    continue
                p = n.get("p")
                t = n.get("t", 0)
                s = n.get("s", 0)
                k_raw = n.get("k", "")

                parent_node = nodes_dict.get(p)
                candidate_keys = []
                if parent_node and parent_node.get("raw_k_dec"):
                    candidate_keys.append(parent_node["raw_k_dec"])
                candidate_keys.append(k_folder)

                k_dec = None
                attribs = {}

                if k_raw:
                    for ck in candidate_keys:
                        for pair in k_raw.split("/"):
                            if ":" in pair:
                                _, k_enc = pair.split(":", 1)
                                try:
                                    k_a32 = c.str_to_a32(c.base64_url_decode(k_enc))
                                    kd = c.decrypt_key(k_a32, ck)

                                    at_raw = n.get("a", n.get("at", ""))
                                    at = c.base64_url_decode(at_raw) if at_raw else b""
                                    if at:
                                        if t == 0:
                                            file_k = (
                                                kd[0] ^ kd[4],
                                                kd[1] ^ kd[5],
                                                kd[2] ^ kd[6],
                                                kd[3] ^ kd[7],
                                            )
                                            attr = c.decrypt_attr(at, file_k)
                                        else:
                                            attr = c.decrypt_attr(at, kd)
                                        if isinstance(attr, dict) and attr.get("n"):
                                            k_dec = kd
                                            attribs = attr
                                            break
                                except Exception:
                                    pass
                        if k_dec:
                            break

                if k_dec is None:
                    continue

                if t == 0:
                    k = (
                        k_dec[0] ^ k_dec[4],
                        k_dec[1] ^ k_dec[5],
                        k_dec[2] ^ k_dec[6],
                        k_dec[3] ^ k_dec[7],
                    )
                    iv = k_dec[4:6] + (0, 0)
                    meta_mac = k_dec[6:8]
                else:
                    k = k_dec
                    iv = None
                    meta_mac = None

                name = attribs.get("n", f"node_{h}") if isinstance(attribs, dict) and attribs.get("n") else f"node_{h}"

                node_obj = {
                    "h": h,
                    "p": p,
                    "t": t,
                    "s": s,
                    "name": name,
                    "k": k,
                    "raw_k_dec": k_dec,
                    "iv": iv,
                    "meta_mac": meta_mac,
                }
                nodes_dict[h] = node_obj

                if p not in children_map:
                    children_map[p] = []
                children_map[p].append(h)

        target_node = None
        if subfolder_handle and subfolder_handle in nodes_dict:
            target_node = nodes_dict[subfolder_handle]
        else:
            for h, no in nodes_dict.items():
                if no["t"] == 2 or no["p"] not in nodes_dict:
                    target_node = no
                    break

        if not target_node:
            raise RuntimeError("Root node or subfolder node not found in MEGA folder.")

        root_name = target_node["name"]
        listener.name = root_name

        file_list = []

        def collect_files(curr_h, rel_path):
            curr = nodes_dict.get(curr_h)
            if not curr:
                return
            if curr["t"] == 0:
                file_list.append((curr, rel_path))
            elif curr["t"] in (1, 2):
                dir_path = os.path.join(rel_path, curr["name"]) if curr_h != target_node["h"] else rel_path
                for ch_h in children_map.get(curr_h, []):
                    collect_files(ch_h, dir_path)

        collect_files(target_node["h"], "")

        total_folder_size = sum(f_obj["s"] for f_obj, _ in file_list)
        listener.size = total_folder_size

        return {
            "is_folder": True,
            "m": m,
            "folder_id": folder_id,
            "root_name": root_name,
            "file_list": file_list,
            "total_folder_size": total_folder_size,
        }


def _mega_py_start_download(listener, path, info, status_helper):
    import mega.crypto as c
    from mega import Mega

    m = info["m"]
    if not info["is_folder"]:
        dest_file_path = os.path.join(path, info["file_name"])
        k_str = c.a32_to_str(info["k"])

        res = _download_file_chunks(
            info["file_url"],
            info["file_size"],
            dest_file_path,
            k_str,
            info["iv"],
            info["meta_mac"],
            status_helper=status_helper,
            listener=listener,
            base_downloaded=0,
        )
        return res
    else:
        root_name = info["root_name"]
        file_list = info["file_list"]

        folder_dest_dir = os.path.join(path, root_name)
        os.makedirs(folder_dest_dir, exist_ok=True)

        current_accumulated_bytes = 0

        for file_obj, rel_subpath in file_list:
            if listener and getattr(listener, "is_cancelled", False):
                return False

            file_dest_folder = os.path.join(folder_dest_dir, rel_subpath) if rel_subpath else folder_dest_dir
            os.makedirs(file_dest_folder, exist_ok=True)

            file_dest_path = os.path.join(file_dest_folder, file_obj["name"])

            nonlocal_state = {"m": m}
            folder_id = info.get("folder_id")
            req_data = {"a": "g", "g": 1, "n": file_obj["h"]}
            if folder_id:
                req_data["folder_id"] = folder_id

            def refresh_file_url():
                try:
                    curr_m = nonlocal_state["m"]
                    data, new_m = _execute_mega_py_request(curr_m, dict(req_data))
                    nonlocal_state["m"] = new_m
                    return data.get("g")
                except Exception as ex:
                    LOGGER.warning(f"Error refreshing URL for {file_obj['name']}: {ex}")
                    return None

            try:
                file_data, m = _execute_mega_py_request(m, dict(req_data))
                nonlocal_state["m"] = m
            except Exception as e:
                LOGGER.warning(f"Error fetching file URL for node {file_obj['name']}: {e}")
                current_accumulated_bytes += file_obj["s"]
                continue

            if "g" not in file_data:
                LOGGER.warning(f"Could not get download URL for file {file_obj['name']}")
                current_accumulated_bytes += file_obj["s"]
                continue

            file_url = file_data["g"]
            k_str = c.a32_to_str(file_obj["k"])

            ok = _download_file_chunks(
                file_url,
                file_obj["s"],
                file_dest_path,
                k_str,
                file_obj["iv"],
                file_obj["meta_mac"],
                status_helper=status_helper,
                listener=listener,
                get_url_cb=refresh_file_url,
                base_downloaded=current_accumulated_bytes,
            )
            if not ok and getattr(listener, "is_cancelled", False):
                return False

            current_accumulated_bytes += file_obj["s"]

        return True


async def _download_mega_py(listener, path, email, password):
    from ...ext_utils.bot_utils import sync_to_async

    await makedirs(path, exist_ok=True)
    gid = token_hex(5)

    try:
        # Phase 1: Fetch metadata only (name and size) before duplicate check / limits / queueing
        info = await sync_to_async(
            _mega_py_fetch_info,
            listener,
            email,
            password,
        )
    except Exception as e:
        LOGGER.error(f"Mega.py metadata fetch failed for link {listener.link}: {e}", exc_info=True)
        await listener.on_download_error(f"Mega download failed: {e}")
        return

    msg, button = await stop_duplicate_check(listener)
    if msg:
        await listener.on_download_error(msg, button)
        return

    if limit_exceeded := await limit_checker(listener):
        await listener.on_download_error(limit_exceeded, is_limit=True)
        return

    added_to_queue, event = await check_running_tasks(listener)
    if added_to_queue:
        async with task_dict_lock:
            task_dict[listener.mid] = QueueStatus(listener, gid, "dl")
        await listener.on_download_start()
        if listener.multi <= 1:
            await send_status_message(listener.message)
        await event.wait()
        if listener.is_cancelled:
            return

    status_helper = MegaPyStatusHelper(listener, gid)
    async with task_dict_lock:
        task_dict[listener.mid] = status_helper

    if added_to_queue:
        await listener.on_download_start()
    else:
        await listener.on_download_start()
        if listener.multi <= 1:
            await send_status_message(listener.message)

    if listener.is_cancelled:
        return

    try:
        # Phase 2: Perform file/folder payload download while task is registered in task_dict
        res = await sync_to_async(
            _mega_py_start_download,
            listener,
            path,
            info,
            status_helper,
        )
        if not res or listener.is_cancelled:
            return
        await listener.on_download_complete()
    except Exception as e:
        LOGGER.error(f"Mega.py download failed: {e}", exc_info=True)
        await listener.on_download_error(f"Mega download failed: {e}")


_ACTIVE_MEGA_LINKS = set()
_ACTIVE_MEGA_LINKS_LOCK = AsyncLock()

_MEGA_BASE64_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def _mega_base64_to_int(handle_str: str) -> int | None:
    if not handle_str:
        return None
    try:
        val = 0
        for c in handle_str:
            idx = _MEGA_BASE64_ALPHABET.find(c)
            if idx < 0:
                return None
            val = (val << 6) | idx
        return val & ((1 << 64) - 1)
    except Exception:
        return None


def _find_child_by_handle(api, parent_node, target_handle):
    if not parent_node or not target_handle:
        return None
    try:
        children = api.getChildren(parent_node)
        return _find_child_in_list(children, target_handle)
    except Exception as e:
        LOGGER.warning(f"_find_child_by_handle error: {e}")
    return None


def _find_child_in_list(children, target_handle):
    if not children:
        return None
    try:
        _to_handle = getattr(MegaApi, "base64ToHandle", None)
        target_int = _to_handle(target_handle) if callable(_to_handle) else None
    except Exception:
        target_int = None
    sz = _call_attr(children, "size", 0)
    for i in range(sz):
        child = _call_attr(children, "get", None, i)
        try:
            ch = _get_node_handle(child)
            ch_name = _get_node_name(child)
            if (
                ch == target_handle
                or (target_int is not None and ch == target_int)
                or ch_name == target_handle
            ):
                return child
        except Exception:
            pass
    return None


def _make_cancel_token():
    if MegaCancelToken is None:
        return None
    try:
        return MegaCancelToken.createInstance()
    except Exception as e:
        LOGGER.error(f"Mega: failed to create cancel token: {e}")
        return None


async def _reserve_link(link: str):
    async with _ACTIVE_MEGA_LINKS_LOCK:
        if link in _ACTIVE_MEGA_LINKS:
            return False
        _ACTIVE_MEGA_LINKS.add(link)
        return True


async def _release_link(link: str):
    async with _ACTIVE_MEGA_LINKS_LOCK:
        _ACTIVE_MEGA_LINKS.discard(link)


async def add_mega_download(listener, path):
    if Config.DISABLE_MEGA:
        await listener.on_download_error(
            "Mega Link downloads are currently disabled by the Bot Owner."
        )
        return

    user_dict = user_data.get(listener.user_id, {})
    mega_email = user_dict.get("MEGA_EMAIL") or Config.MEGA_EMAIL
    mega_password = user_dict.get("MEGA_PASSWORD") or Config.MEGA_PASSWORD

    if not await _reserve_link(listener.link):
        await listener.on_download_error(
            "This Mega link is already being downloaded! Wait for it to finish."
        )
        return

    if MegaApi is None:
        try:
            await _download_mega_py(listener, path, mega_email, mega_password)
        except Exception as e:
            await listener.on_download_error(f"Mega download failed: {e}")
        finally:
            await _release_link(listener.link)
        return

    async_api = None
    mega_base = ""
    sdk_failed = False
    try:
        sdk_gid = token_hex(5)
        await makedirs(path, exist_ok=True)
        mega_base = os.path.join(
            os.path.dirname(path.rstrip("/")), ".mega_sdk", sdk_gid
        )
        mega_dir = os.path.join(mega_base, "main")
        await makedirs(mega_dir, exist_ok=True)

        try:
            async_api = AsyncMega()
            async_api.api = api = MegaApi("", mega_dir, "WZML-X", 4)
        except Exception as e:
            LOGGER.warning(f"Failed to initialize MegaApi SDK: {e}. Falling back to Python downloader.")
            sdk_failed = True

        if sdk_failed or async_api is None or async_api.api is None:
            await _download_mega_py(listener, path, mega_email, mega_password)
            return
        mega_listener = MegaAppListener(async_api, listener)
        async_api._mega_listener = mega_listener
        api.addListener(mega_listener)
        api._listener_ref = mega_listener

        is_folder = is_mega_folder_link(listener.link)
        subfolder_handle = get_mega_subfolder_handle(listener.link)

        if is_folder:
            async_api.folder_api = folder_api = MegaApi("", mega_dir, "WZML-X", 4)

            # Authenticate folder API with the configured premium MEGA account.
            if mega_email and mega_password:
                LOGGER.info("Mega: authenticating premium account for folder download")
                await async_api.login(mega_email, mega_password)
                if listener.is_cancelled or async_api._mega_listener.is_cancelled:
                    return
                if async_api._mega_listener.error:
                    await listener.on_download_error(
                        _mega_error_format(async_api._mega_listener.error)
                    )
                    return

                account_auth = api.getAccountAuth()
                if not account_auth:
                    await listener.on_download_error(
                        "Failed to obtain MEGA account authentication."
                    )
                    return

                folder_api.setAccountAuth(account_auth)
                LOGGER.info("Mega: premium account auth applied to folder API")
                del account_auth

            folder_listener = MegaFolderListener(async_api, listener)
            async_api._folder_listener = folder_listener
            folder_api.addListener(folder_listener)
            folder_api._listener_ref = folder_listener
            dl_listener = folder_listener

            await async_api.loginToFolder(listener.link)
            if listener.is_cancelled or dl_listener.is_cancelled:
                return
            if dl_listener.error:
                await listener.on_download_error(_mega_error_format(dl_listener.error))
                return
            await async_api.fetchNodes(api=folder_api)
            await asleep(0)
            if listener.is_cancelled or dl_listener.is_cancelled:
                LOGGER.info("Mega: cancelled after fetchNodes")
                return
            if dl_listener.error:
                LOGGER.info("Mega: error after fetchNodes: %s", dl_listener.error)
                await listener.on_download_error(_mega_error_format(dl_listener.error))
                return
            if not dl_listener.node:
                LOGGER.info("Mega: no root node after fetchNodes")
                await listener.on_download_error(
                    "Failed to get root node for MEGA folder"
                )
                return
            if subfolder_handle:
                LOGGER.info("Mega: looking up subfolder handle=%s", subfolder_handle)
                target_int = _mega_base64_to_int(subfolder_handle)
                node = _find_child_in_list(dl_listener._children, subfolder_handle)
                if not node and target_int is not None:
                    try:
                        node = folder_api.getNodeByHandle(target_int)
                    except Exception as e:
                        LOGGER.error("Mega: getNodeByHandle failed: %s", e)
                if not node:
                    await listener.on_download_error(
                        "Subfolder not found in the MEGA link"
                    )
                    return
                dl_listener.node = node
                dl_listener._cache_node_data(node)
                LOGGER.info("Mega: subfolder name=%s", dl_listener._name)

                dl_listener._size = listener.size or _get_node_size(node, folder_api)
                if not dl_listener._size or dl_listener._size >= (1 << 62):
                    dl_listener._size = -1
                LOGGER.info("Mega: subfolder size=%s", dl_listener._size)
            else:
                node = dl_listener.node
        else:
            dl_listener = mega_listener
            if mega_email and mega_password:
                await async_api.login(mega_email, mega_password)
                if listener.is_cancelled or mega_listener.is_cancelled:
                    return
                if mega_listener.error:
                    await listener.on_download_error(
                        _mega_error_format(mega_listener.error)
                    )
                    return
                await async_api.fetchNodes()
                if listener.is_cancelled or mega_listener.is_cancelled:
                    return
                if mega_listener.error:
                    await listener.on_download_error(
                        _mega_error_format(mega_listener.error)
                    )
                    return
            await async_api.getPublicNode(listener.link)
            if listener.is_cancelled or mega_listener.is_cancelled:
                return
            if mega_listener.error:
                LOGGER.error("Mega getPublicNode error for link %s: %s", listener.link, mega_listener.error)
                await listener.on_download_error(_mega_error_format(mega_listener.error))
                return
            node = mega_listener.public_node
            if not node:
                LOGGER.error("Mega: Failed to resolve public node for link: %s", listener.link)
                await listener.on_download_error("Failed to resolve MEGA link")
                return

        listener.name = (
            listener.name or dl_listener._name or f"MEGA_Download_{token_hex(5)}"
        )
        listener.size = dl_listener._size if dl_listener._size < (1 << 62) else -1
        if listener.size <= 0 and node:
            s = _get_node_size(node)
            listener.size = s if s < (1 << 62) else -1
        gid = token_hex(5)
        msg, button = await stop_duplicate_check(listener)
        if msg:
            await listener.on_download_error(msg, button)
            return

        if limit_exceeded := await limit_checker(listener):
            await listener.on_download_error(limit_exceeded, is_limit=True)
            return

        added_to_queue, event = await check_running_tasks(listener)
        if added_to_queue:
            async with task_dict_lock:
                task_dict[listener.mid] = QueueStatus(listener, gid, "dl")
            await listener.on_download_start()
            if listener.multi <= 1:
                await send_status_message(listener.message)
            await event.wait()
            if listener.is_cancelled:
                return

        async with task_dict_lock:
            task_dict[listener.mid] = MegaDownloadStatus(
                listener, dl_listener, gid, "dl"
            )

        if added_to_queue:
            await listener.on_download_start()
        else:
            await listener.on_download_start()
            if listener.multi <= 1:
                await send_status_message(listener.message)

        if listener.is_cancelled or dl_listener.is_cancelled:
            return
        download_path = path
        if is_mega_folder_link(listener.link):
            download_path = os.path.join(path, listener.name)
            await makedirs(download_path, exist_ok=True)

        for attempt in range(5):
            cancel_token = _make_cancel_token()
            dl_listener._cancel_token = cancel_token
            dl_listener.error = None
            dl_listener.retryable_error = None
            dl_listener.is_session_expired = False
            dl_listener._bytes_transferred = 0
            dl_listener._total_downloaded_bytes = 0
            dl_listener._caller_manages_completion = False

            await async_api.startDownload(
                node,
                download_path,
                listener.name,
                None,
                False,
                cancel_token,
                3,
                2,
                False,
            )
            await async_api.wait_for_transfer()

            if listener.is_cancelled or dl_listener.is_cancelled:
                LOGGER.info("MegaDownload: transfer cancelled during attempt %s", attempt + 1)
                return

            if getattr(dl_listener, "is_session_expired", False):
                LOGGER.warning("MegaDownload: session expired during download attempt %s, falling back to python downloader", attempt + 1)
                await _download_mega_py(listener, path, mega_email, mega_password)
                return

            if dl_listener.error and not dl_listener.retryable_error:
                LOGGER.error(
                    "MegaDownload: fatal error during download: %s",
                    dl_listener.error,
                )
                await listener.on_download_error(
                    _mega_error_format(dl_listener.error)
                )
                return

            if not dl_listener.retryable_error:
                LOGGER.info(
                    "MegaDownload: completed transfer successfully for %s",
                    listener.name,
                )
                return

            if dl_listener.retryable_error.startswith("-13"):
                local_size = 0
                if os.path.isdir(download_path):
                    for root, dirs, files in os.walk(download_path):
                        for filename in files:
                            try:
                                local_size += os.path.getsize(os.path.join(root, filename))
                            except OSError:
                                pass
                elif os.path.isfile(download_path):
                    try:
                        local_size = os.path.getsize(download_path)
                    except OSError:
                        pass

                expected_size = dl_listener._total_folder_size or dl_listener._size

                LOGGER.warning(
                    "MegaDownload: API_EINCOMPLETE local_size=%s expected_size=%s transferred=%s",
                    local_size,
                    expected_size,
                    dl_listener.downloaded_bytes,
                )

                if expected_size > 0:
                    missing = expected_size - local_size
                    tolerance = max(2 * 1024 * 1024, int(expected_size * 0.001))
                    LOGGER.warning(
                        "MegaDownload: API_EINCOMPLETE missing=%s tolerance=%s",
                        missing,
                        tolerance,
                    )
                    if missing <= tolerance:
                        LOGGER.warning(
                            "MegaDownload: treating API_EINCOMPLETE as complete; local data is within tolerance"
                        )
                        dl_listener.retryable_error = None
                        await listener.on_download_complete()
                        return

            if attempt >= 4:
                LOGGER.error(
                    "MegaDownload: transfer incomplete after 5 attempts: %s",
                    dl_listener.retryable_error,
                )
                await listener.on_download_error(
                    _mega_error_format(dl_listener.retryable_error)
                )
                return

            LOGGER.warning(
                "MegaDownload: transfer incomplete, retrying attempt %s/5: %s",
                attempt + 2,
                dl_listener.retryable_error,
            )
            await clean_download(download_path)
            await asleep(2**attempt)

    except Exception as e:
        LOGGER.error(f"Unexpected error in add_mega_download: {e}", exc_info=True)
        if not listener.is_cancelled:
            await listener.on_download_error(f"Internal error: {e}")
    finally:
        if async_api is not None:
            if not is_folder:
                async with _MEGA_SDK_LOCK:
                    with suppress(Exception):
                        await async_api.logout()
                    if (
                        async_api.api is not None
                        and async_api._mega_listener is not None
                    ):
                        with suppress(Exception):
                            async_api.api.removeListener(async_api._mega_listener)
                    if (
                        async_api.folder_api is not None
                        and async_api._folder_listener is not None
                    ):
                        with suppress(Exception):
                            async_api.folder_api.removeListener(
                                async_api._folder_listener
                            )
        await _release_link(listener.link)
        await clean_download(mega_base)
