from __future__ import annotations

import httpx


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
