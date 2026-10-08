from asyncio import sleep, gather
from random import choice
from re import match as re_match
from time import time

from pyrogram.types import Message, InputMediaPhoto, ReplyParameters
from pyrogram.enums import ButtonStyle, ParseMode
from pyrogram.errors import (
    FloodWait,
    MessageNotModified,
    MessageEmpty,
    MessageTooLong,
    MessageDeleteForbidden,
    ReplyMarkupInvalid,
    PhotoInvalidDimensions,
    WebpageCurlFailed,
    WebpageMediaEmpty,
    MediaEmpty,
    MediaCaptionTooLong,
    EntityBoundsInvalid,
    PeerIdInvalid,
)

try:
    from pyrogram.errors import FloodPremiumWait
except ImportError:
    FloodPremiumWait = FloodWait

from ... import (
    LOGGER,
    bot_cache,
    categories_dict,
    intervals,
    status_dict,
    task_dict_lock,
    user_data,
)
from ...core.config_manager import Config
from ...core.tg_client import TgClient
from ..ext_utils.bot_utils import SetInterval, download_image_url, fetch_drive_cat
from ..ext_utils.exceptions import TgLinkException
from ..ext_utils.status_utils import get_readable_message
from .button_build import ButtonMaker


async def send_message(message, text, buttons=None, block=True, photo=None, **kwargs):
    img_photo = choice(Config.IMAGES) if (photo == "IMAGES" and Config.USE_IMAGES and Config.IMAGES) else (None if photo == "IMAGES" else photo)
    try:
        if img_photo:
            try:
                if isinstance(message, Message):
                    return await message.reply_photo(
                        photo=img_photo,
                        caption=text,
                        reply_parameters=ReplyParameters(message_id=message.id),
                        reply_markup=buttons,
                        disable_notification=True,
                        **kwargs,
                    )
                return await TgClient.bot.send_photo(
                    chat_id=message,
                    photo=img_photo,
                    caption=text,
                    reply_markup=buttons,
                    disable_notification=True,
                    **kwargs,
                )
            except FloodWait as f:
                LOGGER.warning(str(f))
                if not block:
                    return str(f)
                await sleep(f.value * 1.2)
                return await send_message(message, text, buttons, block, photo)
            except MediaCaptionTooLong:
                return await send_message(
                    message,
                    text[:1024],
                    buttons,
                    block,
                    photo,
                )
            except (
                PhotoInvalidDimensions,
                WebpageCurlFailed,
                WebpageMediaEmpty,
                MediaEmpty,
            ):
                try:
                    des_dir = await download_image_url(img_photo)
                    if des_dir:
                        msg = await send_message(message, text, buttons, block, des_dir)
                        from aiofiles.os import remove as aioremove

                        await aioremove(des_dir)
                        return msg
                except Exception:
                    LOGGER.error("Failed to send fallback photo", exc_info=True)
                return
            except Exception:
                LOGGER.error("Error while sending photo", exc_info=True)
                return
        if not isinstance(text, str):
            text = str(text)

        if isinstance(message, Message):
            return await message.reply(
                text=text,
                reply_parameters=ReplyParameters(message_id=message.id),
                disable_web_page_preview=True,
                disable_notification=True,
                reply_markup=buttons,
                **kwargs,
            )
        return await TgClient.bot.send_message(
            chat_id=int(message),
            text=text,
            disable_web_page_preview=True,
            disable_notification=True,
            reply_markup=buttons,
        )
    except FloodWait as f:
        LOGGER.warning(str(f))
        if not block:
            return str(f)
        await sleep(f.value * 1.2)
        return await send_message(message, text, buttons)
    except ReplyMarkupInvalid as rmi:
        LOGGER.warning(str(rmi))
        return await send_message(message, text, None)
    except MessageTooLong:
        return await send_message(message, text[:4096], buttons, block, photo)
    except (MessageEmpty, EntityBoundsInvalid):
        return await send_message(message, text, parse_mode=ParseMode.DISABLED)
    except PeerIdInvalid:
        LOGGER.warning(f"PeerIdInvalid {type(message)}")
        if isinstance(message, (int, str)):
            return await send_message(int(message), text, buttons, block, photo)
    except ConnectionError:
        return
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def edit_message(message, text, buttons=None, block=True, photo=None):
    img_photo = choice(Config.IMAGES) if (photo == "IMAGES" and Config.USE_IMAGES and Config.IMAGES) else (None if photo == "IMAGES" else photo)
    try:
        if not isinstance(text, str):
            text = str(text)
        if message.media:
            caption_text = text[:1020] + "..." if len(text) > 1024 else text
            if img_photo:
                try:
                    return await message.edit_media(
                        InputMediaPhoto(img_photo, caption_text), reply_markup=buttons
                    )
                except (
                    PhotoInvalidDimensions,
                    WebpageCurlFailed,
                    WebpageMediaEmpty,
                    MediaEmpty,
                ):
                    des_dir = await download_image_url(img_photo)
                    if des_dir:
                        msg = await message.edit_media(
                            InputMediaPhoto(des_dir, caption_text), reply_markup=buttons
                        )
                        from aiofiles.os import remove as aioremove

                        await aioremove(des_dir)
                        return msg
                    return await message.edit_caption(
                        caption=caption_text, reply_markup=buttons
                    )
            return await message.edit_caption(caption=caption_text, reply_markup=buttons)

        msg_text = text[:4090] + "..." if len(text) > 4096 else text
        return await message.edit(
            text=msg_text,
            disable_web_page_preview=True,
            reply_markup=buttons,
        )
    except (MessageNotModified, MessageEmpty):
        pass
    except ReplyMarkupInvalid as rmi:
        LOGGER.warning(str(rmi))
        return await edit_message(message, text, None, block, photo)
    except FloodWait as f:
        LOGGER.warning(str(f))
        if not block:
            return str(f)
        await sleep(f.value * 1.2)
        return await edit_message(message, text, buttons, block, photo)
    except OSError:
        return
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def edit_reply_markup(message, buttons):
    try:
        return await message.edit_reply_markup(reply_markup=buttons)
    except MessageNotModified:
        pass
    except FloodWait as f:
        LOGGER.warning(str(f))
        await sleep(f.value * 1.2)
        return await edit_reply_markup(message, buttons)
    except OSError:
        return
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def send_file(message, file, caption="", buttons=None):
    try:
        return await message.reply_document(
            document=file,
            reply_parameters=ReplyParameters(message_id=message.id),
            caption=caption,
            disable_notification=True,
            reply_markup=buttons,
        )
    except FloodWait as f:
        LOGGER.warning(str(f))
        await sleep(f.value * 1.2)
        return await send_file(message, file, caption)
    except ConnectionError:
        return
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def send_rss(text, chat_id, thread_id):
    try:
        return await TgClient.bot.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=True,
            message_thread_id=thread_id,
            disable_notification=True,
        )
    except (FloodWait, FloodPremiumWait) as f:
        LOGGER.warning(str(f))
        await sleep(f.value * 1.2)
        return await send_rss(text, chat_id, thread_id)
    except ConnectionError:
        return
    except Exception as e:
        LOGGER.error(str(e), exc_info=True)
        return str(e)


async def delete_message(*args):
    tasks = [msg.delete() for msg in args if isinstance(msg, Message)]
    if not tasks:
        return
    results = await gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, MessageDeleteForbidden):
            pass
        elif isinstance(result, Exception):
            LOGGER.error(result)


async def delete_links(message):
    if Config.DELETE_LINKS:
        await delete_message(message, message.reply_to_message)


async def auto_delete_message(*args, stime=90):
    await sleep(stime)
    await delete_message(*args)


async def delete_status():
    async with task_dict_lock:
        for key, data in list(status_dict.items()):
            try:
                await delete_message(data["message"])
                del status_dict[key]
            except Exception as e:
                LOGGER.error(str(e))


def _parse_single_tg_link(link: str):
    if link.startswith(
        (
            "https://t.me/",
            "https://telegram.me/",
            "https://telegram.dog/",
            "https://telegram.space/",
        )
    ):
        private = False
        msg = re_match(
            r"https:\/\/(t\.me|telegram\.me|telegram\.dog|telegram\.space)\/(?:c\/)?([^\/]+)(?:\/[^\/]+)?\/([0-9-]+)",
            link,
        )
    else:
        private = True
        msg = re_match(
            r"tg:\/\/(openmessage)\?user_id=([0-9]+)&message_id=([0-9-]+)", link
        )

    if not msg:
        raise TgLinkException(f"Invalid Telegram link: {link}")

    chat = msg[2]
    msg_id = msg[3]

    if "-" in msg_id:
        parts = msg_id.split("-")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            start_id, end_id = int(parts[0]), int(parts[1])
            if start_id <= end_id:
                msg_ids = list(range(start_id, end_id + 1))
            else:
                msg_ids = list(range(start_id, end_id - 1, -1))
        else:
            raise TgLinkException(f"Invalid Telegram range link: {link}")
    else:
        if msg_id.isdigit():
            msg_ids = int(msg_id)
        else:
            raise TgLinkException(f"Invalid Telegram message ID in link: {link}")

    if chat.isdigit():
        chat = int(chat) if private else int(f"-100{chat}")

    return chat, msg_ids, private


def parse_tg_link(link: str):
    from re import findall as re_findall
    link = link.strip()
    urls = re_findall(
        r"(?:https?:\/\/(?:t\.me|telegram\.me|telegram\.dog|telegram\.space)\/(?:c\/)?[^\/\s]+\/(?:[^\/\s]+\/)?[0-9]+|tg:\/\/openmessage\?[^\s]+)",
        link,
    )
    if len(urls) >= 2:
        chat1, id1, priv1 = _parse_single_tg_link(urls[0])
        chat2, id2, priv2 = _parse_single_tg_link(urls[1])
        if chat1 != chat2:
            raise TgLinkException("Chat ID mismatch in range links!")
        start_id = id1[0] if isinstance(id1, list) else id1
        end_id = id2[0] if isinstance(id2, list) else id2
        if start_id <= end_id:
            msg_ids = list(range(start_id, end_id + 1))
        else:
            msg_ids = list(range(start_id, end_id - 1, -1))
        return chat1, msg_ids, priv1 or priv2

    return _parse_single_tg_link(link)


async def get_tg_link_message(link, range_mode="normal", user_id=None, user_dict=None):
    chat, msg_ids, private = parse_tg_link(link)

    # Prefer the requesting user's configured personal session.  This is
    # intentionally independent of the global OWNER/USER_SESSION_STRING so
    # one user's private Telegram access cannot be reused by another user.
    personal_user = None
    if user_id is not None:
        try:
            from ... import user_data
            uid = int(user_id)
            data = user_dict if isinstance(user_dict, dict) else user_data.get(uid, {})
            session_string = data.get("TELEGRAM_SESSION_STRING") if data else None
            if session_string:
                personal_user = await TgClient.get_personal_user(uid, session_string)
                if personal_user:
                    LOGGER.info(f"Using personal Telegram session for user {uid} to resolve {link}")
        except Exception as e:
            LOGGER.warning(f"Failed to initialize personal Telegram session for user {user_id}: {e}")

    session_user = personal_user or TgClient.user
    if private and not session_user:
        raise TgLinkException(
            "🔐 Private Telegram link requires your configured session string. "
            "Open Settings → Telegram Session and set a valid session string."
        )

    is_range = isinstance(msg_ids, list)

    if is_range and range_mode == "each":
        links_list = []
        for mid in msg_ids:
            if private or (isinstance(chat, int) and str(chat).startswith("-100")):
                cid = str(chat)[4:] if str(chat).startswith("-100") else str(chat)
                links_list.append(f"https://t.me/c/{cid}/{mid}")
            else:
                links_list.append(f"https://t.me/{chat}/{mid}")
        return links_list, "bot"

    if not private:
        try:
            messages = await TgClient.bot.get_messages(chat_id=chat, message_ids=msg_ids)
            if is_range:
                if not isinstance(messages, list):
                    messages = [messages]
                valid_msgs = [m for m in messages if m and not getattr(m, "empty", False)]
                if valid_msgs:
                    return valid_msgs, "bot"
                private = True
            else:
                if messages and not getattr(messages, "empty", False):
                    return messages, "bot"
                private = True
        except Exception as e:
            private = True
            if not session_user:
                raise e

    if session_user:
        try:
            user_messages = await session_user.get_messages(chat_id=chat, message_ids=msg_ids)
            if is_range:
                if not isinstance(user_messages, list):
                    user_messages = [user_messages]
                valid_msgs = [m for m in user_messages if m and not getattr(m, "empty", False)]
                if valid_msgs:
                    return valid_msgs, "user"
                raise TgLinkException("No valid messages found in the specified range!")
            else:
                if user_messages and not getattr(user_messages, "empty", False):
                    return user_messages, "user"
                raise TgLinkException("Message not found or empty!")
        except Exception as e:
            raise TgLinkException(
                f"🔒 You do not have access to this Telegram chat/message. ERROR: {e}"
            ) from e
    else:
        raise TgLinkException(
            "🔒 Unable to access this Telegram message. Check that your configured session "
            "belongs to an account that can access the chat/message, then try again."
        )


async def update_status_message(sid, force=False):
    if intervals["stopAll"]:
        return
    async with task_dict_lock:
        if not status_dict.get(sid):
            if obj := intervals["status"].get(sid):
                obj.cancel()
                del intervals["status"][sid]
            return
        if not force and time() - status_dict[sid]["time"] < 3:
            return
        status_dict[sid]["time"] = time()
        page_no = status_dict[sid]["page_no"]
        status = status_dict[sid]["status"]
        is_user = status_dict[sid]["is_user"]
        page_step = status_dict[sid]["page_step"]
        text, buttons = await get_readable_message(
            sid, is_user, page_no, status, page_step
        )
        if text is None:
            del status_dict[sid]
            if obj := intervals["status"].get(sid):
                obj.cancel()
                del intervals["status"][sid]
            return
        if text != status_dict[sid]["message"].text:
            message = await edit_message(
                status_dict[sid]["message"], text, buttons, block=False, photo="IMAGES"
            )
            if isinstance(message, str):
                if message.startswith("Telegram says: [40"):
                    del status_dict[sid]
                    if obj := intervals["status"].get(sid):
                        obj.cancel()
                        del intervals["status"][sid]
                else:
                    LOGGER.error(
                        f"Status with id: {sid} haven't been updated. Error: {message}"
                    )
                return
            status_dict[sid]["message"].text = text
            status_dict[sid]["time"] = time()


async def send_status_message(msg, user_id=0, force_new=False):
    if intervals["stopAll"]:
        return
    sid = user_id or msg.chat.id
    is_user = bool(user_id)
    async with task_dict_lock:
        if sid in status_dict:
            page_no = status_dict[sid]["page_no"]
            status = status_dict[sid]["status"]
            page_step = status_dict[sid]["page_step"]
            text, buttons = await get_readable_message(
                sid, is_user, page_no, status, page_step
            )
            if text is None:
                del status_dict[sid]
                if obj := intervals["status"].get(sid):
                    obj.cancel()
                    del intervals["status"][sid]
                return

            if not force_new and status_dict[sid].get("message"):
                edited = await edit_message(
                    status_dict[sid]["message"], text, buttons, block=False, photo="IMAGES"
                )
                if not isinstance(edited, str):
                    status_dict[sid]["message"].text = text
                    status_dict[sid]["time"] = time()
                    return

            old_message = status_dict[sid]["message"]
            message = await send_message(
                msg, text, buttons, block=False, photo="IMAGES"
            )
            if isinstance(message, str):
                LOGGER.error(
                    f"Status with id: {sid} haven't been sent. Error: {message}"
                )
                return
            await delete_message(old_message)
            message.text = text
            status_dict[sid].update({"message": message, "time": time()})
        else:
            text, buttons = await get_readable_message(sid, is_user)
            if text is None:
                return
            message = await send_message(
                msg, text, buttons, block=False, photo="IMAGES"
            )
            if isinstance(message, str):
                LOGGER.error(
                    f"Status with id: {sid} haven't been sent. Error: {message}"
                )
                return
            message.text = text
            status_dict[sid] = {
                "message": message,
                "time": time(),
                "page_no": 1,
                "page_step": 1,
                "status": "All",
                "is_user": is_user,
            }
        if not intervals["status"].get(sid) and not is_user:
            intervals["status"][sid] = SetInterval(
                Config.STATUS_UPDATE_INTERVAL, update_status_message, sid
            )


async def open_category_btns(message):
    user_id = message.from_user.id
    msg_id = message.id
    buttons = ButtonMaker()
    cat_name = None
    dcats = fetch_drive_cat(user_id)
    default_id = user_data.get(user_id, {}).get("GDRIVE_ID") or Config.GDRIVE_ID
    default_index = user_data.get(user_id, {}).get("INDEX_URL") or Config.INDEX_URL
    merged = {
        "Default": {"drive_id": default_id, "index_link": default_index},
        **dcats,
        **categories_dict,
    }
    for i, name in enumerate(merged):
        if i == 0:
            cat_name = name
        buttons.data_button(
            f"{'✓' if i == 0 else ''} {name}",
            f"scat {user_id} {msg_id} {name.replace(' ', '_')}",
        )
    buttons.data_button(
        "Cancel", f"scat {user_id} {msg_id} scancel", "footer", style=ButtonStyle.DANGER
    )
    buttons.data_button(
        "Done (60)",
        f"scat {user_id} {msg_id} sdone",
        "footer",
        style=ButtonStyle.SUCCESS,
    )
    prompt = await send_message(
        message,
        f"<b>📁 Select Upload Category</b>\n\n"
        f"<blockquote>• <b>Upload Category:</b> <code>{cat_name or 'None'}</code>\n"
        f"• <b>Timeout:</b> 60 sec</blockquote>",
        buttons.build_menu(3),
    )
    start_time = time()
    bot_cache[msg_id] = [None, None, False, False, start_time]
    while time() - start_time <= 60:
        await sleep(0.5)
        if bot_cache[msg_id][2] or bot_cache[msg_id][3]:
            break
    drive_id, index_link, _, is_cancelled, __ = bot_cache[msg_id]
    if not is_cancelled:
        await delete_message(prompt)
    else:
        await edit_message(prompt, "<b>Task Cancelled</b>")
    del bot_cache[msg_id]
    return drive_id, index_link, is_cancelled


async def open_drive_clean(message):
    user_id = message.from_user.id
    msg_id = message.id
    buttons = ButtonMaker()
    dcats = fetch_drive_cat(user_id)
    default_id = user_data.get(user_id, {}).get("GDRIVE_ID") or Config.GDRIVE_ID
    default_index = user_data.get(user_id, {}).get("INDEX_URL") or Config.INDEX_URL
    merged = {
        "Default": {"drive_id": default_id, "index_link": default_index},
        **dcats,
        **categories_dict,
    }
    first_cat = None
    for i, name in enumerate(merged):
        if i == 0:
            first_cat = name
        buttons.data_button(
            f"{'✓' if i == 0 else ''} {name}",
            f"gdccat {user_id} {msg_id} {name.replace(' ', '_')}",
        )
    buttons.data_button(
        "Cancel",
        f"gdccat {user_id} {msg_id} ccancel",
        position="footer",
        style=ButtonStyle.DANGER,
    )
    prompt = await send_message(
        message,
        f"<b>🧹 Select Drive Category to Clean</b>\n\n"
        f"<blockquote>• <b>Category:</b> <code>{first_cat or 'None'}</code>\n"
        f"• <b>Timeout:</b> 60 sec</blockquote>",
        buttons.build_menu(3),
    )
    start_time = time()
    bot_cache[msg_id] = [None, False, False, start_time, None]
    while time() - start_time <= 60:
        await sleep(0.5)
        if bot_cache[msg_id][1] or bot_cache[msg_id][2]:
            break
    drive_id = bot_cache[msg_id][0]
    is_cancelled = bot_cache[msg_id][1]
    cat_name = bot_cache[msg_id][4]
    if not is_cancelled:
        await delete_message(prompt)
    else:
        await edit_message(prompt, "<b>Task Cancelled</b>")
    del bot_cache[msg_id]
    return drive_id, is_cancelled, cat_name


async def open_dump_chat_btns(message, dump_chats, invalid_name=None):
    user_id = message.from_user.id
    msg_id = message.id
    cache_key = f"sdump_{msg_id}"
    buttons = ButtonMaker()
    dump_names = list(dump_chats)
    selected_name = dump_names[0] if dump_names else None
    for i, name in enumerate(dump_names):
        buttons.data_button(
            f"{'✓' if i == 0 else ''} {name}",
            f"sdump {user_id} {msg_id} {i}",
        )
    buttons.data_button(
        "Cancel",
        f"sdump {user_id} {msg_id} scancel",
        "footer",
        style=ButtonStyle.DANGER,
    )
    buttons.data_button(
        "Done (60)",
        f"sdump {user_id} {msg_id} sdone",
        "footer",
        style=ButtonStyle.SUCCESS,
    )
    invalid_hint = (
        f"\n\n<b>Unknown dump:</b> <code>{invalid_name}</code>" if invalid_name else ""
    )
    prompt = await send_message(
        message,
        f"<b>💬 Select Dump Chat Destination</b>{invalid_hint}\n\n"
        f"<blockquote>• <b>Dump Chat:</b> <code>{selected_name or 'None'}</code>\n"
        f"• <b>Timeout:</b> 60 sec</blockquote>",
        buttons.build_menu(3),
    )
    start_time = time()
    bot_cache[cache_key] = [dump_chats.get(selected_name), False, False, start_time]
    while time() - start_time <= 60:
        await sleep(0.5)
        if bot_cache[cache_key][1] or bot_cache[cache_key][2]:
            break
    up_dest, _, is_cancelled, __ = bot_cache[cache_key]
    if not is_cancelled:
        await delete_message(prompt)
    else:
        await edit_message(prompt, "<b>Task Cancelled</b>")
    del bot_cache[cache_key]
    return up_dest, is_cancelled
