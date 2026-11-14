import re
import unicodedata
from functools import lru_cache
from typing import Final

from pydantic import BaseModel

from palimpsest.stealth.models import VectorType

TAG_LOW = 0xE0000
TAG_HIGH = 0xE007F
BIDI_CHARS = frozenset(
    [chr(c) for c in range(0x202A, 0x202F)] + [chr(c) for c in range(0x2066, 0x206A)]
)
ZERO_WIDTH_CHARS = frozenset(
    ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"]
    + [chr(c) for c in range(0xFE00, 0xFE10)]
)
INVISIBLE_CHARS = BIDI_CHARS | ZERO_WIDTH_CHARS
SUSPICIOUS_ALT_WORD_LIMIT = 15
PROSE_PARAM_MIN_WORDS = 8

_TAG_RUN = re.compile("[\U000e0000-\U000e007f]+")
_WORD = re.compile(r"\w+")

# Pre-signal only: conservative phrases aimed at an AI reader, not final classification.
_INSTRUCTION_CI = re.compile(
    r"system\s+(?:prompt|instruction|override|message|note)s?"
    r"|\[\s*system\b"
    r"|ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)"
    r"|disregard\b"
    r"|when\s+(?:summari[sz]ing|asked|answering)"
    r"|(?:return|output|respond\s+with|set)\s+\W*(?:audit_status|clean_pass|pass\b|verified)"
    r"|clean_pass"
    r"|(?:classify|mark|label|rate)\s+(?:this|the)\s+(?:edit|article|page|source|text)"
    r"|fact[\s-]?checker"
    r"|language\s+model"
    r"|you\s+(?:must|should)\s+(?:always\s+)?(?:state|say|output|respond|report)"
    r"|always\s+(?:state|say|report)\s+that",
    re.IGNORECASE,
)
_INSTRUCTION_CS = re.compile(r"\b(?:AI|LLM|LLMs|GPT|ChatGPT)\b")

_OPACITY_LIMIT = 0.05
_ALPHA_LIMIT = 0.05
_FONT_SIZE = re.compile(r"(\d*\.?\d+)\s*(px|pt|em|rem|%)?")
_LENGTH = re.compile(r"(-?\d*\.?\d+)\s*(px|pt|em|rem|%)?")
_IMPORTANT = re.compile(r"\s*!\s*important\s*")
_HEX_COLOR = re.compile(r"#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})")
_FUNC_COLOR = re.compile(r"rgba?\(([^)]*)\)")
_NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "red": (255, 0, 0),
    "lime": (0, 255, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "aqua": (0, 255, 255),
    "magenta": (255, 0, 255),
    "fuchsia": (255, 0, 255),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "silver": (192, 192, 192),
    "maroon": (128, 0, 0),
    "olive": (128, 128, 0),
    "purple": (128, 0, 128),
    "teal": (0, 128, 128),
    "navy": (0, 0, 128),
    "orange": (255, 165, 0),
}
# Font sizes below these limits are unreadable, per unit.
_TINY_FONT_LIMIT = {"px": 2.0, "pt": 1.5, "em": 0.1, "rem": 0.1, "%": 10.0}
_ARIA_HIDDEN = re.compile(r"aria-hidden\s*=\s*[\"']?\s*true", re.IGNORECASE)
_HIDDEN_ATTR = re.compile(
    r"(?:^|\s)hidden(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"']+))?(?=\s|$)"
)
_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
MAX_TEMPLATE_PASSES: Final = 20
MAX_TEMPLATE_SCAN_CHARS: Final = 200_000
_INTERWIKI = re.compile(r"\[\[[a-z]{2,3}(?:-[a-z]+)*:[^\]\n]*\]\]")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_OPEN_TAG = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)\b([^<>]*?)(/?)>")
_STYLE_ATTR = re.compile(r"style\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE)
_COLLAPSED_CLASS = re.compile(
    r"class\s*=\s*[\"'][^\"']*mw-collapsed[^\"']*[\"']", re.IGNORECASE
)
_SCRIPT = re.compile(
    r"<(script|style)\b([^<>]*)>(.*?)</\1\s*>", re.DOTALL | re.IGNORECASE
)
_ATTR_PAIR = re.compile(r"""(?:^|\s)([a-zA-Z][\w:.-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_WIKI_ALT = re.compile(r"\|\s*alt\s*=([^|\]}\n]*)")
_MEDIA_LINK = re.compile(
    r"\[\[\s*(?:file|image|tiedosto|kuva|bild|fichier|archivo)\s*:", re.IGNORECASE
)
_MEDIA_PARAMS = frozenset({"alt", "title", "caption", "description", "label"})
_A11Y_ATTRS = frozenset({"alt", "aria-label", "aria-description"})
_LEGACY_ATTRS = frozenset({"alt", "aria-label", "title"})
_TEXT_ATTRS = frozenset({"title", "placeholder"})
ATTRIBUTE_TEXT_MIN_WORDS = 4
_WIKI_TABLE_START = re.compile(r"^\{\|[^\n]*mw-collapsed[^\n]*$", re.MULTILINE)
_TABLE_MARKER = re.compile(r"^(\{\||\|\})", re.MULTILINE)
_TAG_STRIP = re.compile(r"<[^>]*>")


class TagPayload(BaseModel):
    decoded: str
    span: tuple[int, int]


class TagDecodeResult(BaseModel):
    sanitized_text: str
    decoded_tag_ascii: str
    payloads: list[TagPayload]


class ControlRun(BaseModel):
    span: tuple[int, int]
    is_bidi: bool


class ControlScanResult(BaseModel):
    sanitized_text: str
    count: int
    runs: list[ControlRun]


class HomoglyphToken(BaseModel):
    token: str
    span: tuple[int, int]
    scripts: list[str]


class QuarantinedItem(BaseModel):
    vector_type: VectorType
    span: tuple[int, int]
    raw_snippet: str
    hidden_text: str
    instruction_like: bool


class HiddenChannelResult(BaseModel):
    sanitized_human_text: str
    quarantined_items: list[QuarantinedItem]
    unscanned_span: tuple[int, int] | None = None
    # Prose template parameters (any language) that may not render; screened by
    # triage but not removed from the human text.
    screen_items: list[QuarantinedItem] = []


def looks_like_instruction(text: str) -> bool:
    return bool(_INSTRUCTION_CI.search(text) or _INSTRUCTION_CS.search(text))


def has_strong_instruction(text: str) -> bool:
    """Imperative phrasing only; bare AI/GPT mentions and topic words are not enough."""
    return any(
        not m.group().lower().startswith(("language", "fact"))
        for m in _INSTRUCTION_CI.finditer(text)
    )


def remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    out: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        if start > cursor:
            out.append(text[cursor:start])
        cursor = max(cursor, end)
    out.append(text[cursor:])
    return "".join(out)


def decode_unicode_tags(text: str) -> TagDecodeResult:
    payloads = [
        TagPayload(
            decoded="".join(
                chr(ord(c) - TAG_LOW)
                for c in m.group()
                if chr(ord(c) - TAG_LOW).isprintable()
            ),
            span=(m.start(), m.end()),
        )
        for m in _TAG_RUN.finditer(text)
    ]
    return TagDecodeResult(
        sanitized_text=_TAG_RUN.sub("", text),
        decoded_tag_ascii="".join(p.decoded for p in payloads),
        payloads=payloads,
    )


def scan_invisible_controls(text: str) -> ControlScanResult:
    runs: list[ControlRun] = []
    count = 0
    run_start = -1
    for i, c in enumerate(text):
        if c in INVISIBLE_CHARS:
            count += 1
            if run_start < 0:
                run_start = i
        elif run_start >= 0:
            runs.append(_make_run(text, run_start, i))
            run_start = -1
    if run_start >= 0:
        runs.append(_make_run(text, run_start, len(text)))
    return ControlScanResult(
        sanitized_text=remove_spans(text, [r.span for r in runs]),
        count=count,
        runs=runs,
    )


def _make_run(text: str, start: int, end: int) -> ControlRun:
    return ControlRun(
        span=(start, end), is_bidi=any(c in BIDI_CHARS for c in text[start:end])
    )


@lru_cache(maxsize=4096)
def _script_of(char: str) -> str:
    if not char.isalpha():
        return ""
    return unicodedata.name(char, "UNKNOWN").split()[0]


def detect_homoglyphs(text: str) -> list[HomoglyphToken]:
    found: list[HomoglyphToken] = []
    interwiki = [m.span() for m in _INTERWIKI.finditer(text)]
    for m in _WORD.finditer(text):
        token = m.group()
        if token.isascii():
            continue
        if any(start <= m.start() < end for start, end in interwiki):
            continue
        scripts = {_script_of(c) for c in token} - {""}
        if "LATIN" not in scripts:
            continue
        mixed = scripts & {"CYRILLIC", "GREEK"}
        if not mixed:
            continue
        # Short Greek+Latin tokens are almost always units/symbols (mu-m, delta-t).
        if mixed == {"GREEK"} and sum(c.isalpha() for c in token) < 3:
            continue
        found.append(
            HomoglyphToken(
                token=token, span=(m.start(), m.end()), scripts=sorted(scripts)
            )
        )
    return found


def _split_top_level(text: str, separators: str) -> list[str]:
    """Split on any of `separators`, ignoring any inside parentheses or quotes."""
    parts: list[str] = []
    depth = 0
    quote = ""
    current: list[str] = []
    for char in text:
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif char in separators and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def parse_style(style: str) -> dict[str, str]:
    """Parse an inline style attribute: lower-cased, !important stripped, last wins."""
    props: dict[str, str] = {}
    for declaration in _split_top_level(style, ";"):
        name, colon, value = declaration.partition(":")
        if not colon or not name.strip():
            continue
        props[name.strip().lower()] = _IMPORTANT.sub(" ", value).strip().lower()
    return props


def _number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _fraction(value: str) -> float | None:
    """Parse '0.5' or '50%' to a 0-1 fraction."""
    value = value.strip()
    if value.endswith("%"):
        number = _number(value[:-1])
        return None if number is None else number / 100
    return _number(value)


def _length_px(value: str) -> float | None:
    m = _LENGTH.fullmatch(value.strip())
    if m is None:
        return None
    number = float(m.group(1))
    unit = m.group(2) or "px"
    if unit == "pt":
        return number * 4 / 3
    return number * 16 if unit in {"em", "rem"} else number


def _is_zero(value: str | None) -> bool:
    if value is None:
        return False
    m = _LENGTH.fullmatch(value.strip())
    return m is not None and float(m.group(1)) == 0


def parse_color(value: str) -> tuple[int, int, int, float] | None:
    """Normalise hex / rgb(a) / basic named colours to (r, g, b, alpha)."""
    value = value.strip().lower()
    if value == "transparent":
        return (0, 0, 0, 0.0)
    if value in _NAMED_COLORS:
        return (*_NAMED_COLORS[value], 1.0)
    hex_match = _HEX_COLOR.fullmatch(value)
    if hex_match is not None:
        digits = hex_match.group(1)
        if len(digits) in {3, 4}:
            digits = "".join(c * 2 for c in digits)
        alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
        return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16), alpha)
    func = _FUNC_COLOR.fullmatch(value)
    if func is None:
        return None
    parts = [p for p in re.split(r"[,\s/]+", func.group(1).strip()) if p]
    if len(parts) not in {3, 4}:
        return None
    channels: list[int] = []
    for part in parts[:3]:
        scale = 2.55 if part.endswith("%") else 1.0
        number = _number(part.rstrip("%"))
        if number is None:
            return None
        channels.append(max(0, min(255, round(number * scale))))
    parsed_alpha = _fraction(parts[3]) if len(parts) == 4 else 1.0
    if parsed_alpha is None:
        return None
    return (channels[0], channels[1], channels[2], parsed_alpha)


def _background_color(props: dict[str, str]) -> tuple[int, int, int, float] | None:
    for key in ("background-color", "background"):
        for token in _split_top_level(props.get(key, ""), " \t\n"):
            color = parse_color(token)
            if color is not None:
                return color
    return None


def _hidden_display(props: dict[str, str]) -> str | None:
    if props.get("display") == "none":
        return "display:none"
    if props.get("visibility") in {"hidden", "collapse"}:
        return f"visibility:{props['visibility']}"
    return None


def _hidden_opacity(props: dict[str, str], limit: float) -> str | None:
    opacity = _fraction(props.get("opacity", ""))
    if opacity is not None and opacity < limit:
        return f"opacity:{props['opacity']}"
    m = re.search(r"opacity\(\s*([^)]*)\)", props.get("filter", ""))
    filtered = _fraction(m.group(1)) if m else None
    if filtered is not None and filtered < limit:
        return f"filter:opacity({m.group(1).strip() if m else ''})"
    return None


def _hidden_font_size(props: dict[str, str], factor: float) -> str | None:
    m = _FONT_SIZE.fullmatch(props.get("font-size", ""))
    if m is None:
        return None
    number = float(m.group(1))
    unit = m.group(2)
    if (unit is None and number == 0) or (
        unit is not None and number < _TINY_FONT_LIMIT[unit] * factor
    ):
        return f"font-size:{props['font-size']}"
    return None


def _hidden_color(props: dict[str, str]) -> str | None:
    color = parse_color(props.get("color", ""))
    if color is None:
        return None
    if color[3] < _ALPHA_LIMIT:
        return "color:transparent"
    background = _background_color(props)
    if background is None:
        return (
            "color:white-without-background" if color[:3] == (255, 255, 255) else None
        )
    if background[3] >= 1 - _ALPHA_LIMIT and background[:3] == color[:3]:
        return "color:equals-background"
    return None


def _hidden_box(props: dict[str, str], aria_hidden: bool) -> str | None:
    clipped = any(
        props.get(k) in {"hidden", "clip"}
        for k in ("overflow", "overflow-x", "overflow-y")
    )
    if not clipped:
        return None
    for key in ("width", "height", "max-width", "max-height"):
        value = props.get(key)
        tiny = aria_hidden and value is not None and (_length_px(value) or 99) <= 1
        if _is_zero(value) or tiny:
            return f"size:{key}:{value} with overflow:hidden"
    return None


def _numbers(text: str) -> list[float] | None:
    values = [_length_px(p) for p in re.split(r"[,\s]+", text.strip()) if p]
    return (
        None if any(v is None for v in values) else [v for v in values if v is not None]
    )


def _hidden_clip(props: dict[str, str]) -> str | None:
    m = re.fullmatch(r"rect\(([^)]*)\)", props.get("clip", ""))
    values = _numbers(m.group(1)) if m else None
    if values is not None and len(values) == 4:
        top, right, bottom, left = values
        if right - left <= 0 or bottom - top <= 0:
            return f"clip:{props['clip']}"
    return None


def _inset_hides(args: str) -> bool:
    edges = args.split("round")[0].split()
    if not edges or len(edges) > 4 or not all(e.endswith("%") for e in edges):
        return False
    pct = [_number(e[:-1]) or 0.0 for e in edges]
    top = pct[0]
    right = pct[1] if len(pct) > 1 else top
    bottom = pct[2] if len(pct) > 2 else top
    left = pct[3] if len(pct) > 3 else right
    return top + bottom >= 100 or left + right >= 100


def _polygon_area(args: str) -> float | None:
    points: list[tuple[float, float]] = []
    for piece in args.split(","):
        coords = _numbers(re.sub(r"^(?:nonzero|evenodd)\s*", "", piece.strip()))
        if coords is None:
            return None
        if len(coords) == 2:
            points.append((coords[0], coords[1]))
    if not points:
        return None
    return (
        abs(
            sum(
                x1 * y2 - x2 * y1
                for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
            )
        )
        / 2
    )


def _hidden_clip_path(props: dict[str, str]) -> str | None:
    value = props.get("clip-path", "")
    shape = re.fullmatch(r"(inset|circle|polygon)\((.*)\)", value)
    if shape is None:
        return None
    kind, args = shape.groups()
    if kind == "inset" and _inset_hides(args):
        return f"clip-path:{value}"
    if kind == "circle" and _is_zero(args.split(" at ")[0].strip() or None):
        return f"clip-path:{value}"
    if kind == "polygon" and _polygon_area(args) == 0:
        return f"clip-path:{value}"
    return None


def _hidden_transform(props: dict[str, str]) -> str | None:
    value = props.get("transform", "")
    for m in re.finditer(r"(?<![a-z])(scale(?:3d|x|y)?)\(([^)]*)\)", value):
        factors = [_number(p) for p in re.split(r"[,\s]+", m.group(2).strip()) if p]
        relevant = factors[:1] if m.group(1) in {"scalex", "scaley"} else factors[:2]
        if any(f is not None and abs(f) < 0.05 for f in relevant):
            return f"transform:{m.group(0)}"
    return None


def _hidden_off_screen(props: dict[str, str], aria_hidden: bool) -> str | None:
    limit = 99 if aria_hidden else 999
    indent = _length_px(props.get("text-indent", ""))
    if indent is not None and indent <= -limit:
        return "off-screen:text-indent"
    if props.get("position") not in {"absolute", "fixed"}:
        return None
    for key in ("left", "top", "right", "bottom", "margin-left"):
        offset = _length_px(props.get(key, ""))
        if offset is not None and (offset <= -limit or offset >= 9999):
            return f"off-screen:{key}"
    return None


def is_visually_hidden(props: dict[str, str], aria_hidden: bool = False) -> str | None:
    """Return why an element's inline style hides its text from a reader, else None.

    `aria_hidden` marks an aria-hidden="true" element, which lowers the thresholds.
    """
    return (
        _hidden_display(props)
        or _hidden_opacity(props, 0.2 if aria_hidden else _OPACITY_LIMIT)
        or _hidden_font_size(props, 2.5 if aria_hidden else 1.0)
        or _hidden_color(props)
        or _hidden_box(props, aria_hidden)
        or _hidden_clip(props)
        or _hidden_clip_path(props)
        or _hidden_transform(props)
        or _hidden_off_screen(props, aria_hidden)
    )


def _style_vector(reason: str) -> VectorType:
    if reason.startswith(("display", "visibility")):
        return VectorType.CSS_DISPLAY_NONE
    if reason.startswith("font-size"):
        return VectorType.CSS_ZERO_FONT
    return VectorType.CSS_HIDDEN_ELEMENT


def _find_close(text: str, name: str, start: int) -> int:
    """Return the end offset of the element whose open tag ends at `start`, or -1."""
    pattern = re.compile(rf"<(/?){re.escape(name)}\b[^<>]*?(/?)>", re.IGNORECASE)
    depth = 1
    for m in pattern.finditer(text, start):
        if m.group(1):
            depth -= 1
            if depth == 0:
                return m.end()
        elif not m.group(2):
            depth += 1
    return -1


def _find_table_end(text: str, start: int) -> int:
    depth = 0
    for m in _TABLE_MARKER.finditer(text, start):
        depth += 1 if m.group(1) == "{|" else -1
        if depth == 0:
            return m.end()
    return len(text)


def _item(
    text: str, vector: VectorType, start: int, end: int, hidden: str
) -> QuarantinedItem:
    hidden = hidden.strip()
    return QuarantinedItem(
        vector_type=vector,
        span=(start, end),
        raw_snippet=text[start:end],
        hidden_text=hidden,
        instruction_like=looks_like_instruction(hidden),
    )


def extract_hidden_channels(text: str) -> HiddenChannelResult:
    items: list[QuarantinedItem] = []
    for m in _COMMENT.finditer(text):
        items.append(
            _item(text, VectorType.HTML_COMMENT, m.start(), m.end(), m.group()[4:-3])
        )
    masked = _COMMENT.sub(lambda m: " " * len(m.group()), text)

    removals: list[tuple[int, int]] = []
    for m in _SCRIPT.finditer(masked):
        removals.append(m.span())
        if "ld+json" in m.group(2).lower() and looks_like_instruction(m.group(3)):
            items.append(
                _item(text, VectorType.CSS_HIDDEN_ELEMENT, *m.span(), m.group(3))
            )
    for m in _OPEN_TAG.finditer(masked):
        if m.group(3) or m.group(1).lower() in {"script", "style"}:
            continue
        attrs = m.group(2)
        vector: VectorType | None = None
        style = _STYLE_ATTR.search(attrs)
        if style is not None:
            reason = is_visually_hidden(
                parse_style(style.group(1) or style.group(2) or ""),
                aria_hidden=bool(_ARIA_HIDDEN.search(attrs)),
            )
            vector = None if reason is None else _style_vector(reason)
        if vector is None and _COLLAPSED_CLASS.search(attrs):
            vector = VectorType.COLLAPSED_BLOCK
        if vector is None and _HIDDEN_ATTR.search(_QUOTED.sub('""', attrs)):
            vector = VectorType.CSS_HIDDEN_ELEMENT
        if vector is None:
            continue
        close = _find_close(masked, m.group(1), m.end())
        if close < 0:
            continue
        inner = _TAG_STRIP.sub("", text[m.end() : close]).rsplit("</", 1)[0]
        if inner.strip():
            items.append(_item(text, vector, m.start(), close, inner))
    for m in _WIKI_TABLE_START.finditer(masked):
        end = _find_table_end(masked, m.start())
        items.append(
            _item(
                text,
                VectorType.COLLAPSED_BLOCK,
                m.start(),
                end,
                text[m.end() : end - 2],
            )
        )
    for m in _WIKI_ALT.finditer(masked):
        _append_attr_text(
            items,
            text,
            VectorType.A11Y_ALT_POISONING,
            m.start(),
            m.end(),
            m.group(1),
            min_words=SUSPICIOUS_ALT_WORD_LIMIT + 1,
        )
    for start, end, value in _media_params(masked):
        _append_attr_text(
            items, text, VectorType.A11Y_ALT_POISONING, start, end, value, True
        )
    for m in _OPEN_TAG.finditer(masked):
        for pair in _ATTR_PAIR.finditer(m.group(2)):
            name = pair.group(1).lower()
            if name in _A11Y_ATTRS or name.startswith("aria-label"):
                vector = VectorType.A11Y_ALT_POISONING
            elif (
                name in _TEXT_ATTRS
                or name.startswith("data-")
                or (name == "content" and m.group(1).lower() == "meta")
            ):
                vector = VectorType.ATTRIBUTE_TEXT
            else:
                continue
            _append_attr_text(
                items,
                text,
                vector,
                m.start(2) + pair.start(1),
                m.start(2) + pair.end(),
                pair.group(2) or pair.group(3) or "",
                name not in _LEGACY_ATTRS,
            )
    template_params, unscanned_span = _template_params(masked)
    screen_items: list[QuarantinedItem] = []
    for start, end, value in template_params:
        if looks_like_instruction(value):
            item = _item(text, VectorType.TEMPLATE_PARAM_TEXT, start, end, value)
            items.append(
                item.model_copy(
                    update={"instruction_like": has_strong_instruction(value)}
                )
            )
        elif len(_WORD.findall(value)) >= PROSE_PARAM_MIN_WORDS:
            screen_items.append(
                _item(text, VectorType.TEMPLATE_PARAM_TEXT, start, end, value)
            )

    kept = _drop_nested(items)
    removals.extend(i.span for i in kept)
    return HiddenChannelResult(
        sanitized_human_text=remove_spans(text, removals),
        quarantined_items=kept,
        unscanned_span=unscanned_span,
        screen_items=screen_items,
    )


def _split_pipes(text: str, offset: int) -> list[tuple[int, str]]:
    """Split on top-level '|' (not inside [[ ]]); returns (offset of '|', piece)."""
    pieces: list[tuple[int, str]] = []
    depth = 0
    start = 0
    i = 0
    while i < len(text):
        if text.startswith("[[", i):
            depth += 1
            i += 2
            continue
        if text.startswith("]]", i):
            depth = max(depth - 1, 0)
            i += 2
            continue
        if text[i] == "|" and depth == 0:
            pieces.append((offset + start, text[start:i]))
            start = i
        i += 1
    pieces.append((offset + start, text[start:]))
    return pieces


def _split_param(piece: str) -> tuple[str, str]:
    """Split '|name=value' into (name, value); positional pieces have name ''."""
    name, eq, value = piece[1:].partition("=")
    if eq and name.strip() and not re.search(r"[\n\[\]<>{}]", name.strip()):
        return name.strip().lower(), value
    return "", piece[1:]


def _template_params(
    text: str,
) -> tuple[list[tuple[int, int, str]], tuple[int, int] | None]:
    """Return (start, end, value) of every template parameter, innermost first.

    Cost is bounded: only the first MAX_TEMPLATE_SCAN_CHARS characters are scanned and at
    most MAX_TEMPLATE_PASSES nesting levels are peeled; anything beyond is not reported.
    """
    params: list[tuple[int, int, str]] = []
    unscanned: tuple[int, int] | None = None
    if len(text) > MAX_TEMPLATE_SCAN_CHARS:
        unscanned = (MAX_TEMPLATE_SCAN_CHARS, len(text))
    text = text[:MAX_TEMPLATE_SCAN_CHARS]

    def blank(m: re.Match[str]) -> str:
        for start, piece in _split_pipes(m.group()[2:-2], m.start() + 2)[1:]:
            params.append((start, start + len(piece), _split_param(piece)[1]))
        return " " * len(m.group())

    for _ in range(MAX_TEMPLATE_PASSES):
        if not _TEMPLATE.search(text):
            break
        text = _TEMPLATE.sub(blank, text)
    else:
        leftover = _TEMPLATE.search(text)
        if leftover and unscanned is None:
            unscanned = (leftover.start(), len(text))
    return params, unscanned


def _media_params(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, value) of alt/title/caption-like params in File: links."""
    found: list[tuple[int, int, str]] = []
    for m in _MEDIA_LINK.finditer(text):
        depth = 1
        i = m.end()
        while i < len(text) and depth:
            if text.startswith("[[", i):
                depth += 1
                i += 2
            elif text.startswith("]]", i):
                depth -= 1
                i += 2
            else:
                i += 1
        for start, piece in _split_pipes(text[m.end() : i - 2], m.end())[1:]:
            name, value = _split_param(piece)
            if name in _MEDIA_PARAMS:
                found.append((start, start + len(piece), value))
    return found


def _append_attr_text(
    items: list[QuarantinedItem],
    text: str,
    vector: VectorType,
    start: int,
    end: int,
    value: str,
    words_only: bool = False,
    min_words: int = ATTRIBUTE_TEXT_MIN_WORDS,
) -> None:
    """Quarantine attribute text with >= min_words words, or short instruction-like text."""
    long_enough = len(value.split()) >= min_words
    if long_enough or (not words_only and looks_like_instruction(value)):
        item = _item(text, vector, start, end, value)
        items.append(
            item.model_copy(update={"instruction_like": has_strong_instruction(value)})
        )


def _drop_nested(items: list[QuarantinedItem]) -> list[QuarantinedItem]:
    kept: list[QuarantinedItem] = []
    for item in sorted(items, key=lambda i: (i.span[0], -i.span[1])):
        if kept and item.span[1] <= kept[-1].span[1]:
            continue
        kept.append(item)
    return kept
