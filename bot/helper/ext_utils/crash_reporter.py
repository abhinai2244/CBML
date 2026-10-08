from collections import deque
from json import dumps as jdumps
from datetime import datetime
from gzip import compress as gzip_compress
from hashlib import sha256
from hmac import new as hmac_new
from logging import ERROR, Formatter, Handler, getLogger
from sys import platform, stderr
from time import time
from traceback import format_exception

from niquests import AsyncSession
from pytz import timezone as tz_lookup

from bot import LOGGER, bot_loop
from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import git_info
from bot.version import get_version

CRASH_REPORT_URL = "https://telemetry.wzmlx.com/api/v1/send-crash-report"
API_KEY = hmac_new(b"wzmlx-crash-report", Config.BOT_TOKEN.encode(), sha256).hexdigest()


class _LogCaptureHandler(Handler):
    def __init__(self, capacity=20):
        super().__init__(level=0)
        self.buffer = deque(maxlen=capacity)

    def emit(self, record):
        self.buffer.append(self.format(record))


_log_handler = _LogCaptureHandler()
_log_handler.setFormatter(
    Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
getLogger().addHandler(_log_handler)

_sending_report = False


class _ErrorTriggerHandler(Handler):
    _last_sent = {}
    _debounce = 300

    def emit(self, record):
        global _sending_report
        if _sending_report or record.levelno < ERROR:
            return
        if not Config.ENABLE_TELEMETRY:
            return
        exc_type = record.exc_info[0] if record.exc_info else None
        key = (exc_type.__name__ if exc_type else "no_exc", record.name)
        now = time()
        if now - self._last_sent.get(key, 0) < self._debounce:
            return
        self._last_sent[key] = now
        _sending_report = True
        try:
            exc_type, exc_value, exc_tb = record.exc_info or (None, None, None)
            if exc_type and exc_value:
                payload = _make_payload(exc_type, exc_value, exc_tb)
            else:
                payload = _make_payload(
                    type("LoggedError", (Exception,), {}),
                    Exception(record.getMessage()),
                    None,
                )
                payload["traceback"] = (
                    f"Logged at {record.pathname}:{record.lineno} in {record.funcName}"
                )
            bot_loop.create_task(_post_report(payload))
        finally:
            _sending_report = False


getLogger().addHandler(_ErrorTriggerHandler(level=ERROR))


def _make_payload(exc_type, exc_value, exc_traceback):
    tb_lines = format_exception(exc_type, exc_value, exc_traceback)
    return {
        "version": get_version(),
        "commit_message": git_info.commit_msg(),
        "commit_time": git_info.commit_time(),
        "exception": f"{exc_type.__name__}: {exc_value}",
        "traceback": "".join(tb_lines),
        "platform": platform,
        "timestamp": datetime.now(tz_lookup(Config.TIMEZONE)).isoformat(),
        "api_key": API_KEY,
    }


def send_unhandled_exception(exc_type, exc_value, exc_traceback):
    tb = "".join(format_exception(exc_type, exc_value, exc_traceback))
    print(tb, file=stderr)
    if not Config.ENABLE_TELEMETRY:
        return
    payload = _make_payload(exc_type, exc_value, exc_traceback)
    bot_loop.create_task(_post_report(payload))


def send_async_exception(context):
    exc = context.get("exception")
    if exc:
        tb = "".join(format_exception(type(exc), exc, exc.__traceback__))
        print(tb, file=stderr)
    if not Config.ENABLE_TELEMETRY:
        return
    if not exc:
        return
    payload = _make_payload(type(exc), exc, exc.__traceback__)
    message = context.get("message", "")
    if message:
        payload["logs"] = message
    bot_loop.create_task(_post_report(payload))


async def _upload_logs(log_lines):
    from .telegraph_helper import telegraph

    try:
        commit_msg = git_info.commit_msg()
        commit_time = git_info.commit_time()
        link_html = (
            f"<p>Commit: <b>{commit_msg}</b><br>Time: {commit_time}</p>"
            if commit_msg
            else ""
        )
        html = link_html + (
            "<pre>" + "".join(_esc_html(line) + "\n" for line in log_lines) + "</pre>"
        )
        page = await telegraph.create_page(title="Crash Logs", content=html)
        return page["url"]
    except Exception as e:
        LOGGER.warning(f"Failed to create logs page: {e}")
        return None


def _esc_html(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def _post_report(payload):
    try:
        recent_logs = list(_log_handler.buffer)
        if recent_logs:
            logs_url = await _upload_logs(recent_logs)
            if logs_url:
                payload["logs_url"] = logs_url
        encoded = jdumps(payload).encode()
        headers = {"Authorization": f"Bearer {API_KEY}"}
        if len(encoded) > 0x19000:
            encoded = gzip_compress(encoded)
            headers["Content-Encoding"] = "gzip"
        async with AsyncSession() as client:
            r = await client.post(CRASH_REPORT_URL, data=encoded, headers=headers, timeout=15)
        if r.status_code == 200:
            LOGGER.info("Crash report sent to WZML-X devs")
        else:
            LOGGER.warning(f"Crash report failed: HTTP {r.status_code}")
    except Exception as e:
        LOGGER.warning(f"Crash report failed: {e}")
