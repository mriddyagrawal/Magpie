"""Token streaming for the answer step.

The answer model does not write prose — it writes one JSON object
(`{"evidence": [...], "answer": "...", "sources_used": [...], ...}`,
see `src/answer.py:Answer`), grammar-enforced on the local path and
prompt-enforced on cloud. Streaming that object to the user verbatim would
show them braces and field names, so this module watches the raw model
output as it arrives and hands on only the *value* of the top-level
`answer` string, JSON-decoded, in whatever pieces it was generated in.

Two pieces:

  - `AnswerFieldStreamer` — feed it raw text chunks; it calls `emit(piece)`
    with decoded answer text as soon as it is available. A real incremental
    scanner rather than a substring match, so an `evidence` quote that
    happens to contain `"answer": "` cannot fool it, and an escape split
    across two chunks (`\\` then `n`, or half a `\\uXXXX`) is decoded
    correctly.
  - `stream_answer(start)` — bridges a callback-fed answer call into an
    async iterator, which is what an SSE endpoint wants to consume.

The streamed text is a preview. The parsed `Answer` the caller finally
gets back can differ from it (JSON repair on a cloud reply, the not-found
contract, the grounding guard), so consumers treat the final object as
authoritative — `/query/stream` sends it as the `answer_final` frame.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Awaitable, Callable

# JSON's single-character escapes. `\u` is handled separately.
_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}

# Only depth-1 strings are recorded (to see whether one is the `answer` key);
# a long value there is never the key, so stop remembering it past this.
_MAX_KEY_CHARS = 64


class AnswerFieldStreamer:
    """Incremental scanner over streamed JSON that emits the `answer` value.

    Everything before the first `{` is ignored (a cloud model's "Here is
    the JSON:" preamble, a ```json fence), and everything after the answer
    string closes is ignored too — the remaining fields are parsed from the
    full text by the caller, not here.
    """

    def __init__(self, emit: Callable[[str], None]) -> None:
        self._emit = emit
        self._started = False       # seen the opening `{` of the object
        self._depth = 0             # {} / [] nesting; the answer lives at depth 1
        self._in_string = False
        self._escape = False        # previous char was a backslash
        self._unicode: str | None = None   # hex digits of a \uXXXX being collected
        self._high_surrogate: int | None = None
        self._string: list[str] = []       # chars of the depth-1 string being read
        self._closed_key: str | None = None   # a depth-1 string just closed; is a `:` next?
        self._answer_next = False   # the next value at depth 1 is the answer
        self._streaming = False     # inside the answer string right now
        self._done = False          # answer string closed; ignore the rest
        self._pending: list[str] = []
        self.text = ""              # everything emitted so far, joined

    @property
    def done(self) -> bool:
        return self._done

    def feed(self, chunk: str) -> None:
        """Consume the next piece of raw model output. Any answer text it
        completes is emitted once, at the end of the call."""
        for ch in chunk:
            self._step(ch)
        if self._pending:
            piece = "".join(self._pending)
            self._pending = []
            self.text += piece
            self._emit(piece)

    # one character of raw output
    def _step(self, ch: str) -> None:
        if self._done:
            return
        if not self._started:
            if ch == "{":
                self._started = True
                self._depth = 1
            return

        if self._in_string:
            self._string_char(ch)
            return

        # Outside a string.
        if ch in " \t\r\n":
            return
        # A depth-1 string just closed: it was a key if a colon follows, a
        # value otherwise.
        if self._closed_key is not None:
            key, self._closed_key = self._closed_key, None
            if ch == ":":
                self._answer_next = key == "answer"
                return
        if ch == '"':
            self._in_string = True
            self._string = []
            if self._answer_next and self._depth == 1:
                self._streaming = True
            self._answer_next = False
            return
        # Any other token (`{`, `[`, a number, true/null, a comma) means the
        # answer value — if one was due — is not a string; stop waiting.
        self._answer_next = False
        if ch in "{[":
            self._depth += 1
        elif ch in "}]":
            self._depth -= 1

    def _string_char(self, ch: str) -> None:
        if self._unicode is not None:
            self._unicode += ch
            if len(self._unicode) == 4:
                try:
                    code = int(self._unicode, 16)
                except ValueError:
                    code = 0xFFFD
                self._unicode = None
                self._put_codepoint(code)
            return
        if self._escape:
            self._escape = False
            if ch == "u":
                self._unicode = ""
                return
            self._put(_ESCAPES.get(ch, ch))
            return
        if ch == "\\":
            self._escape = True
            return
        if ch == '"':
            self._in_string = False
            if self._streaming:
                self._streaming = False
                self._done = True
            elif self._depth == 1:
                self._closed_key = "".join(self._string)
            return
        self._put(ch)

    def _put_codepoint(self, code: int) -> None:
        # 😀 style pairs arrive as two escapes; join them.
        if 0xD800 <= code <= 0xDBFF:
            self._high_surrogate = code
            return
        if 0xDC00 <= code <= 0xDFFF:
            if self._high_surrogate is None:
                self._put("�")
                return
            high, self._high_surrogate = self._high_surrogate, None
            self._put(chr(0x10000 + ((high - 0xD800) << 10) + (code - 0xDC00)))
            return
        self._high_surrogate = None
        self._put(chr(code))

    def _put(self, ch: str) -> None:
        if self._streaming:
            self._pending.append(ch)
        elif self._depth == 1 and len(self._string) < _MAX_KEY_CHARS:
            self._string.append(ch)


async def stream_answer(
    start: Callable[[Callable[[str], None]], Awaitable[object]],
) -> AsyncIterator[tuple[str, object]]:
    """Run an answer call whose progress arrives through a callback, and
    expose it as an async iterator of `("text", piece)` items followed by
    one `("answer", result)` item.

    `start(on_answer_text)` must return the awaitable that produces the
    result (typically `answer_question(..., on_answer_text=on_answer_text)`).
    The pieces go through a queue so the consumer — an SSE generator —
    can `yield` each one to the client while the model is still writing.
    An exception from the answer call is raised from the iterator once the
    pieces already produced have been delivered; if the consumer stops
    early (client gone), the answer call is cancelled.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def on_answer_text(piece: str) -> None:
        # The callback fires on the loop thread today, but a provider that
        # generates in a worker thread would call it from there — this is
        # correct either way, and keeps arrival order.
        loop.call_soon_threadsafe(queue.put_nowait, piece)

    task = asyncio.ensure_future(start(on_answer_text))
    task.add_done_callback(lambda _t: queue.put_nowait(None))
    try:
        while True:
            piece = await queue.get()
            if piece is None:
                break
            yield "text", piece
        yield "answer", await task
    finally:
        if not task.done():
            task.cancel()
