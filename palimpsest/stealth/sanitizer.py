import re
import unicodedata
from functools import lru_cache

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

_STYLE_PATTERNS: tuple[tuple[VectorType, re.Pattern[str]], ...] = (
    (VectorType.CSS_DISPLAY_NONE, re.compile(r"display\s*:\s*none", re.IGNORECASE)),
    (
        VectorType.CSS_DISPLAY_NONE,
        re.compile(r"visibility\s*:\s*hidden", re.IGNORECASE),
    ),
    (
        VectorType.CSS_ZERO_FONT,
        re.compile(r"font-size\s*:\s*0(?:px|pt|em|rem|%)?(?![\w.])", re.IGNORECASE),
    ),
    (
        VectorType.CSS_HIDDEN_ELEMENT,
        re.compile(r"opacity\s*:\s*0(?:\.0+)?(?![\w.])", re.IGNORECASE),
    ),
    (
        VectorType.CSS_HIDDEN_ELEMENT,
        re.compile(r"filter\s*:\s*opacity\(\s*0%?\s*\)", re.IGNORECASE),
    ),
    (
        VectorType.CSS_HIDDEN_ELEMENT,
        re.compile(r"line-height\s*:\s*0(?:px|pt|em|rem|%)?(?![\w.])", re.IGNORECASE),
    ),
    (
        VectorType.CSS_HIDDEN_ELEMENT,
        re.compile(r"(?:left|top|text-indent)\s*:\s*-\d{3,}px", re.IGNORECASE),
    ),
    (
        VectorType.CSS_HIDDEN_ELEMENT,
        re.compile(r"(?<![\w-])color\s*:\s*transparent", re.IGNORECASE),
    ),
)
_COLOR = re.compile(r"(?<![\w-])color\s*:\s*([^;\"']+)", re.IGNORECASE)
_BACKGROUND = re.compile(
    r"(?<![\w-])background(?:-color)?\s*:\s*([^;\"']+)", re.IGNORECASE
)
_WHITE = frozenset({"white", "#fff", "#ffffff"})

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_OPEN_TAG = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)\b([^<>]*?)(/?)>")
_STYLE_ATTR = re.compile(r"style\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE)
_COLLAPSED_CLASS = re.compile(
    r"class\s*=\s*[\"'][^\"']*mw-collapsed[^\"']*[\"']", re.IGNORECASE
)
_SCRIPT = re.compile(
    r"<(script|style)\b([^<>]*)>(.*?)</\1\s*>", re.DOTALL | re.IGNORECASE
)
_HTML_ATTR = re.compile(
    r"""\s(alt|aria-label|title)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE
)
_WIKI_ALT = re.compile(r"\|\s*alt\s*=([^|\]}\n]*)")
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


def looks_like_instruction(text: str) -> bool:
    return bool(_INSTRUCTION_CI.search(text) or _INSTRUCTION_CS.search(text))


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
    for m in _WORD.finditer(text):
        token = m.group()
        if token.isascii():
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


def _style_vector(style: str) -> VectorType | None:
    for vector, pattern in _STYLE_PATTERNS:
        if pattern.search(style):
            return vector
    color = _COLOR.search(style)
    if color is None:
        return None
    color_value = color.group(1).strip().lower()
    background = _BACKGROUND.search(style)
    if background is None:
        return VectorType.CSS_HIDDEN_ELEMENT if color_value in _WHITE else None
    return (
        VectorType.CSS_HIDDEN_ELEMENT
        if background.group(1).strip().lower() == color_value
        else None
    )


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
            vector = _style_vector(style.group(1) or style.group(2) or "")
        if vector is None and _COLLAPSED_CLASS.search(attrs):
            vector = VectorType.COLLAPSED_BLOCK
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
        _append_alt(items, text, m.start(), m.end(), m.group(1))
    for m in _HTML_ATTR.finditer(masked):
        _append_alt(items, text, m.start() + 1, m.end(), m.group(2) or m.group(3) or "")

    kept = _drop_nested(items)
    removals.extend(i.span for i in kept)
    return HiddenChannelResult(
        sanitized_human_text=remove_spans(text, removals), quarantined_items=kept
    )


def _append_alt(
    items: list[QuarantinedItem], text: str, start: int, end: int, value: str
) -> None:
    if len(value.split()) > SUSPICIOUS_ALT_WORD_LIMIT or looks_like_instruction(value):
        items.append(_item(text, VectorType.A11Y_ALT_POISONING, start, end, value))


def _drop_nested(items: list[QuarantinedItem]) -> list[QuarantinedItem]:
    kept: list[QuarantinedItem] = []
    for item in sorted(items, key=lambda i: (i.span[0], -i.span[1])):
        if kept and item.span[1] <= kept[-1].span[1]:
            continue
        kept.append(item)
    return kept
