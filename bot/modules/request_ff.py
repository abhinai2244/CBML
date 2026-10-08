import json
from ast import literal_eval
from html import escape
from secrets import token_hex

from pyrogram.enums import ButtonStyle

from .. import LOGGER, sudo_users
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.db_handler import database
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    edit_message,
    send_message,
)
from .users_settings import validate_ffmpeg_cmds

PENDING_FF_REQUESTS = {}


@new_task
async def request_ff(client, message):
    from_user = message.from_user or message.sender_chat
    user_id = from_user.id if from_user else 0
    tag = from_user.mention(style="html") if from_user else "N/A"

    cmd_name = (
        BotCommands.RequestFFCommand[0]
        if isinstance(BotCommands.RequestFFCommand, list)
        else BotCommands.RequestFFCommand
    )

    args = message.text.split(maxsplit=1)
    input_str = args[1].strip() if len(args) > 1 else ""

    example_usage = (
        f"<b>🎬 Request FFmpeg Presets</b>\n\n"
        f"<b>Usage:</b> <code>/{cmd_name} &lt;python_dict_presets&gt;</code>\n\n"
        f"<b>Example:</b>\n"
        f"<code>/{cmd_name} {{\n"
        f'    "tel": [\n'
        f'        "-i mltb.video -map 0:v -map 0:a:m:language:tel -c copy mltb -del",\n'
        f'        "-i mltb.audio -map 0:a:m:language:tel -c copy mltb -del"\n'
        f"    ],\n"
        f'    "tam": [\n'
        f'        "-i mltb.video -map 0:v -map 0:a:m:language:tam -c copy mltb -del",\n'
        f'        "-i mltb.audio -map 0:a:m:language:tam -c copy mltb -del"\n'
        f"    ],\n"
        f'    "hin": [\n'
        f'        "-i mltb.video -map 0:v -map 0:a:m:language:hin -c copy mltb -del",\n'
        f'        "-i mltb.audio -map 0:a:m:language:hin -c copy mltb -del"\n'
        f"    ]\n"
        f"}}</code>"
    )

    if not input_str:
        return await send_message(message, example_usage)

    try:
        parsed_dict = literal_eval(input_str)
        if not isinstance(parsed_dict, dict) or not parsed_dict:
            raise ValueError("Input must be a non-empty Python dictionary!")
        validate_ffmpeg_cmds(parsed_dict)
    except Exception as e:
        return await send_message(
            message,
            f"<b>Malformed FFmpeg preset dict:</b> {escape(str(e))}\n\n{example_usage}",
        )

    req_id = token_hex(4)
    PENDING_FF_REQUESTS[req_id] = {
        "user_id": user_id,
        "tag": tag,
        "cmds": parsed_dict,
    }

    recipients = set()
    if Config.OWNER_ID:
        try:
            recipients.add(int(Config.OWNER_ID))
        except (ValueError, TypeError):
            pass
    for uid in sudo_users:
        try:
            recipients.add(int(uid))
        except (ValueError, TypeError):
            pass

    if not recipients:
        return await send_message(
            message, "No Owner or Sudo users configured to receive your request."
        )

    buttons = ButtonMaker()
    buttons.data_button(
        "✅ Approve", f"reqff approve {req_id}", style=ButtonStyle.SUCCESS
    )
    buttons.data_button(
        "❌ Reject", f"reqff reject {req_id}", style=ButtonStyle.DANGER
    )
    btn_markup = buttons.build_menu(2)

    formatted_json = json.dumps(parsed_dict, indent=2)
    req_text = (
        f"<b>🎬 New FFmpeg Preset Request Received!</b>\n\n"
        f"<blockquote>• <b>User:</b> {tag} (<code>#ID{user_id}</code>)\n"
        f"• <b>Requested Presets:</b>\n"
        f"<code>{escape(formatted_json)}</code></blockquote>"
    )

    for uid in recipients:
        try:
            await TgClient.bot.send_message(
                chat_id=uid,
                text=req_text,
                reply_markup=btn_markup,
                disable_web_page_preview=True,
            )
        except Exception as e:
            LOGGER.error(f"Failed to send requestff to sudo/owner {uid}: {e}")

    await send_message(
        message,
        f"<b>✅ Your FFmpeg preset request has been submitted to Owner/Sudos for approval.</b>\n\n"
        f"Requested keys: <code>{', '.join(parsed_dict.keys())}</code>",
    )


@new_task
async def reqff_callback(client, query):
    from ..helper.telegram_helper.filters import CustomFilters

    if not await CustomFilters.sudo(client, query):
        return await query.answer("This callback is restricted to Owner/Sudo users only!", show_alert=True)

    data = query.data.split()
    action = data[1]
    req_id = data[2]

    req_data = PENDING_FF_REQUESTS.get(req_id)
    if not req_data:
        return await query.answer("Request expired or already processed!", show_alert=True)

    await query.answer()
    user_id = req_data["user_id"]
    tag = req_data["tag"]
    requested_cmds = req_data["cmds"]
    approver_tag = query.from_user.mention(style="html")

    if action == "approve":
        current_ff = dict(Config.FFMPEG_CMDS or {})
        for k, v in requested_cmds.items():
            current_ff[k.lower().strip()] = v
        Config.set("FFMPEG_CMDS", current_ff)
        await database.update_config({"FFMPEG_CMDS": current_ff})

        formatted_json = json.dumps(requested_cmds, indent=2)
        approved_text = (
            f"<b>✅ FFmpeg Preset Request Approved!</b>\n\n"
            f"<blockquote>• <b>Approved By:</b> {approver_tag}\n"
            f"• <b>Request User:</b> {tag} (<code>#ID{user_id}</code>)\n"
            f"• <b>Added Presets:</b>\n"
            f"<code>{escape(formatted_json)}</code></blockquote>"
        )
        await edit_message(query.message, approved_text)

        dm_text = (
            f"<b>🎉 Your FFmpeg Command Preset Request Has Been Approved!</b>\n\n"
            f"<blockquote>• <b>Approved By:</b> {approver_tag}\n"
            f"• <b>Added Keys:</b> <code>{', '.join(requested_cmds.keys())}</code>\n"
            f"• <b>Usage:</b> Use <code>-ff {', '.join(requested_cmds.keys())}</code> in your tasks.</blockquote>"
        )
        try:
            await TgClient.bot.send_message(chat_id=user_id, text=dm_text)
        except Exception as e:
            LOGGER.error(f"Failed to notify user {user_id} of approval: {e}")

        PENDING_FF_REQUESTS.pop(req_id, None)

    elif action == "reject":
        rejected_text = (
            f"<b>❌ FFmpeg Preset Request Rejected</b>\n\n"
            f"<blockquote>• <b>Rejected By:</b> {approver_tag}\n"
            f"• <b>Request User:</b> {tag} (<code>#ID{user_id}</code>)</blockquote>"
        )
        await edit_message(query.message, rejected_text)

        dm_text = (
            f"<b>❌ Your FFmpeg Command Preset Request Has Been Rejected</b>\n\n"
            f"<blockquote>Your requested preset(s) <code>{', '.join(requested_cmds.keys())}</code> were rejected by {approver_tag}.</blockquote>"
        )
        try:
            await TgClient.bot.send_message(chat_id=user_id, text=dm_text)
        except Exception as e:
            LOGGER.error(f"Failed to notify user {user_id} of rejection: {e}")

        PENDING_FF_REQUESTS.pop(req_id, None)
