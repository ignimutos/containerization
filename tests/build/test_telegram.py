import json

import httpx

from tooling.build.telegram import TelegramClient


def test_telegram_client_sends_html_message_payload() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert request.url.path == "/bot123:abc/sendMessage"
        assert json.loads(request.content) == {
            "chat_id": "-1001234567890",
            "text": "Build summary\nChanged targets: 0",
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    client = TelegramClient(
        bot_token="123:abc",
        transport=httpx.MockTransport(handler),
    )

    client.send_message(
        chat_id="-1001234567890",
        text="Build summary\nChanged targets: 0",
    )

    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/bot123:abc/sendMessage"),
    ]
