import json

import httpx

from tooling.build.dockerhub import DockerHubClient


def test_dockerhub_client_authenticates_then_updates_repository_description() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            assert request.url.path == "/v2/users/login/"
            assert json.loads(request.content) == {
                "username": "docker-user",
                "password": "docker-pass",
            }
            return httpx.Response(200, json={"token": "jwt-token"})

        assert request.method == "PATCH"
        assert request.url.path == "/v2/repositories/ignimutos/telegram-api/"
        assert request.headers["Authorization"] == "JWT jwt-token"
        assert json.loads(request.content) == {
            "full_description": "# Telegram API\n\nSynced README.\n"
        }
        return httpx.Response(200, json={"full_description": "updated"})

    client = DockerHubClient(
        username="docker-user",
        password="docker-pass",
        transport=httpx.MockTransport(handler),
    )

    client.update_repository_description(
        namespace="ignimutos",
        repository="telegram-api",
        full_description="# Telegram API\n\nSynced README.\n",
    )

    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/v2/users/login/"),
        ("PATCH", "/v2/repositories/ignimutos/telegram-api/"),
    ]
