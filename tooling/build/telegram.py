from __future__ import annotations

import re

import httpx

# The Bot API rejects a message past 4096 characters outright, which loses the
# whole report. Stay clear of the edge so a repeated header still fits.
MESSAGE_LIMIT = 4000


def split_messages(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Split one report into sendable messages, never cutting inside a block.

    Blocks are the blank-line separated sections of the report. A block that is
    itself over the limit is cut at a line boundary and its tags are closed, so
    the Bot API still accepts it instead of rejecting the whole message.
    """
    if not text:
        return []

    messages: list[str] = []
    current: list[str] = []
    for block in text.split("\n\n"):
        candidate = "\n\n".join([*current, block])
        if len(candidate) <= limit:
            current.append(block)
            continue
        if current:
            messages.append("\n\n".join(current))
            current = []
        if len(block) <= limit:
            current.append(block)
        else:
            messages.extend(_truncate_lines(block, limit))
    if current:
        messages.append("\n\n".join(current))
    return messages


def _truncate_lines(block: str, limit: int) -> list[str]:
    """Split one over-long block into chunks, closing tags the cut left open.

    A single line longer than the limit is hard-cut. It carries no newline to
    split on, and leaving it whole would lose the message.
    """
    chunks: list[str] = []
    current: list[str] = []
    for line in block.splitlines():
        while len(line) > limit:
            if current:
                chunks.append("\n".join(current))
                current = []
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = "\n".join([*current, line])
        if current and len(candidate) > limit:
            chunks.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        chunks.append("\n".join(current))

    closed: list[str] = []
    for chunk in chunks:
        for tag in _open_tags(chunk):
            chunk = f"{chunk}{tag}"
        closed.append(chunk)
    return closed


def _open_tags(chunk: str) -> list[str]:
    """Closing tags for the tags `chunk` opens and never closes."""
    opened = re.findall(r"<(blockquote|b|code|pre)\b[^>]*>", chunk)
    closed = re.findall(r"</(blockquote|b|code|pre)>", chunk)
    remaining = list(opened)
    for tag in closed:
        if tag in remaining:
            remaining.remove(tag)
    return [f"</{tag}>" for tag in reversed(remaining)]


class TelegramClient:
    def __init__(
        self,
        *,
        bot_token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=f"https://api.telegram.org/bot{bot_token}",
            transport=transport,
            follow_redirects=True,
        )

    def send_message(self, *, chat_id: str, text: str) -> None:
        if not chat_id:
            raise ValueError("chat_id must not be empty")
        if not text:
            raise ValueError("text must not be empty")

        response = self._client.post(
            "/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        response.raise_for_status()
