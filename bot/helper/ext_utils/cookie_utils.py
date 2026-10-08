"""Make browser-extension cookie exports safe for yt-dlp.

Extensions ("Get cookies.txt", "EditThisCookie", ...) produce files that yt-dlp
loads only partly or not at all: CRLF line endings, spaces instead of tabs,
JSON exports, missing Netscape header, stray/garbled lines. Everything here is
idempotent and never raises; a file that is already clean is left untouched.
"""

from json import loads
from logging import getLogger
from os import path as ospath
from time import time

LOGGER = getLogger(__name__)

HEADER = "# Netscape HTTP Cookie File"
_LOGIN_COOKIES = {
    "SID",
    "SAPISID",
    "LOGIN_INFO",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
}
_cache = {}  # path -> (mtime, size, report)


def _bool(v):
    return "TRUE" if str(v).strip().upper() in ("TRUE", "1", "YES") else "FALSE"


def _expiry(v):
    try:
        return str(int(float(str(v).strip())))
    except (TypeError, ValueError):
        return "0"


def _from_json(text):
    data = loads(text)
    if isinstance(data, dict):
        data = data.get("cookies", [])
    rows = []
    for c in data:
        if not isinstance(c, dict) or not c.get("name") or not c.get("domain"):
            continue
        domain = str(c["domain"])
        if c.get("httpOnly"):
            domain = f"#HttpOnly_{domain}"
        host_only = c.get("hostOnly")
        include_sub = (
            "FALSE" if host_only else ("TRUE" if str(c["domain"]).startswith(".") else "FALSE")
        )
        rows.append(
            "\t".join(
                [
                    domain,
                    include_sub,
                    str(c.get("path") or "/"),
                    _bool(c.get("secure")),
                    _expiry(c.get("expirationDate", c.get("expires", 0))),
                    str(c["name"]),
                    str(c.get("value", "")),
                ]
            )
        )
    return rows


def _from_netscape(text):
    rows, dropped = [], 0
    for raw in text.split("\n"):
        line = raw.strip("\r\n ").lstrip("﻿")
        if not line:
            continue
        if line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue  # comment / header, rewritten below
        parts = line.split("\t")
        if len(parts) < 6 or len(parts) > 7:
            parts = line.split(None, 6)  # extension used spaces
        if len(parts) == 6:
            parts.append("")  # cookie with empty value
        if len(parts) != 7:
            dropped += 1
            continue
        domain, sub, cpath, secure, exp, name, value = parts
        if not name.strip() or not domain.strip():
            dropped += 1
            continue
        rows.append(
            "\t".join(
                [domain.strip(), _bool(sub), cpath.strip() or "/", _bool(secure), _expiry(exp), name.strip(), value]
            )
        )
    return rows, dropped


def normalize_cookie_file(file_path):
    """Rewrite file_path as clean Netscape format. Returns a report dict."""
    report = {"total": 0, "dropped": 0, "google": 0, "login": 0, "login_expired": 0, "fixed": False, "error": ""}
    try:
        with open(file_path, "rb") as f:
            original = f.read().decode("utf-8-sig", errors="ignore")
        text = original.replace("\r\n", "\n").replace("\r", "\n")
        stripped = text.lstrip()
        if stripped[:1] in ("[", "{"):
            try:
                rows, dropped = _from_json(stripped), 0
            except Exception as e:
                report["error"] = f"Unreadable JSON cookie file: {e}"
                return report
        else:
            rows, dropped = _from_netscape(text)
        report["dropped"] = dropped
        report["total"] = len(rows)
        now = time()
        for row in rows:
            domain, _, _, _, exp, name, _ = row.split("\t")
            d = domain.replace("#HttpOnly_", "").lower()
            if d.endswith("youtube.com") or d.endswith("google.com"):
                report["google"] += 1
                if name in _LOGIN_COOKIES:
                    report["login"] += 1
                    if exp != "0" and int(exp) < now:
                        report["login_expired"] += 1
        if rows:
            cleaned = HEADER + "\n" + "\n".join(rows) + "\n"
            if cleaned != original:
                with open(file_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(cleaned)
                report["fixed"] = True
                LOGGER.info(f"Cookie file normalized: {file_path} ({len(rows)} cookies)")
        else:
            report["error"] = "No valid cookie lines found (expected Netscape cookies.txt)."
    except Exception as e:
        report["error"] = str(e)
    return report


def ensure_cookie_file(file_path):
    """Normalize once per file version (cheap to call before every download)."""
    if not file_path or not ospath.exists(file_path):
        return {}
    try:
        st = ospath.getmtime(file_path), ospath.getsize(file_path)
    except OSError:
        return {}
    cached = _cache.get(file_path)
    if cached and cached[0] == st:
        return cached[1]
    report = normalize_cookie_file(file_path)
    with_new = (ospath.getmtime(file_path), ospath.getsize(file_path))
    _cache[file_path] = (with_new, report)
    return report


def describe_cookie_report(report):
    """One-line human summary, used on upload and in error messages."""
    if not report:
        return "no cookie file"
    if report.get("error"):
        return f"cookie file problem: {report['error']}"
    if not report.get("login"):
        login = "NO YouTube login cookies found (export while logged in to YouTube)"
    elif report.get("login") == report.get("login_expired"):
        login = "YouTube login cookies are EXPIRED (re-export)"
    else:
        login = "YouTube login cookies present"
    extra = f", {report['dropped']} bad line(s) removed" if report.get("dropped") else ""
    fixed = ", format auto-fixed" if report.get("fixed") else ""
    return f"{report['total']} cookies ({report['google']} Google/YouTube); {login}{extra}{fixed}"


SOCIAL_COOKIE_PLATFORMS = {
    "facebook": ("Facebook", ("facebook.com", "fb.com")),
    "instagram": ("Instagram", ("instagram.com",)),
    "x": ("X / Twitter", ("x.com", "twitter.com")),
    "tiktok": ("TikTok", ("tiktok.com",)),
    "reddit": ("Reddit", ("reddit.com",)),
    "generic": ("Generic Social", ()),
}


def social_cookie_path(user_id, platform):
    """Return the per-user cookie path for a social platform."""
    platform = str(platform).lower().strip()
    if platform not in SOCIAL_COOKIE_PLATFORMS:
        platform = "generic"
    return f"cookies/{user_id}/social_{platform}.txt"


def get_social_platform(url):
    """Map a URL to a cookie profile. Unknown yt-dlp sites use generic."""
    from urllib.parse import urlparse
    host = (urlparse(str(url)).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    for platform, (_, domains) in SOCIAL_COOKIE_PLATFORMS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return platform
    if host.endswith("youtube.com") or host.endswith("youtu.be"):
        return "youtube"
    return "generic"


def get_social_cookie_file(user_id, url, user_dict=None):
    """Prefer a platform-specific cookie, then generic, then the legacy user cookie."""
    user_dict = user_dict or {}
    platform = get_social_platform(url)
    candidates = []
    if platform != "youtube":
        candidates.append(social_cookie_path(user_id, platform))
    candidates.append(social_cookie_path(user_id, "generic"))
    legacy = user_dict.get("USER_COOKIE_FILE", "")
    if legacy:
        candidates.append(legacy)
    if ospath.exists("cookies.txt"):
        candidates.append("cookies.txt")
    for candidate in candidates:
        if candidate and ospath.exists(candidate):
            ensure_cookie_file(candidate)
            return candidate
    return None
