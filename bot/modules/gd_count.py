from ..helper.ext_utils.bot_utils import sync_to_async, new_task
from ..helper.ext_utils.links_utils import is_gdrive_link
from ..helper.ext_utils.status_utils import get_readable_file_size
from ..helper.mirror_leech_utils.gdrive_utils.count import GoogleDriveCount
from ..helper.telegram_helper.message_utils import delete_message, send_message


@new_task
async def count_node(_, message):
    args = message.text.split()
    user = message.from_user or message.sender_chat
    if username := user.username:
        tag = f"@{username}"
    else:
        tag = message.from_user.mention(style="html")

    link = args[1] if len(args) > 1 else ""
    if len(link) == 0 and (reply_to := message.reply_to_message):
        link = reply_to.text.split(maxsplit=1)[0].strip()

    if is_gdrive_link(link):
        msg = await send_message(message, f"<b>Counting Google Drive contents...</b>\n<code>{link}</code>")
        name, mime_type, size, files, folders = await sync_to_async(
            GoogleDriveCount().count, link, user.id
        )
        if mime_type is None:
            await send_message(message, name)
            return
        await delete_message(msg)
        msg = "<b>📁 Google Drive Count Result</b>\n\n"
        msg += f"<blockquote>• <b>Name:</b> <code>{name}</code>\n"
        msg += f"• <b>Size:</b> {get_readable_file_size(size)}\n"
        msg += f"• <b>Type:</b> {mime_type}\n"
        if mime_type == "Folder":
            msg += f"• <b>Subfolders:</b> {folders}\n"
            msg += f"• <b>Files:</b> {files}\n"
        msg += f"• <b>Requested By:</b> {tag}</blockquote>"
    else:
        msg = (
            "<blockquote>Send Google Drive link along with command or reply to a message containing the link.</blockquote>"
        )

    await send_message(message, msg, photo="IMAGES")
