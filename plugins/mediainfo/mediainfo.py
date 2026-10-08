from os import getcwd, path as ospath
from re import search, sub as re_sub
from shlex import split

from aiofiles import open as aiopen
from aiofiles.os import mkdir, path as aiopath, remove as aioremove
from aiohttp import ClientSession, ClientTimeout

from bot import LOGGER
from bot.core.tg_client import TgClient
from bot.helper.ext_utils.bot_utils import cmd_exec
from bot.helper.ext_utils.telegraph_helper import telegraph
from bot.core.config_manager import Config
from bot.helper.telegram_helper.message_utils import send_message, edit_message


async def gen_mediainfo(message, link=None, media=None, mmsg=None):
    temp_send = await send_message(message, "<i>Generating MediaInfo...</i>")
    des_path = None
    tc = ""
    try:
        path = "mediainfo/"
        if not await aiopath.isdir(path):
            await mkdir(path)
        file_size = 0
        if link:
            clean_link = link.strip().split()[0].rstrip("),]}>")
            filename = ospath.basename(clean_link.split("?", 1)[0].split("#", 1)[0]) or "media"
            filename = re_sub(r"[^A-Za-z0-9._-]+", "_", filename)[:180] or "media"
            des_path = ospath.join(path, filename)
            headers = {
                "user-agent": "Mozilla/5.0 (Linux; Android 12; 2201116PI) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Mobile Safari/537.36"
            }
            async with ClientSession() as session:
                async with session.get(
                    clean_link,
                    headers=headers,
                    allow_redirects=True,
                    timeout=ClientTimeout(total=3600),
                ) as response:
                    response.raise_for_status()
                    file_size = int(response.headers.get("Content-Length", 0) or 0)
                    async with aiopen(des_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(4 * 1024 * 1024):
                            await f.write(chunk)
        elif media:
            des_path = ospath.join(path, media.file_name)
            file_size = media.file_size
            if file_size <= 50000000:
                await mmsg.download(ospath.join(getcwd(), des_path))
            else:
                async for chunk in TgClient.bot.stream_media(media, limit=5):
                    async with aiopen(des_path, "ab") as f:
                        await f.write(chunk)
        stdout, _, _ = await cmd_exec(split(f'mediainfo "{des_path}"'))
        tc = f"<h4>📌 {ospath.basename(des_path)}</h4><br><br>"
        if len(stdout) != 0:
            tc += parseinfo(stdout, file_size)
    except Exception as e:
        LOGGER.error(e)
        return await edit_message(temp_send, f"MediaInfo Stopped due to {str(e)}")
    finally:
        if des_path and await aiopath.exists(des_path):
            await aioremove(des_path)

    if not tc or not tc.strip():
        return await edit_message(temp_send, "MediaInfo Generation Failed: No content extracted from file.")

    # Create a clean shareable Graph.org MediaInfo page first.
    # Format: https://graph.org/MediaInfo-X-DD-MM-xxxxx
    page_url = ""
    try:
        from datetime import datetime
        import random
        title = f"MediaInfo-X-{datetime.now().strftime("%d-%m")}-{random.randint(10000, 99999)}"
        page = await telegraph.create_page(title=title, content=tc)
        path = page.get("path", "") if isinstance(page, dict) else ""
        if path:
            page_url = path if path.startswith("http") else f"https://graph.org/{path.lstrip("/")}"
    except Exception as e:
        LOGGER.warning(f"Graph.org MediaInfo page creation failed: {e}")

    # Fallback to PastyX if Telegraph/Graph.org is unavailable.
    if not page_url:
        try:
            async with ClientSession() as session:
                async with session.post(
                    "https://pastyx.pages.dev/api/paste",
                    json={
                        "content": tc,
                        "title": f"MediaInfo · {ospath.basename(des_path or 'media')}",
                        "author": "HTR-X",
                        "expiry": "never",
                    },
                    timeout=ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        payload = await response.json(content_type=None)
                        page_url = payload.get("url", "")
        except Exception as e:
            LOGGER.warning(f"PastyX MediaInfo upload failed: {e}")

    if not page_url:
        return await edit_message(temp_send, "❌ MediaInfo page creation failed.")

    await temp_send.edit(
        f"<b>MediaInfo:</b>\n\n➲ <b>Link :</b> {page_url}",
        disable_web_page_preview=False,
    )


section_dict = {"General": "🗒", "Video": "🎞", "Audio": "🔊", "Text": "🔠", "Menu": "🗃"}


def parseinfo(out, size):
    tc, trigger = "", False
    size_line = (
        f"File size                                 : {size / (1024 * 1024):.2f} MiB"
    )
    for line in out.split("\n"):
        for section, emoji in section_dict.items():
            if line.startswith(section):
                trigger = True
                if not line.startswith("General"):
                    tc += "</pre><br>"
                tc += f"<h4>{emoji} {line.replace('Text', 'Subtitle')}</h4>"
                break
        if line.startswith("File size"):
            line = size_line
        if trigger:
            tc += "<br><pre>"
            trigger = False
        else:
            tc += line + "\n"
    tc += "</pre><br>"
    return tc


async def mediainfo(_, message):
    rply = message.reply_to_message
    cmd = f"mediainfo{Config.CMD_SUFFIX}"
    alias = f"mi{Config.CMD_SUFFIX}"
    help_msg = f"""
<b>By replying to media:</b>
<code>/{cmd} or /{alias} [media]</code>

<b>By reply/sending download link:</b>
<code>/{cmd} or /{alias} [link]</code>
"""
    if len(message.command) > 1 or rply and rply.text:
        link = rply.text if rply else message.command[1]
        return await gen_mediainfo(message, link)
    elif rply:
        if file := next(
            (
                i
                for i in [
                    rply.document,
                    rply.video,
                    rply.audio,
                    rply.voice,
                    rply.animation,
                    rply.video_note,
                ]
                if i is not None
            ),
            None,
        ):
            return await gen_mediainfo(message, None, file, rply)
        else:
            return await send_message(message, help_msg)
    else:
        return await send_message(message, help_msg)
