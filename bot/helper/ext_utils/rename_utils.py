import re
from os import path as ospath

_QUALITY_REGEX = re.compile(
    r"\b(2160p|1080p|720p|480p|360p|240p|4k|uhd|fhd|hd|bluray|blu-ray|web-dl|webdl|webrip|hdtv|dvdrip|hdrip|brrip|remux)\b",
    re.IGNORECASE,
)
_SEASON_REGEX = re.compile(
    r"\b(S\d+|Season\s*\d+|\d+st\s*Season|\d+nd\s*Season|\d+rd\s*Season|\d+th\s*Season)\b",
    re.IGNORECASE,
)
_EPISODE_REGEX = re.compile(
    r"\b(E\d+|EP\d+|Episode\s*\d+|E[P]?\d+)\b",
    re.IGNORECASE,
)
_SEASON_EPISODE_REGEX = re.compile(
    r"\bS(\d+)E(\d+)\b|\b(\d+)x(\d+)\b",
    re.IGNORECASE,
)
_CODEC_REGEX = re.compile(
    r"\b(x264|x265|h264|h265|hevc|av1|vp9|10bit|8bit|12bit|hdr10\+|hdr10|hdr|dv|dolby\s*vision)\b",
    re.IGNORECASE,
)
_AUDIO_REGEX = re.compile(
    r"\b(aac|ac3|eac3|dts-hd|dts|truehd|atmos|flac|mp3|opus|2\.0|5\.1|7\.1|dual\s*audio|multi\s*audio|multi)\b",
    re.IGNORECASE,
)
_YEAR_REGEX = re.compile(r"\b(19\d\d|20\d\d)\b")
_LANGUAGE_REGEX = re.compile(
    r"\b(hindi|english|tamil|telugu|japanese|korean|spanish|french|german|multi|dual|esub|msub|sub)\b",
    re.IGNORECASE,
)


def extract_media_metadata(filename: str, caption: str = "", file_details: dict = None) -> dict:
    if file_details is None:
        file_details = {}

    combined_text = f"{filename}\n{caption}"
    base_name, ext = ospath.splitext(filename)
    ext = ext.lstrip(".")

    metadata = {
        "TITLE": None,
        "SEASON": None,
        "EPISODE": None,
        "QUALITY": None,
        "YEAR": None,
        "LANGUAGE": None,
        "CODEC": None,
        "AUDIO": None,
        "GROUP": None,
        "EXT": ext if ext else None,
    }

    # 1. Season & Episode
    se_match = _SEASON_EPISODE_REGEX.search(combined_text)
    if se_match:
        if se_match.group(1) and se_match.group(2):
            metadata["SEASON"] = f"S{int(se_match.group(1)):02d}"
            metadata["EPISODE"] = f"E{int(se_match.group(2)):02d}"
        elif se_match.group(3) and se_match.group(4):
            metadata["SEASON"] = f"S{int(se_match.group(3)):02d}"
            metadata["EPISODE"] = f"E{int(se_match.group(4)):02d}"

    if not metadata["SEASON"]:
        s_match = _SEASON_REGEX.search(combined_text)
        if s_match:
            s_str = s_match.group(1)
            num = re.search(r"\d+", s_str)
            metadata["SEASON"] = f"S{int(num.group()):02d}" if num else s_str

    if not metadata["EPISODE"]:
        e_match = _EPISODE_REGEX.search(combined_text)
        if e_match:
            e_str = e_match.group(1)
            num = re.search(r"\d+", e_str)
            metadata["EPISODE"] = f"E{int(num.group()):02d}" if num else e_str

    # 2. Quality
    q_match = _QUALITY_REGEX.search(combined_text)
    if q_match:
        metadata["QUALITY"] = q_match.group(1)

    # 3. Codec
    c_match = _CODEC_REGEX.search(combined_text)
    if c_match:
        metadata["CODEC"] = c_match.group(1)

    # 4. Audio
    a_match = _AUDIO_REGEX.search(combined_text)
    if a_match:
        metadata["AUDIO"] = a_match.group(1)

    # 5. Year
    y_match = _YEAR_REGEX.search(combined_text)
    if y_match:
        metadata["YEAR"] = y_match.group(1)

    # 6. Language
    l_match = _LANGUAGE_REGEX.search(combined_text)
    if l_match:
        metadata["LANGUAGE"] = l_match.group(1)

    # Languages from caption details if present
    if "Languages:" in caption or "🌐 Languages:" in caption:
        for line in caption.split("\n"):
            if "Languages:" in line:
                langs = line.split("Languages:", 1)[1].strip()
                if langs:
                    metadata["LANGUAGE"] = langs

    # 7. Extract Title
    metadata["TITLE"] = _detect_title(filename, caption, metadata)

    return metadata


def _detect_title(filename: str, caption: str, metadata: dict) -> str:
    sources = []
    if caption:
        first_line = caption.split("\n")[0].strip()
        # Clean extension if present in caption line
        if ospath.splitext(first_line)[1]:
            first_line = ospath.splitext(first_line)[0]
        sources.append(first_line)

    base_name = ospath.splitext(filename)[0]
    sources.append(base_name)

    for source in sources:
        cleaned = re.sub(r"[^\w\s\-\.\'\"]", " ", source)
        segments = [s.strip() for s in re.split(r"[\-|]", cleaned) if s.strip()]

        best_candidate = None
        best_score = -1

        for seg in segments:
            words = seg.split()
            valid_words = []
            for w in words:
                w_clean = w.strip(".-_")
                if not w_clean:
                    continue
                if (_QUALITY_REGEX.fullmatch(w_clean) or
                    _SEASON_REGEX.fullmatch(w_clean) or
                    _EPISODE_REGEX.fullmatch(w_clean) or
                    _CODEC_REGEX.fullmatch(w_clean) or
                    _AUDIO_REGEX.fullmatch(w_clean) or
                    _YEAR_REGEX.fullmatch(w_clean) or
                    _LANGUAGE_REGEX.fullmatch(w_clean) or
                    re.fullmatch(r"S\d+E\d+", w_clean, re.I) or
                    re.fullmatch(r"\d+x\d+", w_clean, re.I) or
                    w_clean.lower() in ("bluray", "blu-ray", "esub", "msub", "multi", "audio", "part", "size", "gb", "mb", "mkv", "mp4", "avi", "webm")):
                    continue
                valid_words.append(w_clean)

            candidate_title = " ".join(valid_words).strip(" -_")
            if len(candidate_title) > 2:
                score = len(candidate_title)
                if score > best_score:
                    best_score = score
                    best_candidate = candidate_title

        if best_candidate:
            best_candidate = re.sub(r"\bS\d+\b|\bE\d+\b", "", best_candidate, flags=re.I).strip(" -_")
            if best_candidate:
                return best_candidate

    return None


def format_auto_rename(format_template: str, metadata: dict) -> str:
    sentinel = "__MISSING_PLACEHOLDER__"

    formatted = format_template
    placeholders = ["TITLE", "SEASON", "EPISODE", "QUALITY", "YEAR", "LANGUAGE", "CODEC", "AUDIO", "GROUP", "EXT"]

    for ph in placeholders:
        val = metadata.get(ph)
        placeholder_tag = f"{{{ph}}}"
        if val is not None and str(val).strip():
            formatted = formatted.replace(placeholder_tag, str(val).strip())
        else:
            formatted = formatted.replace(placeholder_tag, sentinel)

    # Clean up empty brackets containing sentinel
    formatted = re.sub(r"\[\s*" + sentinel + r"\s*\]", "", formatted)
    formatted = re.sub(r"\(\s*" + sentinel + r"\s*\)", "", formatted)
    formatted = re.sub(r"\{\s*" + sentinel + r"\s*\}", "", formatted)

    # Remove sentinel
    formatted = formatted.replace(sentinel, "")

    # Clean up empty brackets leftover
    formatted = re.sub(r"\[\s*\]|\(\s*\)|\{\s*\}", "", formatted)

    # Collapse spaces
    formatted = re.sub(r"\s+", " ", formatted)

    # Clean up duplicate/dangling separators
    formatted = re.sub(r"\s*([\|\-\_:\/])\s*(\1\s*)+", r" \1 ", formatted)
    formatted = re.sub(r"^\s*[\|\-\_:\/]+\s*", "", formatted)
    formatted = re.sub(r"\s*[\|\-\_:\/]+\s*$", "", formatted)

    # Remove double separators like "- -" or "| -"
    formatted = re.sub(r"\s*[\-\|]\s*[\-\|]\s*", " - ", formatted)

    formatted = formatted.strip()

    # Append extension if EXT present in metadata
    ext = metadata.get("EXT")
    if ext and not formatted.endswith(f".{ext}"):
        formatted = f"{formatted}.{ext}"

    return formatted
