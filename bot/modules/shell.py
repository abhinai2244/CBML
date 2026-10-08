from io import BytesIO

from .. import LOGGER
from ..helper.ext_utils.bot_utils import cmd_exec, new_task
from ..helper.telegram_helper.message_utils import send_message, send_file


@new_task
async def run_shell(_, message):
    cmd = message.text.split(maxsplit=1)
    if len(cmd) == 1:
        await send_message(message, "<blockquote>No shell command provided. Usage: <code>/shell &lt;cmd&gt;</code></blockquote>")
        return
    cmd = cmd[1]
    stdout, stderr, _ = await cmd_exec(cmd, shell=True)
    reply = ""
    if len(stdout) != 0:
        reply += f"<b>Stdout:</b>\n<blockquote expandable>{stdout}</blockquote>\n"
        LOGGER.info(f"Shell - {cmd} - {stdout}")
    if len(stderr) != 0:
        reply += f"<b>Stderr:</b>\n<blockquote expandable>{stderr}</blockquote>"
        LOGGER.error(f"Shell - {cmd} - {stderr}")
    if len(reply) > 3000:
        with BytesIO(str.encode(reply)) as out_file:
            out_file.name = "shell_output.txt"
            await send_file(message, out_file)
    elif len(reply) != 0:
        await send_message(message, reply)
    else:
        await send_message(message, "<blockquote>Command executed with no output.</blockquote>")
