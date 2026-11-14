"""Extract reader-visible wikitext suitable for edit judging."""

import re
from typing import Final

import mwparserfromhell

from palimpsest.stage0 import strip_wikitext

_FILE_NAMESPACES: Final = frozenset(
    {"file", "image", "tiedosto", "kuva", "fil", "bild"}
)
_CAPTION_PARAMS: Final = frozenset({"kuvateksti", "caption", "bildtext"})
_MEDIA_OPTIONS: Final = frozenset(
    {
        "thumb",
        "thumbnail",
        "frame",
        "framed",
        "frameless",
        "border",
        "left",
        "right",
        "center",
        "centre",
        "none",
        "baseline",
        "sub",
        "super",
        "top",
        "text-top",
        "middle",
        "bottom",
        "text-bottom",
    }
)
_MEDIA_OPTION_PARAMS: Final = frozenset(
    {
        "alt",
        "link",
        "lang",
        "page",
        "class",
        "upright",
        "thumbtime",
        "start",
        "end",
    }
)
_PIXEL_SIZE: Final = re.compile(r"(?:\d+(?:x\d*)?|x\d+)px", re.IGNORECASE)


def _split_arguments(value: str) -> list[str]:
    """Split media arguments while leaving nested links and templates intact."""
    parts: list[str] = []
    start = depth = 0
    index = 0
    while index < len(value):
        pair = value[index : index + 2]
        if pair in {"{{", "[["}:
            depth += 1
            index += 2
            continue
        if pair in {"}}", "]]"} and depth:
            depth -= 1
            index += 2
            continue
        if value[index] == "|" and not depth:
            parts.append(value[start:index])
            start = index + 1
        index += 1
    parts.append(value[start:])
    return parts


def _media_caption(arguments: str) -> str | None:
    caption: str | None = None
    for argument in _split_arguments(arguments):
        value = argument.strip()
        key, separator, parameter = value.partition("=")
        folded_key = key.strip().casefold()
        if separator and folded_key == "caption":
            caption = parameter.strip()
        elif (
            not separator
            and (value.casefold() in _MEDIA_OPTIONS or _PIXEL_SIZE.fullmatch(value))
        ) or (separator and folded_key in _MEDIA_OPTION_PARAMS):
            continue
        elif value:
            caption = value
    return caption


def _is_file_link(link: mwparserfromhell.nodes.Wikilink) -> bool:
    namespace, separator, _ = str(link.title).partition(":")
    return bool(separator and namespace.strip().casefold() in _FILE_NAMESPACES)


def _gallery_captions(contents: str) -> list[str]:
    captions: list[str] = []
    for line in contents.splitlines():
        name, separator, arguments = line.partition("|")
        namespace, colon, _ = name.strip().partition(":")
        if separator and colon and namespace.casefold() in _FILE_NAMESPACES:
            caption = _media_caption(arguments)
            if caption:
                captions.append(caption)
    return captions


def judged_plain_text(wikitext: str) -> str:
    """Return prose plus reader-visible media and infobox captions.

    Image names, layout options, and dimensions are presentation markup.  Captions
    are displayed article text, so preserve them separately before stripping code.
    """
    code = mwparserfromhell.parse(wikitext)
    captions: list[str] = []
    for tag in code.filter_tags(recursive=True):
        if str(tag.tag).strip().casefold() == "gallery":
            captions.extend(_gallery_captions(str(tag.contents or "")))
            code.remove(tag)
    for link in code.filter_wikilinks(recursive=True):
        if _is_file_link(link):
            caption = _media_caption(str(link.text or ""))
            if caption:
                captions.append(caption)
            code.remove(link)
    for template in code.filter_templates(recursive=True):
        captions.extend(
            str(parameter.value)
            for parameter in template.params
            if str(parameter.name).strip().casefold() in _CAPTION_PARAMS
        )
    visible = [strip_wikitext(str(code)).strip()]
    visible.extend(strip_wikitext(caption).strip() for caption in captions)
    return "\n".join(text for text in visible if text)
