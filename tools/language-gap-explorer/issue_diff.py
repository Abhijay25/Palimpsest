"""Escaped word-level source diffs shared by native and preview evidence."""
import re
import html
import difflib

def diff_html(old: str, new: str) -> str:
    """Render a full-width, word-level diff using the native anchor classes."""
    old_tokens = re.findall(r"\s+|\w+|[^\w\s]", old)
    new_tokens = re.findall(r"\s+|\w+|[^\w\s]", new)
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens)
    old_html: list[str] = []
    new_html: list[str] = []
    for opcode, a0, a1, b0, b1 in matcher.get_opcodes():
        old_text = html.escape("".join(old_tokens[a0:a1]))
        new_text = html.escape("".join(new_tokens[b0:b1]))
        if opcode == "equal":
            old_html.append(old_text)
            new_html.append(new_text)
        elif opcode == "delete":
            old_html.append(f'<del class="diffchange">{old_text}</del>')
        elif opcode == "insert":
            new_html.append(f'<ins class="diffchange">{new_text}</ins>')
        else:
            old_html.append(f'<del class="diffchange">{old_text}</del>')
            new_html.append(f'<ins class="diffchange">{new_text}</ins>')
    return (
        '<table class="flags-diff diff mw-diff-inline"><thead><tr>'
        '<th scope="col">Prior revision</th><th scope="col">Selected revision</th>'
        '</tr></thead><tbody><tr>'
        f'<td class="mw-diff-inline-deleted" data-diff-side="old">{"".join(old_html)}</td>'
        f'<td class="mw-diff-inline-added" data-diff-side="new">{"".join(new_html)}</td>'
        '</tr></tbody></table>'
    )
