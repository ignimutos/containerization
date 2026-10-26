import json

import httpx

from tooling.build.telegram import TelegramClient, split_messages


def test_split_messages_keeps_a_short_report_whole() -> None:
    assert split_messages("one\n\ntwo") == ["one\n\ntwo"]


def test_split_messages_splits_between_blocks() -> None:
    text = "\n\n".join(["a" * 30, "b" * 30, "c" * 30])

    messages = split_messages(text, limit=70)

    assert messages == ["a" * 30 + "\n\n" + "b" * 30, "c" * 30]


def test_split_messages_cuts_a_single_line_that_cannot_fit() -> None:
    messages = split_messages("x" * 100, limit=40)

    assert len(messages) == 3
    assert all(len(message) <= 40 for message in messages)
    assert "".join(messages) == "x" * 100


def test_split_messages_closes_tags_its_cut_left_open() -> None:
    text = "<blockquote expandable><b>a</b>\n" + "\n".join(
        f"line {index} " + "y" * 30 for index in range(10)
    )

    messages = split_messages(text, limit=120)

    assert len(messages) > 1
    for message in messages:
        assert message.count("<blockquote") == message.count("</blockquote>")


def test_split_messages_returns_nothing_for_empty_text() -> None:
    assert split_messages("") == []


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
