"""Image slots: where an image sits inside a flattened local prompt.

The desktop side builds one heterogeneous message list (strings and
image blocks in document order). The local transport has to send text
as a string and images as typed `image_url` parts, and until now it
pulled every image out and appended them all AFTER the text - so the
model saw `question + every file's text + question again` and only
then the pictures, with nothing tying an image to its file header.

`_flatten_message_for_local` (src/llm.py) now leaves a slot marker in
the text where each image was; `_attach_images_to_last_user`
(src/inference/local_llm.py) splits the text on those markers and
interleaves the image parts at their original positions. llama-server
renders content parts in order, so the model sees each image right
under its `--- File N ---` header, exactly like the cloud transport
already did.

The marker uses NUL bytes so it cannot collide with file text (NUL
never survives the text extractors) and is unmistakable if it ever
leaks into a log.
"""

from __future__ import annotations

import re

_SLOT_FMT = "\x00magpie:image:{n}\x00"
_SLOT_RE = re.compile(r"\x00magpie:image:(\d+)\x00")


def slot(n: int) -> str:
    """Marker for the n-th image (0-based) of the request."""
    return _SLOT_FMT.format(n=n)


def split_slots(text: str) -> list[str | int]:
    """Split `text` into a sequence of text runs and image indices, in
    order. Empty text runs are dropped; indices are ints."""
    out: list[str | int] = []
    pos = 0
    for m in _SLOT_RE.finditer(text):
        if m.start() > pos:
            out.append(text[pos:m.start()])
        out.append(int(m.group(1)))
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    return out


def strip_slots(text: str) -> str:
    """Text with every slot marker removed (for transports that drop images)."""
    return _SLOT_RE.sub("", text)
