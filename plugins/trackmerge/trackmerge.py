import asyncio
import mimetypes
import os
import re
import shlex
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from pyrogram import filters
from pyrogram.types import Message

from bot import LOGGER
from bot.core.tg_client import TgClient
from bot.helper.ext_utils.bot_utils import cmd_exec
from bot.helper.telegram_helper.message_utils import send_message, edit_message, delete_message

SESSIONS = {}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".m4v", ".ts", ".3gp"}
AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".aac", ".ac3", ".ogg", ".opus", ".wav", ".wma", ".eac3", ".mka"}
SUB_EXTS = {".srt", ".ass", ".vtt", ".sub", ".idx", ".sup"}
URL_RE = re.compile(r"https?://[^\s<>]+")


def _kind_from_name(name, content_type=""):
    ext = Path(urlparse(name).path).suffix.lower()
    ct = (content_type or "").split(";", 1)[0].lower()
    if ext in VIDEO_EXTS or ct.startswith("video/"):
        return "video"
    if ext in SUB_EXTS or "subtitle" in ct or ct in {"text/vtt", "application/x-subrip", "text/srt"}:
        return "subtitle"
    if ext in AUDIO_EXTS or ct.startswith("audio/"):
        return "audio"
    return None


def _safe_name(name, default):
    name = os.path.basename(name or "").strip()
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", name)
    return name[:180] or default


def _source_from_message(msg):
    media = (
        msg.document or msg.video or msg.audio or msg.voice or
        msg.animation or msg.video_note
    )
    if not media:
        return None
    name = getattr(media, "file_name", None) or getattr(media, "file_unique_id", None) or "media"
    kind = _kind_from_name(name, getattr(media, "mime_type", ""))
    return {"kind": kind, "name": _safe_name(name, f"track_{msg.id}"), "message_id": msg.id}


def _parse_sources(text):
    result = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        forced = None
        if line.lower().startswith("audio|"):
            forced, line = "audio", line[6:].strip()
        elif line.lower().startswith("sub|"):
            forced, line = "subtitle", line[4:].strip()
        for token in URL_RE.findall(line):
            token = token.rstrip("),]}>")
            kind = forced or _kind_from_name(token)
            result.append((token, kind))
    return result



async def _download_url(url, dest_dir, forced_kind=None):
    headers = {"User-Agent": "Mozilla/5.0 CANTARELLABOTS TrackMerge"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=3600)) as r:
            r.raise_for_status()
            ct = r.headers.get("Content-Type", "")
            kind = forced_kind or _kind_from_name(str(r.url), ct)
            if not kind:
                raise ValueError("Cannot determine whether the URL is audio or subtitle. Use audio|URL or sub|URL.")
            suffix = Path(urlparse(str(r.url)).path).suffix.lower()
            if not suffix:
                suffix = {"audio": ".mka", "subtitle": ".srt", "video": ".mkv"}[kind]
            name = _safe_name(Path(urlparse(str(r.url)).path).name, f"download{suffix}")
            if not Path(name).suffix:
                name += suffix
            path = os.path.join(dest_dir, name)
            base, ext = os.path.splitext(path)
            i = 2
            while os.path.exists(path):
                path = f"{base}_{i}{ext}"
                i += 1
            with open(path, "wb") as f:
                async for chunk in r.content.iter_chunked(1024 * 1024):
                    f.write(chunk)
    return path, kind


async def _download_tg(msg, dest_dir):
    src = _source_from_message(msg)
    if not src or not src["kind"]:
        raise ValueError("Unsupported Telegram media. Send an audio or subtitle file.")
    media = (
        msg.document or msg.video or msg.audio or msg.voice or
        msg.animation or msg.video_note
    )
    path = await msg.download(file_name=os.path.join(dest_dir, src["name"]))
    return path, src["kind"]


def _planner_text(s):
    lines = [
        "<b>🧩 CANTARELLABOTS Track Merge Planner</b>",
        "",
        f"🎬 <b>Video:</b> <code>{s['video_name']}</code>",
        f"🔊 <b>Audio tracks:</b> {sum(x['kind']=='audio' for x in s['tracks'])}",
        f"📝 <b>Subtitle tracks:</b> {sum(x['kind']=='subtitle' for x in s['tracks'])}",
        f"📦 <b>Total tracks:</b> {len(s['tracks'])}",
        f"✏️ <b>Output:</b> <code>{s['output']}</code>",
        "",
    ]
    for i, t in enumerate(s["tracks"], 1):
        lang = t.get("language") or "und"
        title = t.get("title") or "-"
        icon = "🔊" if t["kind"] == "audio" else "📝"
        lines.append(f"{i}. {icon} <code>{t['name'][:45]}</code> — <b>{lang}</b> — {title}")
    lines += ["", "<i>Use the buttons to reorder, remove, rename output, or edit track language/title.</i>"]
    return "\n".join(lines)


def _planner_buttons(s):
    from bot.helper.telegram_helper.button_build import ButtonMaker
    b = ButtonMaker()
    for i, t in enumerate(s["tracks"]):
        b.data_button(f"{i+1} {'🔊' if t['kind']=='audio' else '📝'} Lang/Edit", f"tmerge edit {s['id']} {i}")
        if i > 0:
            b.data_button(f"⬆️ {i+1}", f"tmerge move {s['id']} {i} -1")
        if i < len(s["tracks"]) - 1:
            b.data_button(f"⬇️ {i+1}", f"tmerge move {s['id']} {i} 1")
        b.data_button(f"❌ {i+1}", f"tmerge rm {s['id']} {i}")
    b.data_button("➕ Add Track", f"tmerge add {s['id']}", position="footer")
    b.data_button("✏️ Rename Output", f"tmerge name {s['id']}", position="footer")
    b.data_button("🚀 Done & Start", f"tmerge done {s['id']}", position="footer")
    b.data_button("🗑️ Cancel", f"tmerge cancel {s['id']}", position="footer")
    return b.build_menu(3)


async def _show(s):
    if s.get("message"):
        await edit_message(s["message"], _planner_text(s), _planner_buttons(s))


async def _ask_input(client, chat_id, prompt, session_id, timeout=60):
    msg = await client.send_message(chat_id, prompt)
    fut = asyncio.get_running_loop().create_future()

    async def handler(_, event):
        if event.chat.id != chat_id or not event.from_user or event.from_user.id != s_user(session_id):
            return
        if not (event.text or event.media):
            return
        if not fut.done():
            fut.set_result(event)

    h = client.add_handler(__import__("pyrogram").handlers.MessageHandler(handler, group=-2))
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        with suppress(Exception):
            client.remove_handler(*h)
        with suppress(Exception):
            await delete_message(msg)


def s_user(sid):
    return SESSIONS.get(sid, {}).get("user_id", 0)


async def _start_ffmpeg(s):
    work = s["workdir"]
    output = os.path.join(work, _safe_name(s["output"], "merged.mkv"))
    if not output.lower().endswith(".mkv"):
        output = os.path.splitext(output)[0] + ".mkv"

    inputs = [s["video_path"]] + [t["path"] for t in s["tracks"]]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for p in inputs:
        cmd += ["-i", p]

    # Main video + all existing streams from the source video.
    cmd += ["-map", "0:v:0", "-map", "0:a?", "-map", "0:s?"]
    for i, t in enumerate(s["tracks"], 1):
        if t["kind"] == "audio":
            cmd += ["-map", f"{i}:a:0?"]
        else:
            cmd += ["-map", f"{i}:s:0?"]

    cmd += ["-c:v", "copy", "-c:a", "copy", "-c:s", "copy"]
    cmd += ["-map_metadata", "0"]

    # Count streams already present in the main video so metadata indices for
    # newly added tracks remain correct even when the video already has audio/subtitles.
    probe = await cmd_exec([
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1", s["video_path"]
    ])
    existing_audio = sum(1 for line in (probe[0] or "").splitlines() if line.strip() == "audio")
    existing_sub = sum(1 for line in (probe[0] or "").splitlines() if line.strip() == "subtitle")
    audio_index = existing_audio
    sub_index = existing_sub
    for t in s["tracks"]:
        if t["kind"] == "audio":
            # Existing source audio tracks precede added tracks; metadata is
            # applied to the added track using ffmpeg's output stream index.
            audio_index += 1
            out_idx = audio_index
            cmd += [f"-metadata:s:a:{out_idx}", f"language={t.get('language') or 'und'}"]
            if t.get("title"):
                cmd += [f"-metadata:s:a:{out_idx}", f"title={t['title']}"]
        else:
            sub_index += 1
            cmd += [f"-metadata:s:s:{sub_index}", f"language={t.get('language') or 'und'}"]
            if t.get("title"):
                cmd += [f"-metadata:s:s:{sub_index}", f"title={t['title']}"]

    cmd += [output]
    status = await send_message(s["user_id"], "⏳ <b>Merging video + tracks…</b>")
    stdout, stderr, code = await cmd_exec(cmd)
    if code != 0 or not os.path.exists(output):
        await edit_message(status, f"❌ <b>Merge failed.</b>\n<pre>{(stderr or stdout or 'FFmpeg failed')[-3500:]}</pre>")
        return
    try:
        if output.lower().endswith(".mp4"):
            await TgClient.bot.send_video(s["user_id"], output, caption="🎬 <b>CANTARELLABOTS Track Merge Complete</b>")
        else:
            await TgClient.bot.send_document(s["user_id"], output, caption="🎬 <b>CANTARELLABOTS Track Merge Complete</b>")
        await edit_message(status, "✅ <b>Merge completed and uploaded.</b>")
    finally:
        with suppress(Exception):
            os.remove(output)
        with suppress(Exception):
            import shutil
            shutil.rmtree(work, ignore_errors=True)


async def merge_command(_, message):
    reply = message.reply_to_message
    video = reply if reply and (reply.video or (reply.document and _kind_from_name(reply.document.file_name or "", reply.document.mime_type or "") == "video")) else None
    if not video:
        return await send_message(
            message,
            "<b>🧩 CANTARELLABOTS Merge</b>\n\nReply to a video with <code>/merge</code>, then send audio/subtitle files or links.\n\n"
            "Direct links are also supported with <code>audio|URL</code> or <code>sub|URL</code>."
        )

    sid = f"{message.from_user.id}_{message.id}"
    work = os.path.join("trackmerge", sid)
    os.makedirs(work, exist_ok=True)
    try:
        video_path = await video.download(file_name=os.path.join(work, _safe_name(getattr(video.video or video.document, "file_name", None), "video.mkv")))
    except Exception as e:
        return await send_message(message, f"❌ Failed to download video: <code>{e}</code>")

    s = {
        "id": sid, "user_id": message.from_user.id, "chat_id": message.chat.id,
        "workdir": work, "video_path": video_path,
        "video_name": os.path.basename(video_path), "tracks": [],
        "output": os.path.splitext(os.path.basename(video_path))[0] + "_merged.mkv",
        "message": None,
    }
    SESSIONS[sid] = s

    # Accept links supplied directly with /merge.
    for url, forced in _parse_sources(message.text or ""):
        try:
            path, kind = await _download_url(url, work, forced)
            s["tracks"].append({"path": path, "name": os.path.basename(path), "kind": kind, "language": "und", "title": ""})
        except Exception as e:
            await send_message(message, f"⚠️ Skipped <code>{url[:100]}</code>: {e}")

    s["message"] = await send_message(
        message,
        _planner_text(s) + "\n\n<b>📥 Send audio/subtitle files or links now.</b>\nWhen finished, tap <b>🚀 Done & Start</b>.",
        _planner_buttons(s),
    )


async def _receive_add(s):
    prompt = await send_message(s["user_id"], "📥 <b>Send an audio/subtitle file or direct download link.</b>\nSend <code>audio|URL</code> or <code>sub|URL</code> when the URL has no useful extension.")
    fut = asyncio.get_running_loop().create_future()

    async def handler(_, event):
        if event.chat.id != s["chat_id"] or not event.from_user or event.from_user.id != s["user_id"]:
            return
        if event.text and event.text.startswith("/"):
            return
        if event.media or event.text:
            if not fut.done():
                fut.set_result(event)

    from pyrogram.handlers import MessageHandler
    h = TgClient.bot.add_handler(MessageHandler(handler, group=-2))
    try:
        event = await asyncio.wait_for(fut, timeout=90)
    except asyncio.TimeoutError:
        return
    finally:
        with suppress(Exception):
            TgClient.bot.remove_handler(*h)
        with suppress(Exception):
            await delete_message(prompt)

    try:
        if event.text:
            pairs = _parse_sources(event.text)
            if not pairs:
                raise ValueError("No direct download URL found.")
            for url, forced in pairs:
                path, kind = await _download_url(url, s["workdir"], forced)
                s["tracks"].append({"path": path, "name": os.path.basename(path), "kind": kind, "language": "und", "title": ""})
        else:
            path, kind = await _download_tg(event, s["workdir"])
            s["tracks"].append({"path": path, "name": os.path.basename(path), "kind": kind, "language": "und", "title": ""})
        await _show(s)
    except Exception as e:
        await send_message(s["user_id"], f"❌ Could not add track: <code>{e}</code>")


async def _prompt_edit(s, idx):
    if not 0 <= idx < len(s["tracks"]):
        return
    t = s["tracks"][idx]
    prompt = await send_message(
        s["user_id"],
        f"✏️ <b>Edit Track {idx+1}</b>\nSend <code>language|title</code>\nExample: <code>eng|English</code>\nUse <code>eng|</code> to keep only the language."
    )
    fut = asyncio.get_running_loop().create_future()

    async def handler(_, event):
        if event.chat.id == s["chat_id"] and event.from_user and event.from_user.id == s["user_id"] and event.text and not fut.done():
            fut.set_result(event.text.strip())

    from pyrogram.handlers import MessageHandler
    h = TgClient.bot.add_handler(MessageHandler(handler, group=-2))
    try:
        value = await asyncio.wait_for(fut, timeout=60)
        lang, _, title = value.partition("|")
        if lang.strip():
            t["language"] = lang.strip()[:16]
        t["title"] = title.strip()[:80]
        await _show(s)
    except asyncio.TimeoutError:
        pass
    finally:
        with suppress(Exception):
            TgClient.bot.remove_handler(*h)
        with suppress(Exception):
            await delete_message(prompt)


async def _prompt_name(s):
    prompt = await send_message(s["user_id"], "✏️ <b>Output filename:</b> send a name. Extension will be normalized to <code>.mkv</code>.")
    fut = asyncio.get_running_loop().create_future()

    async def handler(_, event):
        if event.chat.id == s["chat_id"] and event.from_user and event.from_user.id == s["user_id"] and event.text and not fut.done():
            fut.set_result(event.text.strip())

    from pyrogram.handlers import MessageHandler
    h = TgClient.bot.add_handler(MessageHandler(handler, group=-2))
    try:
        value = await asyncio.wait_for(fut, timeout=60)
        if value:
            s["output"] = value
            await _show(s)
    except asyncio.TimeoutError:
        pass
    finally:
        with suppress(Exception):
            TgClient.bot.remove_handler(*h)
        with suppress(Exception):
            await delete_message(prompt)


async def trackmerge_callback(_, query):
    data = query.data.split(maxsplit=4)
    if len(data) < 3:
        return await query.answer()
    action, sid = data[1], data[2]
    s = SESSIONS.get(sid)
    if not s or query.from_user.id != s["user_id"]:
        return await query.answer("This merge session is not yours or has expired.", show_alert=True)

    if action == "add":
        await query.answer("Waiting for a track…")
        return await _receive_add(s)

    if action == "edit":
        idx = int(data[3])
        await query.answer()
        return await _prompt_edit(s, idx)

    if action == "move":
        idx, direction = int(data[3]), int(data[4])
        target = idx + direction
        if 0 <= idx < len(s["tracks"]) and 0 <= target < len(s["tracks"]):
            s["tracks"][idx], s["tracks"][target] = s["tracks"][target], s["tracks"][idx]
        await query.answer("Track order updated.")
        return await _show(s)

    if action == "rm":
        idx = int(data[3])
        if 0 <= idx < len(s["tracks"]):
            t = s["tracks"].pop(idx)
            with suppress(Exception):
                os.remove(t["path"])
        await query.answer("Track removed.")
        return await _show(s)

    if action == "name":
        await query.answer()
        return await _prompt_name(s)

    if action == "cancel":
        await query.answer("Merge cancelled.")
        s = SESSIONS.pop(sid, None)
        if s:
            import shutil
            shutil.rmtree(s["workdir"], ignore_errors=True)
            with suppress(Exception):
                await edit_message(s["message"], "🗑️ <b>Merge session cancelled.</b>")
        return

    if action == "done":
        if not s["tracks"]:
            return await query.answer("Add at least one audio or subtitle track first.", show_alert=True)
        await query.answer("Starting FFmpeg…")
        await edit_message(s["message"], _planner_text(s) + "\n\n🚀 <b>Processing started…</b>")
        SESSIONS.pop(sid, None)
        return await _start_ffmpeg(s)
