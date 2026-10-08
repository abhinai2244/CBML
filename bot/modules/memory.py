from asyncio import all_tasks
from time import time

from pyrogram.enums import ButtonStyle

from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.mem_guard import (
    budget,
    limit_bytes,
    monitor,
    profiler,
    readable,
    snapshot,
    trim_caches,
)
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)


def _wz(title, rows, note=""):
    lines = [f"<b>🧠 {title}</b>", ""]
    body = []
    for key, value in rows:
        body.append(f"• <b>{key}:</b> {value}")
    lines.append(f"<blockquote>{'<br>'.join(body)}</blockquote>" if body else "")
    if note:
        lines.append(f"<blockquote><b>Note:</b> {note}</blockquote>")
    return "\n".join(lines)


def _trend():
    points = monitor.samples[-6:]
    if len(points) < 2:
        return "not enough samples yet"
    first, last = points[0][1], points[-1][1]
    span = max(1, points[-1][0] - points[0][0])
    delta = last - first
    arrow = "steady" if abs(delta) < 2 * 1024 * 1024 else ("rising" if delta > 0 else "falling")
    return f"{arrow} ({readable(abs(delta))} over {span}s)"


def _overview():
    snap = snapshot()
    rows = [
        ("Resident RSS", readable(snap["rss"])),
        ("Instance Limit", readable(snap["limit"])),
        ("Memory Pressure", f"{snap['pressure'] * 100:.0f}%"),
        ("Peak Resident", readable(snap["peak"])),
        ("Available Free", readable(snap["available"])),
        ("Usage Trend", _trend()),
        (
            "Active Transfers",
            f"{readable(snap['budget']['used'])} of "
            f"{readable(snap['budget']['limit'])}"
            f" (peak {readable(snap['budget']['peak'])}, "
            f"{snap['budget']['waits']} wait(s))",
        ),
        ("Caches Total", readable(snap["cache_total"])),
        ("Auto Trims", str(snap["trims"])),
        ("Profiler Status", "ON" if snap["profiling"] else "OFF"),
    ]
    return snap, rows


def _menu(user_id, view="main"):
    buttons = ButtonMaker()
    if view == "main":
        snap, rows = _overview()
        buttons.data_button("🔄 Refresh", f"mem {user_id} main", position="header")
        buttons.data_button("📊 Breakdown", f"mem {user_id} detail")
        if profiler.running:
            buttons.data_button("📈 Top Allocations", f"mem {user_id} top")
            buttons.data_button(
                "⏹️ Stop Profiler", f"mem {user_id} proff", style=ButtonStyle.DANGER
            )
        else:
            buttons.data_button(
                "▶️ Start Profiler", f"mem {user_id} pron", style=ButtonStyle.PRIMARY
            )
        buttons.data_button("🧹 Trim Caches", f"mem {user_id} trim")
        buttons.data_button(
            "❌ Close", f"mem {user_id} close", position="footer", style=ButtonStyle.DANGER
        )
        note = ""
        if snap["pressure"] >= 0.85:
            note = "High memory pressure. Caches are being trimmed automatically."
        elif not snap["profiling"]:
            note = "Start profiler to monitor allocation sources during heavy load."
        return _wz("Memory Overview", rows, note), buttons.build_menu(2)

    if view == "detail":
        snap = snapshot()
        rows = []
        for name, size in sorted(snap["caches"].items(), key=lambda kv: -kv[1]):
            rows.append((name, readable(size)))
        if not rows:
            rows = [("Caches", "none registered")]
        try:
            rows.append(("Async Tasks", str(len(all_tasks()))))
        except RuntimeError:
            pass
        rows.append(("GC Counts", " / ".join(str(c) for c in snap["gc"]["counts"])))
        if Config.MEM_DEEP_STATS:
            rows.append(("Tracked Objects", f"{snap['gc']['objects']:,}"))
        buttons.data_button("◀️ Back", f"mem {user_id} main", position="footer")
        buttons.data_button(
            "❌ Close", f"mem {user_id} close", position="footer", style=ButtonStyle.DANGER
        )
        note = "" if Config.MEM_DEEP_STATS else "Set MEM_DEEP_STATS for object counts."
        return _wz("Memory Breakdown", rows, note), buttons.build_menu(2)

    if view == "top":
        rows = []
        for row in profiler.top(12):
            rows.append((row["where"], f"{readable(row['size'])} ({row['count']} blocks)"))
        if not rows:
            rows = [("Profiler", "not running")]
        buttons.data_button("🔄 Refresh", f"mem {user_id} top", position="header")
        buttons.data_button("◀️ Back", f"mem {user_id} main", position="footer")
        buttons.data_button(
            "❌ Close", f"mem {user_id} close", position="footer", style=ButtonStyle.DANGER
        )
        seen = f"since {int(time() - profiler.started_at)}s ago" if profiler.started_at else ""
        return (
            _wz("Top Memory Allocations", rows, f"size / blocks {seen}".strip()),
            buttons.build_menu(1),
        )

    return "<b>Unknown memory view.</b>", buttons.build_menu(1)


@new_task
async def memory_stats(_, message):
    text, markup = _menu(message.from_user.id)
    await send_message(message, text, markup)


@new_task
async def memory_callback(_, query):
    user_id = query.from_user.id
    data = query.data.split()
    if len(data) < 3 or user_id != int(data[1]):
        return await query.answer("This menu is not for you!", show_alert=True)

    action = data[2]
    if action == "close":
        await query.answer()
        await delete_message(query.message.reply_to_message)
        return await delete_message(query.message)

    if action == "pron":
        started = profiler.start()
        await query.answer(
            "Profiler started. Check Top Allocations during load."
            if started
            else "Profiler already running.",
            show_alert=started,
        )
    elif action == "proff":
        profiler.stop()
        await query.answer("Profiler stopped.")
    elif action == "trim":
        before = snapshot()["rss"]
        freed = trim_caches(aggressive=True)
        from gc import collect

        collected = collect()
        after = snapshot()["rss"]
        await query.answer(
            f"Freed {readable(freed)} of caches and {collected} objects. "
            f"Resident RSS: {readable(before)} -> {readable(after)}.",
            show_alert=True,
        )
    else:
        await query.answer()

    view = action if action in ("main", "detail", "top") else "main"
    text, markup = _menu(user_id, view)
    await edit_message(query.message, text, markup)


def memory_report():
    snap = snapshot()
    return (
        f"resident {readable(snap['rss'])} of {readable(limit_bytes())} "
        f"({snap['pressure'] * 100:.0f}%), transfers "
        f"{readable(snap['budget']['used'])}/{readable(budget.limit)}, "
        f"caches {readable(snap['cache_total'])}"
    )
