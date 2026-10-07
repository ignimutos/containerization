from __future__ import annotations

import httpx


class DockerHubClient:
    def __init__(
        self,
        *,
        username: str,
        password: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._client = httpx.Client(
            base_url="https://hub.docker.com",
            transport=transport,
            follow_redirects=True,
        )

    def update_repository_description(
        self,
        *,
        namespace: str,
        repository: str,
        full_description: str,
    ) -> None:
        if not namespace:
            raise ValueError("namespace must not be empty")
        if not repository:
            raise ValueError("repository must not be empty")

        token = self._login()
        response = self._client.patch(
            f"/v2/repositories/{namespace}/{repository}/",
            json={"full_description": full_description},
            headers={"Authorization": f"JWT {token}"},
        )
        response.raise_for_status()

    def _login(self) -> str:
        response = self._client.post(
            "/v2/users/login/",
            json={
                "username": self._username,
                "password": self._password,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("docker hub login response must be a mapping")
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("docker hub login response missing token")
        return token
