import json
from contextlib import suppress

from aiofiles import open as aiopen
from aiofiles.os import remove, path as aiopath

from ... import LOGGER, active_range_tasks, bot_loop

RANGE_STORE_FILE = "range_tasks.json"


async def save_range_tasks_to_file():
    try:
        data = []
        for range_id, rt in list(active_range_tasks.items()):
            if rt.get("is_cancelled"):
                continue
            listener_dict = rt.get("listener_dict")
            if not listener_dict:
                continue
            data.append(
                {
                    "range_id": range_id,
                    "mid": rt.get("mid"),
                    "user_id": rt.get("user_id"),
                    "tag": rt.get("tag"),
                    "total_links": rt.get("total_links"),
                    "current_idx": rt.get("current_idx", 1),
                    "links": rt.get("links", []),
                    "listener_dict": listener_dict,
                }
            )
        if data:
            async with aiopen(RANGE_STORE_FILE, "w") as f:
                await f.write(json.dumps(data, indent=2))
        else:
            if await aiopath.exists(RANGE_STORE_FILE):
                await remove(RANGE_STORE_FILE)
    except Exception as e:
        LOGGER.error(f"Error saving range tasks to file: {e}")


async def load_range_tasks_from_file():
    if not await aiopath.exists(RANGE_STORE_FILE):
        return []
    try:
        async with aiopen(RANGE_STORE_FILE, "r") as f:
            content = await f.read()
            if not content.strip():
                return []
            return json.loads(content)
    except Exception as e:
        LOGGER.error(f"Error loading range tasks from file: {e}")
        return []


async def resume_range_tasks_on_startup():
    saved_tasks = await load_range_tasks_from_file()
    if not saved_tasks:
        return

    from ...core.tg_client import TgClient
    from ...modules.mirror_leech import Mirror

    LOGGER.info(f"Found {len(saved_tasks)} range link task(s) to auto-resume.")

    for r_data in saved_tasks:
        range_id = r_data.get("range_id")
        current_idx = r_data.get("current_idx", 1)
        total_links = r_data.get("total_links", 1)
        links = r_data.get("links", [])
        listener_dict = r_data.get("listener_dict", {})

        if not range_id or not links or current_idx > total_links:
            continue

        chat_id = listener_dict.get("chat_id")
        message_id = listener_dict.get("message_id")

        msg = None
        if chat_id and message_id:
            with suppress(Exception):
                msg = await TgClient.bot.get_messages(chat_id, message_id)

        if not msg:

            class DummyUser:
                def __init__(self, u_id):
                    self.id = u_id or 0

                def mention(self, style=None):
                    return f"User {self.id}"

            class DummyChat:
                def __init__(self, c_id):
                    self.id = c_id or 0

            class DummyMessage:
                def __init__(self, c_id, m_id, u_id):
                    self.id = m_id or 0
                    self.chat = DummyChat(c_id)
                    self.from_user = DummyUser(u_id)
                    self.sender_chat = None
                    self.text = ""
                    self.reply_to_message = None

            msg = DummyMessage(chat_id, message_id, listener_dict.get("user_id"))

        mirror_inst = Mirror(
            client=TgClient.bot,
            message=msg,
            is_qbit=listener_dict.get("is_qbit", False),
            is_leech=listener_dict.get("is_leech", False),
            is_jd=listener_dict.get("is_jd", False),
            is_nzb=listener_dict.get("is_nzb", False),
            is_seedr=listener_dict.get("is_seedr", False),
            is_uphoster=listener_dict.get("is_uphoster", False),
            options=listener_dict.get("options", {}),
        )

        for k, v in listener_dict.items():
            if k not in ("chat_id", "message_id", "raw_message"):
                setattr(mirror_inst, k, v)

        r_data["listener_dict"] = listener_dict
        bot_loop.create_task(mirror_inst.resume_range_task(r_data))
