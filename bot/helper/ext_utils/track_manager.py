import json
from asyncio import wait_for, TimeoutError as AsyncTimeoutError
from html import escape
from re import sub
from contextlib import suppress
from os import path as ospath, walk

from aiofiles.os import remove, path as aiopath
from aioshutil import move
from pyrogram.types import CallbackQuery

from ... import LOGGER, bot_loop, DOWNLOAD_DIR
from ...core.tg_client import TgClient
from ..telegram_helper.button_build import ButtonMaker
from .bot_utils import cmd_exec, new_task, sync_to_async
from .media_utils import FFMpeg, get_document_type
from .status_utils import get_readable_file_size
from ..telegram_helper.message_utils import delete_message, edit_message, send_message

track_manager_sessions = {}


def get_short_lang(stream):
    tags = stream.get("tags") or {}
    lang = tags.get("language") or ""
    title = tags.get("title") or ""

    code = lang.strip() or title.strip() or "und"
    code_lower = code.lower()

    mapping = {
        "tel": "Tel", "te": "Tel", "telugu": "Tel",
        "tam": "Tam", "ta": "Tam", "tamil": "Tam",
        "hin": "Hin", "hi": "Hin", "hindi": "Hin",
        "eng": "Eng", "en": "Eng", "english": "Eng",
        "kan": "Kan", "kn": "Kan", "kannada": "Kan",
        "mal": "Mal", "ml": "Mal", "malayalam": "Mal",
        "mar": "Mar", "mr": "Mar", "marathi": "Mar",
        "ben": "Ben", "bn": "Ben", "bengali": "Ben",
        "pan": "Pan", "pa": "Pan", "punjabi": "Pan",
        "guj": "Guj", "gu": "Guj", "gujarati": "Guj",
        "ori": "Ori", "or": "Ori", "odia": "Ori",
        "jpn": "Jpn", "ja": "Jpn", "japanese": "Jpn", "jap": "Jpn",
        "kor": "Kor", "ko": "Kor", "korean": "Kor",
        "chi": "Chi", "zh": "Chi", "zho": "Chi", "chinese": "Chi",
        "spa": "Spa", "es": "Spa", "spanish": "Spa",
        "fre": "Fre", "fra": "Fre", "fr": "Fre", "french": "Fre",
        "ger": "Ger", "deu": "Ger", "de": "Ger", "german": "Ger",
        "rus": "Rus", "ru": "Rus", "russian": "Rus",
        "ita": "Ita", "it": "Ita", "italian": "Ita",
        "und": "Und", "unk": "Und", "unknown": "Und",
    }

    if code_lower in mapping:
        return mapping[code_lower]

    for k, v in mapping.items():
        if k in code_lower:
            return v

    with suppress(Exception):
        from langcodes import Language
        l_obj = Language.get(code)
        if l_obj and l_obj.is_valid():
            autonym = l_obj.autonym() or l_obj.display_name()
            if autonym:
                return autonym[:3].capitalize()

    clean_code = sub(r"[^a-zA-Z]", "", code)
    if clean_code:
        return clean_code[:3].capitalize()
    return "Und"


def format_tm_ui(session):
    mid = session["mid"]
    files = session["files"]
    view_mode = session["view_mode"]
    page = session["page"]
    page_size = session.get("page_size", 5)
    cur_idx = session.get("current_file_idx", 0)
    is_multi = session["is_multi"]

    total_files = len(files)
    total_pages = max(1, (total_files + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    session["page"] = page

    buttons = ButtonMaker()

    if view_mode == "list":
        start_i = (page - 1) * page_size
        end_i = min(start_i + page_size, total_files)
        page_files = files[start_i:end_i]

        lines = [
            "<b>📂 Track Manager - Files List</b>\n",
            f"• <b>Total Files:</b> {total_files}",
            f"• <b>Page:</b> {page}/{total_pages}\n",
            "<b>Track Summary:</b>",
        ]

        for i, f in enumerate(page_files, start=start_i + 1):
            aud_str_list = []
            for pos in f["audio_order"]:
                if pos in f["selected_audio"]:
                    lang = f["audio_tracks"][pos]["short_lang"]
                    aud_str_list.append(lang)
            aud_str = ", ".join(aud_str_list) if aud_str_list else "None"

            sub_str_list = []
            for pos in f["sub_order"]:
                if pos in f["selected_sub"]:
                    lang = f["sub_tracks"][pos]["short_lang"]
                    sub_str_list.append(lang)
            sub_str = ", ".join(sub_str_list) if sub_str_list else "None"

            lines.append(f"{i}. <code>{escape(f['name'])}</code>")
            lines.append(f"   ↳ Audio: <b>{escape(aud_str)}</b>")
            lines.append(f"   ↳ Subtitle: <b>{escape(sub_str)}</b>")

        caption = "\n".join(lines)

        # Pagination in header (h_cols=3)
        if total_pages > 1:
            prev_p = page - 1 if page > 1 else total_pages
            next_p = page + 1 if page < total_pages else 1
            buttons.data_button("◀️ Prev", f"tmcb page {mid} {prev_p}", position="header")
            buttons.data_button(f"Page {page}/{total_pages}", "tmcb dummy", position="header")
            buttons.data_button("Next ▶️", f"tmcb page {mid} {next_p}", position="header")

        # Main controls in default (b_cols=1)
        buttons.data_button("🔄 Apply to All", f"tmcb apply_all {mid}", position="default")

        # Last row in footer (f_cols=3): Cancel (left), Select File (middle), Done (right)
        buttons.data_button("❌ Cancel", f"tmcb cancel {mid}", position="footer")
        buttons.data_button("📁 Select File", f"tmcb select_file {mid}", position="footer")
        buttons.data_button("✅ Done", f"tmcb done {mid}", position="footer")

        return caption, buttons.build_menu(b_cols=1, h_cols=3, f_cols=3)

    elif view_mode == "select_file":
        start_i = (page - 1) * page_size
        end_i = min(start_i + page_size, total_files)
        page_files = files[start_i:end_i]

        caption = f"<b>📂 Select a File to Edit Tracks:</b>\n[Page {page}/{total_pages}]"

        for i, f in enumerate(page_files, start=start_i):
            buttons.data_button(f"{i + 1}. {f['name'][:30]}", f"tmcb file {mid} {i}", position="default")

        if total_pages > 1:
            prev_p = page - 1 if page > 1 else total_pages
            next_p = page + 1 if page < total_pages else 1
            buttons.data_button("◀️ Prev", f"tmcb page {mid} {prev_p}", position="header")
            buttons.data_button(f"Page {page}/{total_pages}", "tmcb dummy", position="header")
            buttons.data_button("Next ▶️", f"tmcb page {mid} {next_p}", position="header")

        buttons.data_button("◀️ Back", f"tmcb back {mid}", position="footer")
        return caption, buttons.build_menu(b_cols=1, h_cols=3, f_cols=1)

    elif view_mode in ("audio", "sub"):
        cur_file = files[cur_idx] if 0 <= cur_idx < len(files) else files[0]
        fname = cur_file["name"]

        is_aud = (view_mode == "audio")
        tracks = cur_file["audio_tracks"] if is_aud else cur_file["sub_tracks"]
        order = cur_file["audio_order"] if is_aud else cur_file["sub_order"]
        selected = cur_file["selected_audio"] if is_aud else cur_file["selected_sub"]

        mode_title = "🎵 Audio Track Selection" if is_aud else "💬 Subtitle Track Selection"

        lines = [
            f"<b>{mode_title}</b>\n",
            f"• <b>File:</b> <code>{escape(fname)}</code>\n",
            "<b>Available Tracks:</b>",
        ]

        if not tracks:
            lines.append("<i>No tracks available</i>")
        else:
            for display_pos, pos in enumerate(order, start=1):
                t = tracks[pos]
                status = "✓" if pos in selected else "✗"
                lang_disp = t["short_lang"]
                lines.append(f"{display_pos}. {lang_disp} [{status}]")

        caption = "\n".join(lines)

        # First column: Available tracks with short language names (b_cols=1)
        for display_pos, pos in enumerate(order, start=1):
            t = tracks[pos]
            status = "✓" if pos in selected else "✗"
            btn_label = f"{display_pos}. {t['short_lang']} [{status}]"
            toggle_action = "toggle_aud" if is_aud else "toggle_sub"
            buttons.data_button(btn_label, f"tmcb {toggle_action} {mid} {pos}", position="default")

        # Up and Down reorder buttons below track list in f_body (fb_cols=2)
        if len(order) > 1:
            reorder_action = "move_aud" if is_aud else "move_sub"
            for display_pos in range(len(order)):
                up_cb = f"tmcb {reorder_action} {mid} {display_pos} -1" if display_pos > 0 else "tmcb dummy"
                dn_cb = f"tmcb {reorder_action} {mid} {display_pos} 1" if display_pos < len(order) - 1 else "tmcb dummy"
                buttons.data_button(f"#{display_pos + 1} ⬆️", up_cb, position="f_body")
                buttons.data_button(f"#{display_pos + 1} ⬇️", dn_cb, position="f_body")

        # Footer controls
        if is_aud:
            buttons.data_button("💬 Subtitles", f"tmcb view {mid} sub", position="footer")
        else:
            buttons.data_button("🎵 Audio", f"tmcb view {mid} audio", position="footer")

        if is_multi:
            buttons.data_button("🔄 Apply to All", f"tmcb apply_all {mid}", position="footer")
            buttons.data_button("◀️ Back", f"tmcb back {mid}", position="footer")

        buttons.data_button("✅ Done", f"tmcb done {mid}", position="footer")

        footer_cols = 3 if is_multi else 2
        return caption, buttons.build_menu(b_cols=1, fb_cols=2, f_cols=footer_cols)


@new_task
async def tm_callback(client, query: CallbackQuery):
    data = query.data.split()
    cmd = data[1] if len(data) > 1 else ""

    if cmd == "dummy":
        return await query.answer()

    mid = int(data[2]) if len(data) > 2 and data[2].isdigit() else 0
    session = track_manager_sessions.get(mid)

    if not session:
        return await query.answer("Track Manager session expired!", show_alert=True)

    if query.from_user.id != session["user_id"]:
        return await query.answer("This menu is not for you!", show_alert=True)

    files = session["files"]
    cur_idx = session.get("current_file_idx", 0)

    if cmd == "page":
        target_page = int(data[3])
        session["page"] = target_page
        await query.answer(f"Page {target_page}")
        caption, markup = format_tm_ui(session)
        await edit_message(session["msg"], caption, markup)

    elif cmd == "select_file":
        session["view_mode"] = "select_file"
        await query.answer()
        caption, markup = format_tm_ui(session)
        await edit_message(session["msg"], caption, markup)

    elif cmd == "file":
        target_f_idx = int(data[3])
        session["current_file_idx"] = target_f_idx
        session["view_mode"] = "audio"
        await query.answer(f"Editing file #{target_f_idx + 1}")
        caption, markup = format_tm_ui(session)
        await edit_message(session["msg"], caption, markup)

    elif cmd == "view":
        target_view = data[3]
        session["view_mode"] = target_view
        await query.answer()
        caption, markup = format_tm_ui(session)
        await edit_message(session["msg"], caption, markup)

    elif cmd == "toggle_aud":
        track_pos = int(data[3])
        cur_file = files[cur_idx] if 0 <= cur_idx < len(files) else files[0]
        if track_pos in cur_file["selected_audio"]:
            cur_file["selected_audio"].remove(track_pos)
            await query.answer("Audio track deselected")
        else:
            cur_file["selected_audio"].add(track_pos)
            await query.answer("Audio track selected")
        caption, markup = format_tm_ui(session)
        await edit_message(session["msg"], caption, markup)

    elif cmd == "toggle_sub":
        track_pos = int(data[3])
        cur_file = files[cur_idx] if 0 <= cur_idx < len(files) else files[0]
        if track_pos in cur_file["selected_sub"]:
            cur_file["selected_sub"].remove(track_pos)
            await query.answer("Subtitle track deselected")
        else:
            cur_file["selected_sub"].add(track_pos)
            await query.answer("Subtitle track selected")
        caption, markup = format_tm_ui(session)
        await edit_message(session["msg"], caption, markup)

    elif cmd == "move_aud":
        display_pos = int(data[3])
        direction = int(data[4])
        target_disp_pos = display_pos + direction
        cur_file = files[cur_idx] if 0 <= cur_idx < len(files) else files[0]
        order = cur_file["audio_order"]
        if 0 <= display_pos < len(order) and 0 <= target_disp_pos < len(order):
            order[display_pos], order[target_disp_pos] = order[target_disp_pos], order[display_pos]
            await query.answer("Audio track reordered")
            caption, markup = format_tm_ui(session)
            await edit_message(session["msg"], caption, markup)

    elif cmd == "move_sub":
        display_pos = int(data[3])
        direction = int(data[4])
        target_disp_pos = display_pos + direction
        cur_file = files[cur_idx] if 0 <= cur_idx < len(files) else files[0]
        order = cur_file["sub_order"]
        if 0 <= display_pos < len(order) and 0 <= target_disp_pos < len(order):
            order[display_pos], order[target_disp_pos] = order[target_disp_pos], order[display_pos]
            await query.answer("Subtitle track reordered")
            caption, markup = format_tm_ui(session)
            await edit_message(session["msg"], caption, markup)

    elif cmd == "apply_all":
        cur_file = files[cur_idx] if 0 <= cur_idx < len(files) else files[0]

        # Selected audio short languages in order
        target_aud_langs = []
        for pos in cur_file["audio_order"]:
            if pos in cur_file["selected_audio"]:
                target_aud_langs.append(cur_file["audio_tracks"][pos]["short_lang"])

        # Selected sub short languages in order
        target_sub_langs = []
        for pos in cur_file["sub_order"]:
            if pos in cur_file["selected_sub"]:
                target_sub_langs.append(cur_file["sub_tracks"][pos]["short_lang"])

        for f in files:
            # Apply audio rules
            new_aud_order = []
            new_aud_sel = set()
            used_aud = set()

            for lang in target_aud_langs:
                for pos, track in enumerate(f["audio_tracks"]):
                    if pos not in used_aud and track["short_lang"] == lang:
                        new_aud_order.append(pos)
                        new_aud_sel.add(pos)
                        used_aud.add(pos)
                        break

            if not new_aud_sel and cur_file["audio_tracks"] and f["audio_tracks"]:
                for pos in cur_file["audio_order"]:
                    if pos < len(f["audio_tracks"]):
                        new_aud_order.append(pos)
                        if pos in cur_file["selected_audio"]:
                            new_aud_sel.add(pos)
                        used_aud.add(pos)

            # Add remaining audio tracks at the end as unselected
            for pos in range(len(f["audio_tracks"])):
                if pos not in used_aud:
                    new_aud_order.append(pos)

            f["audio_order"] = new_aud_order
            f["selected_audio"] = new_aud_sel

            # Apply sub rules
            new_sub_order = []
            new_sub_sel = set()
            used_sub = set()

            for lang in target_sub_langs:
                for pos, track in enumerate(f["sub_tracks"]):
                    if pos not in used_sub and track["short_lang"] == lang:
                        new_sub_order.append(pos)
                        new_sub_sel.add(pos)
                        used_sub.add(pos)
                        break

            if not new_sub_sel and cur_file["sub_tracks"] and f["sub_tracks"]:
                for pos in cur_file["sub_order"]:
                    if pos < len(f["sub_tracks"]):
                        new_sub_order.append(pos)
                        if pos in cur_file["selected_sub"]:
                            new_sub_sel.add(pos)
                        used_sub.add(pos)

            for pos in range(len(f["sub_tracks"])):
                if pos not in used_sub:
                    new_sub_order.append(pos)

            f["sub_order"] = new_sub_order
            f["selected_sub"] = new_sub_sel

        await query.answer("Applied track selection/order rules to all files!", show_alert=True)
        caption, markup = format_tm_ui(session)
        await edit_message(session["msg"], caption, markup)

    elif cmd == "back":
        session["view_mode"] = "list"
        await query.answer()
        caption, markup = format_tm_ui(session)
        await edit_message(session["msg"], caption, markup)

    elif cmd == "cancel":
        await query.answer("Track Manager cancelled")
        fut = session.get("future")
        if fut and not fut.done():
            fut.set_result(False)

    elif cmd == "done":
        await query.answer("Applying track choices...")
        fut = session.get("future")
        if fut and not fut.done():
            fut.set_result(True)


async def proceed_track_manager(listener, dl_path, gid):
    if not dl_path or not await aiopath.exists(dl_path):
        return dl_path

    # Discover media files
    all_files = []
    if listener.is_file or await aiopath.isfile(dl_path):
        is_vid, is_aud, _ = await get_document_type(dl_path)
        if is_vid or is_aud:
            all_files.append(dl_path)
    else:
        for dirpath, _, files in await sync_to_async(walk, dl_path, topdown=False):
            for file_ in files:
                fp = ospath.join(dirpath, file_)
                is_vid, is_aud, _ = await get_document_type(fp)
                if is_vid or is_aud:
                    all_files.append(fp)

    if not all_files:
        LOGGER.info("Track Manager: No media files found to inspect.")
        return dl_path

    ffmpeg = FFMpeg(listener)
    files_data = []

    for fp in all_files:
        streams = await ffmpeg.get_streams(fp)
        if not streams:
            continue

        aud_streams = [s for s in streams if s.get("codec_type") == "audio"]
        sub_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

        audio_tracks = [
            {
                "index": s.get("index"),
                "codec": s.get("codec_name"),
                "short_lang": get_short_lang(s),
                "title": s.get("tags", {}).get("title", ""),
                "full_lang": s.get("tags", {}).get("language", ""),
            }
            for s in aud_streams
        ]

        sub_tracks = [
            {
                "index": s.get("index"),
                "codec": s.get("codec_name"),
                "short_lang": get_short_lang(s),
                "title": s.get("tags", {}).get("title", ""),
                "full_lang": s.get("tags", {}).get("language", ""),
            }
            for s in sub_streams
        ]

        files_data.append(
            {
                "path": fp,
                "name": ospath.basename(fp),
                "audio_tracks": audio_tracks,
                "sub_tracks": sub_tracks,
                "audio_order": list(range(len(audio_tracks))),
                "sub_order": list(range(len(sub_tracks))),
                "selected_audio": set(range(len(audio_tracks))),
                "selected_sub": set(range(len(sub_tracks))),
            }
        )

    if not files_data:
        LOGGER.info("Track Manager: No audio/subtitle streams found.")
        return dl_path

    mid = listener.mid
    user_id = listener.user_id
    fut = bot_loop.create_future()

    session = {
        "mid": mid,
        "user_id": user_id,
        "dl_path": dl_path,
        "gid": gid,
        "is_multi": len(files_data) > 1,
        "files": files_data,
        "current_file_idx": 0,
        "view_mode": "list" if len(files_data) > 1 else "audio",
        "page": 1,
        "page_size": 5,
        "future": fut,
    }

    track_manager_sessions[mid] = session

    caption, markup = format_tm_ui(session)

    try:
        msg = await send_message(listener.message, caption, markup)
    except Exception as e:
        LOGGER.error(f"Failed to send Track Manager message: {e}")
        track_manager_sessions.pop(mid, None)
        return dl_path

    session["msg"] = msg

    try:
        res = await wait_for(fut, timeout=600)
    except AsyncTimeoutError:
        LOGGER.info(f"Track Manager timed out for {mid}. Proceeding with default track selection.")
        res = True
    finally:
        track_manager_sessions.pop(mid, None)
        await delete_message(msg)

    if not res:
        LOGGER.info("Track Manager cancelled by user.")
        return dl_path

    # Execute FFmpeg modifications for each file
    for f in files_data:
        fp = f["path"]
        aud_tracks = f["audio_tracks"]
        sub_tracks = f["sub_tracks"]
        aud_order = f["audio_order"]
        sub_order = f["sub_order"]
        sel_aud = f["selected_audio"]
        sel_sub = f["selected_sub"]

        # Check if modification is needed
        aud_modified = (
            len(sel_aud) != len(aud_tracks)
            or aud_order != list(range(len(aud_tracks)))
        )
        sub_modified = (
            len(sel_sub) != len(sub_tracks)
            or sub_order != list(range(len(sub_tracks)))
        )

        if not aud_modified and not sub_modified:
            continue

        out_path = f"{fp}.tm_out.mkv"
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", fp, "-map", "0:v?"]

        # Map selected audio streams in order
        for pos in aud_order:
            if pos in sel_aud:
                s_idx = aud_tracks[pos]["index"]
                cmd.extend(["-map", f"0:{s_idx}"])

        # Map selected subtitle streams in order
        for pos in sub_order:
            if pos in sel_sub:
                s_idx = sub_tracks[pos]["index"]
                cmd.extend(["-map", f"0:{s_idx}"])

        cmd.extend(["-c", "copy", out_path])

        res_code, err, code = await cmd_exec(cmd)
        if code == 0 and await aiopath.exists(out_path):
            await move(out_path, fp)
            LOGGER.info(f"Track Manager successfully updated tracks for {fp}")
        else:
            LOGGER.error(f"Track Manager FFmpeg error for {fp}: {err}")
            if await aiopath.exists(out_path):
                await remove(out_path)

    return dl_path
