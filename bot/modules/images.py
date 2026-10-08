from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import handleIndex, new_task
from ..helper.ext_utils.db_handler import database
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
)


@new_task
async def picture_add(_, message):
    resm = message.reply_to_message
    editable = await send_message(message, "<b>Processing image input...</b>")
    if len(message.command) > 1 or resm and resm.text:
        msg_text = resm.text if resm else message.command[1]
        if not msg_text.startswith("http"):
            return await edit_message(
                editable, "<blockquote>Invalid URL! Link must start with 'http'.</blockquote>"
            )
        pic_add = msg_text.strip()
    elif resm and resm.photo:
        if resm.photo.file_size > 5242880 * 2:
            return await edit_message(
                editable, "<blockquote>Media not supported! File size is too large.</blockquote>"
            )
        pic_add = resm.photo.file_id
    else:
        help_msg = f"""<b>🖼️ Add Image Usage Guide</b>

<blockquote><b>How to add images:</b>
• <b>Reply to Image URL:</b> <code>/{BotCommands.AddImageCommand} https://link.com/image.jpg</code>
• <b>Reply to Photo:</b> Send photo and reply with <code>/{BotCommands.AddImageCommand}</code>

<b>Supported Formats:</b> Direct image links, Telegram photos</blockquote>"""
        return await edit_message(editable, help_msg)
    Config.IMAGES.append(pic_add)
    if Config.DATABASE_URL:
        await database.update_config({"IMAGES": Config.IMAGES})
    await edit_message(
        editable,
        f"<b>🖼️ Image Added to Gallery</b>\n\n<blockquote>• <b>Total Gallery Images:</b> <code>{len(Config.IMAGES)}</code></blockquote>",
    )


@new_task
async def pictures(_, message):
    if not Config.IMAGES:
        await send_message(
            message,
            f"<blockquote>No images in gallery! Add images using <code>/{BotCommands.AddImageCommand}</code></blockquote>",
        )
    else:
        to_edit = await send_message(
            message, "<b>Loading image gallery...</b>"
        )
        buttons = ButtonMaker()
        user_id = message.from_user.id
        buttons.data_button("« Previous", f"images {user_id} turn -1")
        buttons.data_button("Next »", f"images {user_id} turn 1")
        buttons.data_button("🗑️ Remove Image", f"images {user_id} remov 0")
        buttons.data_button("❌ Close", f"images {user_id} close")
        buttons.data_button("⚠️ Remove All", f"images {user_id} removall", "footer")
        await delete_message(to_edit)
        total = len(Config.IMAGES)
        await send_message(
            message,
            f"<b>🖼️ Image Gallery</b>\n\n<blockquote>• <b>Image:</b> 1 / {total}</blockquote>",
            buttons.build_menu(2),
            photo=Config.IMAGES[0],
        )


@new_task
async def pics_callback(_, query):
    message = query.message
    user_id = query.from_user.id
    data = query.data.split()
    if user_id != int(data[1]):
        await query.answer(text="This menu is not for you!", show_alert=True)
        return
    if data[2] == "turn":
        await query.answer()
        if not Config.IMAGES:
            await delete_message(message)
            await send_message(
                message,
                f"<blockquote>No images in gallery! Add images using <code>/{BotCommands.AddImageCommand}</code></blockquote>",
            )
            return
        ind = handleIndex(int(data[3]), Config.IMAGES)
        total = len(Config.IMAGES)
        no = ind + 1
        pic_info = f"<b>🖼️ Image Gallery</b>\n\n<blockquote>• <b>Image:</b> {no} / {total}</blockquote>"
        buttons = ButtonMaker()
        buttons.data_button("« Previous", f"images {data[1]} turn {ind - 1}")
        buttons.data_button("Next »", f"images {data[1]} turn {ind + 1}")
        buttons.data_button("🗑️ Remove Image", f"images {data[1]} remov {ind}")
        buttons.data_button("❌ Close", f"images {data[1]} close")
        buttons.data_button("⚠️ Remove All", f"images {data[1]} removall", "footer")
        if message.media:
            await edit_message(
                message, pic_info, buttons.build_menu(2), photo=Config.IMAGES[ind]
            )
        else:
            await delete_message(message)
            await send_message(
                message,
                pic_info,
                buttons.build_menu(2),
                photo=Config.IMAGES[ind],
            )
    elif data[2] == "remov":
        Config.IMAGES.pop(int(data[3]))
        if Config.DATABASE_URL:
            await database.update_config({"IMAGES": Config.IMAGES})
        await query.answer("Image deleted!", show_alert=True)
        if len(Config.IMAGES) == 0:
            await delete_message(message)
            await send_message(
                message,
                f"<blockquote>No images in gallery! Add images using <code>/{BotCommands.AddImageCommand}</code></blockquote>",
            )
            return
        ind = int(data[3])
        ind = min(ind, len(Config.IMAGES) - 1)
        total = len(Config.IMAGES)
        no = ind + 1
        pic_info = f"<b>🖼️ Image Gallery</b>\n\n<blockquote>• <b>Image:</b> {no} / {total}</blockquote>"
        buttons = ButtonMaker()
        buttons.data_button("« Previous", f"images {data[1]} turn {ind - 1}")
        buttons.data_button("Next »", f"images {data[1]} turn {ind + 1}")
        buttons.data_button("🗑️ Remove Image", f"images {data[1]} remov {ind}")
        buttons.data_button("❌ Close", f"images {data[1]} close")
        buttons.data_button("⚠️ Remove All", f"images {data[1]} removall", "footer")
        if message.media:
            await edit_message(
                message, pic_info, buttons.build_menu(2), photo=Config.IMAGES[ind]
            )
        else:
            await delete_message(message)
            await send_message(
                message,
                pic_info,
                buttons.build_menu(2),
                photo=Config.IMAGES[ind],
            )
    elif data[2] == "removall":
        Config.IMAGES.clear()
        if Config.DATABASE_URL:
            await database.update_config({"IMAGES": Config.IMAGES})
        await query.answer("All images deleted!", show_alert=True)
        await delete_message(message)
        await send_message(
            message,
            f"<blockquote>No images in gallery! Add images using <code>/{BotCommands.AddImageCommand}</code></blockquote>",
        )
    else:
        await query.answer()
        await delete_message(message)
        if message.reply_to_message:
            await delete_message(message.reply_to_message)
