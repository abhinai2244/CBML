from asyncio import wait_for, get_running_loop
from html import escape
from pyrogram.enums import ChatType, ButtonStyle
from pyrogram.filters import command, regex, create
from pyrogram.handlers import MessageHandler, CallbackQueryHandler

from bot import (
    LOGGER,
    bot_loop,
    non_queued_dl,
    non_queued_up,
    queue_dict_lock,
    queued_dl,
    queued_up,
    task_dict,
    task_dict_lock,
    user_data,
)
from bot.core.config_manager import Config
from bot.core.tg_client import TgClient
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.ext_utils.bot_utils import new_task, safe_int, update_user_ldata
from bot.helper.ext_utils.db_handler import database
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)


def _get_task_details(user_id):
    running_list = []
    queued_list = []

    for mid, tk in list(task_dict.items()):
        listener = getattr(tk, "listener", None)
        if listener and listener.user_id == user_id:
            name = escape(tk.name() if callable(getattr(tk, "name", None)) else str(getattr(tk, "name", "Task")))
            gid = tk.gid() if callable(getattr(tk, "gid", None)) else str(mid)
            if mid in non_queued_dl or mid in non_queued_up:
                mode = "DL" if mid in non_queued_dl else "UP"
                running_list.append((mid, gid, name, mode))

    pos = 1
    for mid in list(queued_dl.keys()):
        tk = task_dict.get(mid)
        listener = getattr(tk, "listener", None) if tk else None
        if listener and listener.user_id == user_id:
            name = escape(tk.name() if callable(getattr(tk, "name", None)) else str(getattr(tk, "name", "Task")))
            gid = tk.gid() if callable(getattr(tk, "gid", None)) else str(mid)
            queued_list.append((pos, mid, gid, name, "Queued DL"))
        pos += 1

    pos_up = 1
    for mid in list(queued_up.keys()):
        tk = task_dict.get(mid)
        listener = getattr(tk, "listener", None) if tk else None
        if listener and listener.user_id == user_id:
            name = escape(tk.name() if callable(getattr(tk, "name", None)) else str(getattr(tk, "name", "Task")))
            gid = tk.gid() if callable(getattr(tk, "gid", None)) else str(mid)
            queued_list.append((pos_up, mid, gid, name, "Queued UP"))
        pos_up += 1

    return running_list, queued_list


def build_taskm_view(user_id, from_user):
    user_name = from_user.mention(style="html")
    user_dict = user_data.get(user_id, {})
    user_limit = safe_int(user_dict.get("maxtask", Config.USER_MAX_TASKS))

    limit_str = f"<b>{user_limit}</b>" if user_limit > 0 else "<b>Unlimited (0)</b>"

    running_list, queued_list = _get_task_details(user_id)

    text = "<b>📊 Task Manager & Queue Controller (/taskm)</b>\n\n"
    text += f"<blockquote>• <b>Authorized User:</b> {user_name}\n"
    text += f"• <b>Configured Task Limit:</b> {limit_str}\n"
    text += f"• <b>Running Tasks:</b> <code>{len(running_list)}</code>\n"
    text += f"• <b>Queued Tasks:</b> <code>{len(queued_list)}</code></blockquote>\n\n"

    if running_list:
        text += "<b>▶️ Current Running Tasks:</b>\n"
        for idx, (mid, gid, name, mode) in enumerate(running_list, start=1):
            text += f"{idx}. [<code>{mode}</code>] <code>{name}</code> (<code>#{gid[:8]}</code>)\n"
        text += "\n"
    else:
        text += "<b>▶️ Current Running Tasks:</b> <i>None</i>\n\n"

    if queued_list:
        text += "<b>⏳ Current Queued Tasks & Status:</b>\n"
        for pos, mid, gid, name, st_label in queued_list:
            text += f"• <b>Queue #{pos}:</b> [<code>{st_label}</code>] <code>{name}</code> (<code>#{gid[:8]}</code>)\n"
        text += "\n"
    else:
        text += "<b>⏳ Current Queued Tasks & Status:</b> <i>None</i>\n\n"

    text += "<i>Use buttons below or send <code>/taskm &lt;limit&gt;</code> to set maximum simultaneous tasks.</i>"

    buttons = ButtonMaker()
    buttons.data_button("1", f"taskm set {user_id} 1")
    buttons.data_button("2", f"taskm set {user_id} 2")
    buttons.data_button("3", f"taskm set {user_id} 3")
    buttons.data_button("5", f"taskm set {user_id} 5")
    buttons.data_button("10", f"taskm set {user_id} 10")
    buttons.data_button("∞ Unlimited", f"taskm set {user_id} 0")

    buttons.data_button("✏️ Custom Input", f"taskm custom {user_id}", position="header")
    buttons.data_button("♻️ Refresh", f"taskm ref {user_id}", position="header")
    buttons.data_button("❌ Close", "taskm close", position="footer", style=ButtonStyle.DANGER)

    return text, buttons.build_menu(3)


@new_task
async def taskm_command(client, message):
    if message.chat.type != ChatType.PRIVATE:
        await send_message(
            message,
            "<blockquote>The <code>/taskm</code> command works ONLY in Direct Messages (DM)!</blockquote>",
        )
        return

    user_id = message.from_user.id if message.from_user else 0
    sudo_users = getattr(Config, "SUDO_USERS", [])
    if isinstance(sudo_users, str):
        sudo_users = [int(x.strip()) for x in sudo_users.split(",") if x.strip().isdigit()]

    if user_id != Config.OWNER_ID and user_id not in sudo_users:
        await send_message(
            message,
            "<blockquote>The <code>/taskm</code> command is restricted to Owner and Sudo users only!</blockquote>",
        )
        return

    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].strip().isdigit():
        new_val = safe_int(args[1].strip())
        update_user_ldata(user_id, "maxtask", new_val)
        await database.update_user_data(user_id)
        from bot.helper.ext_utils.task_manager import start_from_queued
        await start_from_queued()

    text, buttons = build_taskm_view(user_id, message.from_user)
    await send_message(message, text, buttons)


@new_task
async def taskm_callback(client, query):
    user_id = query.from_user.id
    data = query.data.split()
    action = data[1]

    sudo_users = getattr(Config, "SUDO_USERS", [])
    if isinstance(sudo_users, str):
        sudo_users = [int(x.strip()) for x in sudo_users.split(",") if x.strip().isdigit()]

    if user_id != Config.OWNER_ID and user_id not in sudo_users:
        return await query.answer("This menu is restricted to Owner and Sudo users!", show_alert=True)

    if action == "close":
        await query.answer()
        await delete_message(query.message)
        return

    target_user_id = int(data[2]) if len(data) > 2 and data[2].isdigit() else user_id
    if user_id != target_user_id and user_id != Config.OWNER_ID:
        return await query.answer("This menu is not for you!", show_alert=True)

    if action == "ref":
        await query.answer("Refreshed!")
        text, buttons = build_taskm_view(target_user_id, query.from_user)
        await edit_message(query.message, text, buttons)

    elif action == "set":
        new_val = safe_int(data[3])
        update_user_ldata(target_user_id, "maxtask", new_val)
        await database.update_user_data(target_user_id)
        from bot.helper.ext_utils.task_manager import start_from_queued
        await start_from_queued()
        await query.answer(f"Task limit set to {new_val if new_val > 0 else 'Unlimited'}!", show_alert=True)
        text, buttons = build_taskm_view(target_user_id, query.from_user)
        await edit_message(query.message, text, buttons)

    elif action == "custom":
        await query.answer()
        buttons = ButtonMaker()
        buttons.data_button("◀️ Back", f"taskm ref {target_user_id}", position="footer")
        prompt = "<b>✏️ Set Custom Task Limit:</b>\nPlease send maximum simultaneous running tasks number (e.g. <code>2</code> or <code>0</code> for unlimited).\n⏱️ <i>Timeout: 30s</i>"
        await edit_message(query.message, prompt, buttons.build_menu(1))

        event_done = bot_loop.create_future()
        user_input = []

        async def limit_filter(_, __, event):
            u = event.from_user or event.sender_chat
            return bool(u and u.id == target_user_id and event.chat.type == ChatType.PRIVATE and event.text)

        async def limit_handler(_, msg):
            user_input.append(msg.text.strip())
            await delete_message(msg)
            if not event_done.done():
                event_done.set_result(True)

        h = client.add_handler(MessageHandler(limit_handler, filters=create(limit_filter)), group=-1)
        try:
            await wait_for(event_done, timeout=30)
            if user_input and user_input[0].isdigit():
                new_val = safe_int(user_input[0])
                update_user_ldata(target_user_id, "maxtask", new_val)
                await database.update_user_data(target_user_id)
                from bot.helper.ext_utils.task_manager import start_from_queued
                await start_from_queued()
        except Exception:
            pass
        finally:
            client.remove_handler(*h)
            text, buttons = build_taskm_view(target_user_id, query.from_user)
            await edit_message(query.message, text, buttons)


def build_taskuser_view(user_id, from_user):
    user_name = from_user.mention(style="html")
    user_dict = user_data.get(user_id, {})
    user_limit = safe_int(user_dict.get("maxtask", Config.USER_MAX_TASKS))
    admin_max = safe_int(Config.USER_MAX_TASKS)

    limit_str = f"<b>{user_limit}</b>" if user_limit > 0 else f"<b>{admin_max} (Max Default)</b>"
    admin_cap_str = f"<code>{admin_max}</code>" if admin_max > 0 else "<i>No Global Limit</i>"

    running_list, queued_list = _get_task_details(user_id)

    text = "<b>👤 User Task Manager & Queue Status (/taskuser)</b>\n\n"
    text += f"<blockquote>• <b>User:</b> {user_name}\n"
    text += f"• <b>Your Configured Task Limit:</b> {limit_str}\n"
    text += f"• <b>Admin Max Tasks Allowed:</b> {admin_cap_str}\n"
    text += f"• <b>Your Running Tasks:</b> <code>{len(running_list)}</code>\n"
    text += f"• <b>Your Queued Tasks:</b> <code>{len(queued_list)}</code></blockquote>\n\n"

    if running_list:
        text += "<b>▶️ Your Running Tasks:</b>\n"
        for idx, (mid, gid, name, mode) in enumerate(running_list, start=1):
            text += f"{idx}. [<code>{mode}</code>] <code>{name}</code> (<code>#{gid[:8]}</code>)\n"
        text += "\n"
    else:
        text += "<b>▶️ Your Running Tasks:</b> <i>None</i>\n\n"

    if queued_list:
        text += "<b>⏳ Your Queued Tasks & Status:</b>\n"
        for pos, mid, gid, name, st_label in queued_list:
            text += f"• <b>Queue #{pos}:</b> [<code>{st_label}</code>] <code>{name}</code> (<code>#{gid[:8]}</code>)\n"
        text += "\n"
    else:
        text += "<b>⏳ Your Queued Tasks & Status:</b> <i>None</i>\n\n"

    text += "<i>Note: You can set a limit up to your allowed max tasks. Unlimited (0) is not allowed for normal users.</i>"

    buttons = ButtonMaker()
    max_opts = admin_max if admin_max > 0 else 5
    for val in range(1, min(max_opts + 1, 6)):
        buttons.data_button(str(val), f"taskuser set {user_id} {val}")

    buttons.data_button("✏️ Custom Input", f"taskuser custom {user_id}", position="header")
    buttons.data_button("♻️ Refresh", f"taskuser ref {user_id}", position="header")
    buttons.data_button("❌ Close", "taskuser close", position="footer", style=ButtonStyle.DANGER)

    return text, buttons.build_menu(3)


@new_task
async def taskuser_command(client, message):
    if message.chat.type != ChatType.PRIVATE:
        await send_message(
            message,
            "<blockquote>The <code>/taskuser</code> command works ONLY in Direct Messages (DM)!</blockquote>",
        )
        return

    user_id = message.from_user.id if message.from_user else 0
    admin_max = safe_int(Config.USER_MAX_TASKS)

    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].strip().isdigit():
        new_val = safe_int(args[1].strip())
        if new_val <= 0:
            await send_message(
                message,
                "<blockquote>Normal users cannot set unlimited (0) task limit! Please choose a number greater than 0.</blockquote>",
            )
            return
        if admin_max > 0 and new_val > admin_max:
            await send_message(
                message,
                f"<blockquote>Your task limit cannot exceed the admin limit of <b>{admin_max}</b>!</blockquote>",
            )
            return
        update_user_ldata(user_id, "maxtask", new_val)
        await database.update_user_data(user_id)
        from bot.helper.ext_utils.task_manager import start_from_queued
        await start_from_queued()

    text, buttons = build_taskuser_view(user_id, message.from_user)
    await send_message(message, text, buttons)


@new_task
async def taskuser_callback(client, query):
    user_id = query.from_user.id
    data = query.data.split()
    action = data[1]

    if action == "close":
        await query.answer()
        await delete_message(query.message)
        return

    target_user_id = int(data[2]) if len(data) > 2 and data[2].isdigit() else user_id
    if user_id != target_user_id:
        return await query.answer("This menu is not for you!", show_alert=True)

    admin_max = safe_int(Config.USER_MAX_TASKS)

    if action == "ref":
        await query.answer("Refreshed!")
        text, buttons = build_taskuser_view(target_user_id, query.from_user)
        await edit_message(query.message, text, buttons)

    elif action == "set":
        new_val = safe_int(data[3])
        if new_val <= 0:
            return await query.answer("Normal users cannot set unlimited task limit!", show_alert=True)
        if admin_max > 0 and new_val > admin_max:
            return await query.answer(f"Limit cannot exceed admin max of {admin_max}!", show_alert=True)
        update_user_ldata(target_user_id, "maxtask", new_val)
        await database.update_user_data(target_user_id)
        from bot.helper.ext_utils.task_manager import start_from_queued
        await start_from_queued()
        await query.answer(f"Task limit set to {new_val}!", show_alert=True)
        text, buttons = build_taskuser_view(target_user_id, query.from_user)
        await edit_message(query.message, text, buttons)

    elif action == "custom":
        await query.answer()
        buttons = ButtonMaker()
        buttons.data_button("◀️ Back", f"taskuser ref {target_user_id}", position="footer")
        prompt = f"<b>✏️ Set Custom Task Limit:</b>\nPlease send your desired task limit (1-{admin_max if admin_max > 0 else 'infinity'}).\n⏱️ <i>Timeout: 30s</i>"
        await edit_message(query.message, prompt, buttons.build_menu(1))

        event_done = bot_loop.create_future()
        user_input = []

        async def limit_filter(_, __, event):
            u = event.from_user or event.sender_chat
            return bool(u and u.id == target_user_id and event.chat.type == ChatType.PRIVATE and event.text)

        async def limit_handler(_, msg):
            user_input.append(msg.text.strip())
            await delete_message(msg)
            if not event_done.done():
                event_done.set_result(True)

        h = client.add_handler(MessageHandler(limit_handler, filters=create(limit_filter)), group=-1)
        try:
            await wait_for(event_done, timeout=30)
            if user_input and user_input[0].isdigit():
                new_val = safe_int(user_input[0])
                if new_val <= 0:
                    await send_message(query.message, "<blockquote>Cannot set 0 (unlimited)!</blockquote>")
                elif admin_max > 0 and new_val > admin_max:
                    await send_message(query.message, f"<blockquote>Cannot exceed admin limit of {admin_max}!</blockquote>")
                else:
                    update_user_ldata(target_user_id, "maxtask", new_val)
                    await database.update_user_data(target_user_id)
                    from bot.helper.ext_utils.task_manager import start_from_queued
                    await start_from_queued()
        except Exception:
            pass
        finally:
            client.remove_handler(*h)
            text, buttons = build_taskuser_view(target_user_id, query.from_user)
            await edit_message(query.message, text, buttons)
