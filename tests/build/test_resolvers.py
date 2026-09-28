import hashlib
from pathlib import Path

import httpx
import pytest

from tooling.build.cli import BuildPlan, resolve_target_builds
from tooling.build.errors import BuildUserError, ResolverUserError
from tooling.build.models import ResolvedTargetState
from tooling.build.resolvers import ResolverService


def test_resolve_github_tag_falls_back_to_unauthenticated_request_for_invalid_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/releases/latest"):
            if request.headers.get("Authorization") == "Bearer bad-token":
                return httpx.Response(401, json={"message": "Bad credentials"})
            return httpx.Response(200, json={"tag_name": "v2.0.1"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = ResolverService(
        token="bad-token",
        transport=httpx.MockTransport(handler),
    )

    tag = service.resolve_github_tag("owner/repo")

    assert tag == "2.0.1"
    assert [request.headers.get("Authorization") for request in requests] == [
        "Bearer bad-token",
        None,
    ]


def test_resolve_github_tag_records_raw_upstream_tag_before_stripping_v() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json={"tag_name": "v2.0.1"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = ResolverService(transport=httpx.MockTransport(handler))

    raw: dict[str, str] = {}
    tag = service.resolve_github_tag("owner/repo", raw_out=raw)

    assert tag == "2.0.1"
    assert raw == {"github_tag": "v2.0.1"}


def test_resolve_github_tag_records_raw_upstream_tag_from_tags_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(404, json={"message": "Not Found"})
        if request.url.path.endswith("/tags"):
            return httpx.Response(200, json=[{"name": "release-2.0.1"}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = ResolverService(transport=httpx.MockTransport(handler))

    raw: dict[str, str] = {}
    tag = service.resolve_github_tag("owner/repo", regex=r"^release-(.+)$", raw_out=raw)

    assert tag == "2.0.1"
    assert raw == {"github_tag": "release-2.0.1"}


def test_resolve_github_tag_does_not_fall_back_to_unauthenticated_request_for_tls_error() -> None:
    requests: list[httpx.Request] = []
    transport_error = httpx.ConnectError(
        "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise transport_error

    service = ResolverService(
        token="bad-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_tag("owner/repo")

    assert exc_info.value.reason_code == "github_tls_error"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "tag"
    assert exc_info.value.__cause__ is transport_error
    assert len(requests) == 1
    assert [request.headers.get("Authorization") for request in requests] == [
        "Bearer bad-token",
    ]


def test_resolve_github_tag_falls_back_to_tags_when_latest_release_is_not_found() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(404, json={"message": "Not Found"})
        if request.url.path.endswith("/tags"):
            return httpx.Response(200, json=[{"name": "v1.2.3"}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = ResolverService(transport=httpx.MockTransport(handler))

    tag = service.resolve_github_tag("owner/repo")

    assert tag == "1.2.3"
    assert requests == [
        "/repos/owner/repo/releases/latest",
        "/repos/owner/repo/tags",
    ]


def test_resolve_github_tag_raises_tls_user_error() -> None:
    transport_error = httpx.ConnectError(
        "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise transport_error

    service = ResolverService(transport=httpx.MockTransport(handler))

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_tag("owner/repo")

    assert exc_info.value.reason_code == "github_tls_error"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "tag"
    assert str(exc_info.value) == (
        "GitHub tag lookup failed for owner/repo: "
        "TLS connection failed (UNEXPECTED_EOF_WHILE_READING)"
    )
    assert exc_info.value.__cause__ is transport_error


def test_resolve_github_tag_raises_access_denied_user_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Forbidden"})

    service = ResolverService(transport=httpx.MockTransport(handler))

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_tag("owner/repo")

    assert exc_info.value.reason_code == "github_access_denied"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "tag"
    assert str(exc_info.value) == "GitHub tag lookup failed for owner/repo: GitHub access denied"
    assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)


def test_resolve_github_tag_raises_not_found_user_error_for_tags_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(404, json={"message": "Not Found"})
        if request.url.path.endswith("/tags"):
            return httpx.Response(404, json={"message": "Not Found"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = ResolverService(transport=httpx.MockTransport(handler))

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_tag("owner/repo")

    assert exc_info.value.reason_code == "github_not_found"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "tag"
    assert str(exc_info.value) == "GitHub tag lookup failed for owner/repo: repository not found"


def test_resolve_github_tag_raises_server_error_user_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"message": "Bad Gateway"})

    service = ResolverService(transport=httpx.MockTransport(handler))

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_tag("owner/repo")

    assert exc_info.value.reason_code == "github_server_error"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "tag"
    assert str(exc_info.value) == "GitHub tag lookup failed for owner/repo: GitHub server error (HTTP 502)"


def test_resolve_github_tag_raises_payload_user_error_for_unexpected_release_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = ResolverService(transport=httpx.MockTransport(handler))

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_tag("owner/repo")

    assert exc_info.value.reason_code == "github_payload_error"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "tag"
    assert str(exc_info.value) == (
        "GitHub tag lookup failed for owner/repo: "
        "expected a dict payload for latest release"
    )


def test_resolve_github_tag_raises_payload_user_error_for_invalid_release_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, content=b"{")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = ResolverService(transport=httpx.MockTransport(handler))

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_tag("owner/repo")

    assert exc_info.value.reason_code == "github_payload_error"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "tag"
    assert str(exc_info.value) == (
        "GitHub tag lookup failed for owner/repo: "
        "invalid JSON payload for latest release"
    )
    assert isinstance(exc_info.value.__cause__, ValueError)

def test_resolve_github_sha_details_returns_per_repo_mapping() -> None:
    responses = {
        "/repos/caddy-dns/cloudflare/commits": [{"sha": "abc123"}],
        "/repos/caddyserver/replace-response/commits": [{"sha": "def456"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses[request.url.path])

    service = ResolverService(transport=httpx.MockTransport(handler))

    details = service.resolve_github_sha_details(
        ["caddy-dns/cloudflare", "caddyserver/replace-response"]
    )

    assert details == {
        "caddy-dns/cloudflare": "abc123",
        "caddyserver/replace-response": "def456",
    }



def test_resolve_github_sha_matches_legacy_shell_digest_format() -> None:
    responses = {
        "/repos/caddy-dns/cloudflare/commits": [{"sha": "abc123"}],
        "/repos/caddyserver/replace-response/commits": [{"sha": "def456"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses[request.url.path])

    service = ResolverService(transport=httpx.MockTransport(handler))

    digest = service.resolve_github_sha(
        ["caddy-dns/cloudflare", "caddyserver/replace-response"]
    )

    expected = hashlib.sha256(b"abc123 def456\n").hexdigest()
    assert digest == expected



def test_resolve_github_sha_preserves_input_order_when_hashing_duplicate_repos() -> None:
    responses = {
        "/repos/caddy-dns/cloudflare/commits": [{"sha": "abc123"}],
        "/repos/caddyserver/replace-response/commits": [{"sha": "def456"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses[request.url.path])

    service = ResolverService(transport=httpx.MockTransport(handler))

    digest = service.resolve_github_sha(
        [
            "caddy-dns/cloudflare",
            "caddyserver/replace-response",
            "caddy-dns/cloudflare",
        ]
    )

    expected = hashlib.sha256(b"abc123 def456 abc123\n").hexdigest()
    assert digest == expected



def test_resolve_target_builds_returns_structured_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_dir = tmp_path / "images" / "caddy"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        """
image_name: caddy
version: 1.2.3
targets:
  - name: rr
    version: 1.2.3
    sha:
      github_sha:
        repos:
          - caddy-dns/cloudflare
          - caddyserver/replace-response
""".strip()
        + "\n"
    )

    class FakeResolverService:
        def __init__(self, *, token: str | None = None, transport: object | None = None) -> None:
            self.token = token
            self.transport = transport

        def resolve_github_sha_details(self, repos: list[str]) -> dict[str, str]:
            assert repos == ["caddy-dns/cloudflare", "caddyserver/replace-response"]
            return {
                "caddy-dns/cloudflare": "abc123",
                "caddyserver/replace-response": "def456",
            }

        def resolve_github_sha(self, repos: list[str]) -> str:
            pytest.fail("structured resolver path should be primary")

        def resolve_github_tag(
            self,
            repo: str,
            regex: str | None = None,
            *,
            raw_out: dict[str, str] | None = None,
        ) -> str:
            pytest.fail("unexpected github tag resolution")

        def resolve_alpine_pkg(
            self,
            target: str,
            branch: str = "v3.21",
            repository: str = "main",
        ) -> str:
            pytest.fail("unexpected alpine package resolution")

        def resolve_regex_match(self, url: str, pattern: str) -> str:
            pytest.fail("unexpected regex resolution")

    monkeypatch.setattr("tooling.build.cli.ResolverService", FakeResolverService)

    builds = resolve_target_builds(
        repo_root=tmp_path,
        requested_targets=["caddy"],
        force=True,
        state_file=None,
    )

    assert builds == [
        BuildPlan(
            image_dir=image_dir,
            dockerfile="Dockerfile",
            target=ResolvedTargetState(
                image_name="caddy",
                target_name="rr",
                version="1.2.3",
                components={
                    "caddy-dns/cloudflare": "abc123",
                    "caddyserver/replace-response": "def456",
                },
            ),
            build_target=None,
            directory_name="caddy",
            version_source={
                "resolver": "literal",
                "kind": "literal",
                "value": "1.2.3",
            },
            component_sources={
                "caddy-dns/cloudflare": {
                    "resolver": "github_sha",
                    "kind": "resolver",
                    "repos": ["caddy-dns/cloudflare", "caddyserver/replace-response"],
                    "repo": "caddy-dns/cloudflare",
                },
                "caddyserver/replace-response": {
                    "resolver": "github_sha",
                    "kind": "resolver",
                    "repos": ["caddy-dns/cloudflare", "caddyserver/replace-response"],
                    "repo": "caddyserver/replace-response",
                },
            },
            template=None,
            repos=["caddy-dns/cloudflare", "caddyserver/replace-response"],
        )
    ]


def test_resolve_target_builds_records_raw_github_tag_in_version_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_dir = tmp_path / "images" / "nezha-agent"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        """
image_name: nezha-agent
version:
  github_tag:
    repo: nezhahq/agent
targets:
  - {}
""".strip()
        + "\n"
    )

    class FakeResolverService:
        def __init__(self, *, token: str | None = None, transport: object | None = None) -> None:
            self.token = token
            self.transport = transport

        def resolve_github_sha_details(self, repos: list[str]) -> dict[str, str]:
            pytest.fail("unexpected github sha resolution")

        def resolve_github_sha(self, repos: list[str]) -> str:
            pytest.fail("unexpected github sha digest resolution")

        def resolve_github_tag(
            self,
            repo: str,
            regex: str | None = None,
            *,
            raw_out: dict[str, str] | None = None,
        ) -> str:
            assert repo == "nezhahq/agent"
            if raw_out is not None:
                raw_out["github_tag"] = "v2.3.5"
            return "2.3.5"

        def resolve_alpine_pkg(
            self,
            target: str,
            branch: str = "v3.21",
            repository: str = "main",
        ) -> str:
            pytest.fail("unexpected alpine package resolution")

        def resolve_regex_match(self, url: str, pattern: str) -> str:
            pytest.fail("unexpected regex resolution")

    monkeypatch.setattr("tooling.build.cli.ResolverService", FakeResolverService)

    builds = resolve_target_builds(
        repo_root=tmp_path,
        requested_targets=["nezha-agent"],
        force=True,
        state_file=None,
    )

    assert builds[0].version_source == {
        "resolver": "github_tag",
        "kind": "resolver",
        "repo": "nezhahq/agent",
        "raw_tag": "v2.3.5",
    }


def test_resolve_target_builds_wraps_image_level_resolver_error_with_default_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        """
version:
  github_tag:
    repo: owner/repo
targets:
  - {}
""".strip()
        + "\n"
    )

    class FakeResolverService:
        def __init__(self, *, token: str | None = None, transport: object | None = None) -> None:
            pass

        def resolve_github_tag(
            self,
            repo: str,
            regex: str | None = None,
            *,
            raw_out: dict[str, str] | None = None,
        ) -> str:
            raise ResolverUserError(
                reason_code="github_tls_error",
                message="GitHub tag lookup failed for owner/repo: TLS connection failed",
                repo=repo,
                resolver_kind="tag",
            )

        def resolve_github_sha(self, repos: list[str]) -> str:
            pytest.fail("unexpected github sha resolution")

        def resolve_github_sha_details(self, repos: list[str]) -> dict[str, str]:
            pytest.fail("unexpected github sha detail resolution")

        def resolve_alpine_pkg(
            self,
            target: str,
            branch: str = "v3.21",
            repository: str = "main",
        ) -> str:
            pytest.fail("unexpected alpine package resolution")

        def resolve_regex_match(self, url: str, pattern: str) -> str:
            pytest.fail("unexpected regex resolution")

    monkeypatch.setattr("tooling.build.cli.ResolverService", FakeResolverService)

    with pytest.raises(BuildUserError) as exc_info:
        resolve_target_builds(
            repo_root=tmp_path,
            requested_targets=["tg-signer"],
            force=True,
            state_file=None,
        )

    assert exc_info.value.reason_code == "github_tls_error"
    assert exc_info.value.image_name == "tg-signer"
    assert exc_info.value.target_name == "default"
    assert str(exc_info.value) == "GitHub tag lookup failed for owner/repo: TLS connection failed"


def test_resolve_target_builds_wraps_target_version_resolver_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        """
version: 1.0.0
targets:
  - name: release
    version:
      github_tag:
        repo: owner/repo
""".strip()
        + "\n"
    )

    class FakeResolverService:
        def __init__(self, *, token: str | None = None, transport: object | None = None) -> None:
            pass

        def resolve_github_tag(
            self,
            repo: str,
            regex: str | None = None,
            *,
            raw_out: dict[str, str] | None = None,
        ) -> str:
            raise ResolverUserError(
                reason_code="github_tls_error",
                message="GitHub tag lookup failed for owner/repo: TLS connection failed",
                repo=repo,
                resolver_kind="tag",
            )

        def resolve_github_sha(self, repos: list[str]) -> str:
            pytest.fail("unexpected github sha resolution")

        def resolve_github_sha_details(self, repos: list[str]) -> dict[str, str]:
            pytest.fail("unexpected github sha detail resolution")

        def resolve_alpine_pkg(
            self,
            target: str,
            branch: str = "v3.21",
            repository: str = "main",
        ) -> str:
            pytest.fail("unexpected alpine package resolution")

        def resolve_regex_match(self, url: str, pattern: str) -> str:
            pytest.fail("unexpected regex resolution")

    monkeypatch.setattr("tooling.build.cli.ResolverService", FakeResolverService)

    with pytest.raises(BuildUserError) as exc_info:
        resolve_target_builds(
            repo_root=tmp_path,
            requested_targets=["tg-signer"],
            force=True,
            state_file=None,
        )

    assert exc_info.value.reason_code == "github_tls_error"
    assert exc_info.value.image_name == "tg-signer"
    assert exc_info.value.target_name == "release"
    assert str(exc_info.value) == "GitHub tag lookup failed for owner/repo: TLS connection failed"


def test_resolve_target_builds_wraps_target_components_resolver_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        """
version: 1.0.0
targets:
  - name: release
    sha:
      github_sha:
        repos:
          - owner/repo
""".strip()
        + "\n"
    )

    class FakeResolverService:
        def __init__(self, *, token: str | None = None, transport: object | None = None) -> None:
            pass

        def resolve_github_tag(
            self,
            repo: str,
            regex: str | None = None,
            *,
            raw_out: dict[str, str] | None = None,
        ) -> str:
            pytest.fail("unexpected github tag resolution")

        def resolve_github_sha(self, repos: list[str]) -> str:
            pytest.fail("unexpected github sha resolution")

        def resolve_github_sha_details(self, repos: list[str]) -> dict[str, str]:
            raise ResolverUserError(
                reason_code="github_rate_limited",
                message="GitHub commit lookup failed for owner/repo: GitHub rate limit exceeded",
                repo="owner/repo",
                resolver_kind="commit",
            )

        def resolve_alpine_pkg(
            self,
            target: str,
            branch: str = "v3.21",
            repository: str = "main",
        ) -> str:
            pytest.fail("unexpected alpine package resolution")

        def resolve_regex_match(self, url: str, pattern: str) -> str:
            pytest.fail("unexpected regex resolution")

    monkeypatch.setattr("tooling.build.cli.ResolverService", FakeResolverService)

    with pytest.raises(BuildUserError) as exc_info:
        resolve_target_builds(
            repo_root=tmp_path,
            requested_targets=["tg-signer"],
            force=True,
            state_file=None,
        )

    assert exc_info.value.reason_code == "github_rate_limited"
    assert exc_info.value.image_name == "tg-signer"
    assert exc_info.value.target_name == "release"
    assert str(exc_info.value) == "GitHub commit lookup failed for owner/repo: GitHub rate limit exceeded"


def test_resolve_alpine_pkg_extracts_version_from_html() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(
            200,
            text=(
                "<html><body>"
                "<table>"
                "<tr><th class=\"header\">Package</th><td>tor</td></tr>"
                "<tr><th class=\"header\">Version</th><td><strong>1.2.3-r0</strong></td></tr>"
                "</table>"
                "</body></html>"
            ),
        )

    service = ResolverService(transport=httpx.MockTransport(handler))

    version = service.resolve_alpine_pkg("tor")

    assert version == "1.2.3-r0"
    assert seen_urls == [
        "https://pkgs.alpinelinux.org/package/v3.21/main/x86_64/tor"
    ]


def test_resolve_alpine_pkg_extracts_version_from_version_row_when_strong_has_attributes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                "<html><body>"
                "<table>"
                "<tr><th class=\"header\">Package</th><td>tor</td></tr>"
                "<tr><th class=\"header\">Version</th><td><strong class=\"hint\" aria-label=\"Flagged as: 1.2.4-r0\">1.2.3-r0</strong></td></tr>"
                "</table>"
                "</body></html>"
            ),
        )

    service = ResolverService(transport=httpx.MockTransport(handler))

    version = service.resolve_alpine_pkg("tor")

    assert version == "1.2.3-r0"


def test_resolve_alpine_pkg_ignores_non_version_strong_values() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                "<html><body>"
                "<strong>checksum</strong>"
                "<table>"
                "<tr><th class=\"header\">Package</th><td>tor</td></tr>"
                "<tr><th class=\"header\">Version</th><td><strong>1.2.3-r0</strong></td></tr>"
                "</table>"
                "</body></html>"
            ),
        )

    service = ResolverService(transport=httpx.MockTransport(handler))

    version = service.resolve_alpine_pkg("tor")

    assert version == "1.2.3-r0"


def test_resolve_regex_match_returns_first_capture_group() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<div>version=9.9.9</div>")

    service = ResolverService(transport=httpx.MockTransport(handler))

    value = service.resolve_regex_match(
        "https://example.invalid",
        r"version=(\d+\.\d+\.\d+)",
    )

    assert value == "9.9.9"



def test_resolve_docker_hub_tag_returns_first_matching_capture_group_across_pages() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.params.get("page") == "2":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"name": "2.11.2-alpine"},
                        {"name": "2.11.2"},
                    ],
                    "next": None,
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {"name": "latest"},
                    {"name": "builder-alpine"},
                ],
                "next": "https://hub.docker.com/v2/namespaces/library/repositories/caddy/tags?page=2",
            },
        )

    service = ResolverService(transport=httpx.MockTransport(handler))

    assert hasattr(service, "resolve_docker_hub_tag")
    value = service.resolve_docker_hub_tag(
        namespace="library",
        repository="caddy",
        regex=r"^(\d+\.\d+\.\d+)-alpine$",
    )

    assert value == "2.11.2"
    assert requests == [
        "https://hub.docker.com/v2/namespaces/library/repositories/caddy/tags?page_size=100",
        "https://hub.docker.com/v2/namespaces/library/repositories/caddy/tags?page=2",
    ]



def test_resolve_github_sha_raises_timeout_user_error() -> None:
    transport_error = httpx.ReadTimeout("timed out")

    def handler(request: httpx.Request) -> httpx.Response:
        raise transport_error

    service = ResolverService(transport=httpx.MockTransport(handler))

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_sha(["owner/repo"])

    assert exc_info.value.reason_code == "github_timeout"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "commit"
    assert str(exc_info.value) == (
        "GitHub commit lookup failed for owner/repo: "
        "GitHub request timed out"
    )


def test_resolve_github_sha_raises_rate_limited_user_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0"},
            json={"message": "API rate limit exceeded"},
        )

    service = ResolverService(transport=httpx.MockTransport(handler))

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_sha_details(["owner/repo"])

    assert exc_info.value.reason_code == "github_rate_limited"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "commit"
    assert str(exc_info.value) == (
        "GitHub commit lookup failed for owner/repo: "
        "GitHub rate limit exceeded"
    )


def test_resolve_github_sha_raises_payload_user_error_for_empty_commits_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    service = ResolverService(transport=httpx.MockTransport(handler))

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_sha(["owner/repo"])

    assert exc_info.value.reason_code == "github_payload_error"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "commit"
    assert str(exc_info.value) == (
        "GitHub commit lookup failed for owner/repo: "
        "expected a non-empty list payload"
    )


def test_resolve_github_sha_raises_not_found_user_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    service = ResolverService(transport=httpx.MockTransport(handler))

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_sha_details(["owner/repo"])

    assert exc_info.value.reason_code == "github_not_found"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "commit"
    assert str(exc_info.value) == (
        "GitHub commit lookup failed for owner/repo: "
        "repository not found"
    )



def test_resolve_github_tag_raises_contextual_error_for_unexpected_release_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = ResolverService(transport=httpx.MockTransport(handler))

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_tag("owner/repo")

    assert exc_info.value.reason_code == "github_payload_error"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "tag"
    assert str(exc_info.value) == (
        "GitHub tag lookup failed for owner/repo: "
        "expected a dict payload for latest release"
    )



def test_resolve_github_tag_raises_contextual_error_for_unexpected_tags_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json={"tag_name": None})
        if request.url.path.endswith("/tags"):
            return httpx.Response(200, json=[{"name": None}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    service = ResolverService(transport=httpx.MockTransport(handler))

    with pytest.raises(ResolverUserError) as exc_info:
        service.resolve_github_tag("owner/repo")

    assert exc_info.value.reason_code == "github_payload_error"
    assert exc_info.value.repo == "owner/repo"
    assert exc_info.value.resolver_kind == "tag"
    assert str(exc_info.value) == (
        "GitHub tag lookup failed for owner/repo: "
        "field 'name' must be a non-empty string"
    )


def test_resolver_user_error_str_returns_message() -> None:
    from tooling.build.errors import ResolverUserError

    error = ResolverUserError(
        reason_code="github_api_error",
        message="GitHub request failed",
        repo="owner/repo",
        resolver_kind="github_tag",
    )

    assert str(error) == "GitHub request failed"
    assert error.reason_code == "github_api_error"
    assert error.repo == "owner/repo"
    assert error.resolver_kind == "github_tag"


def test_build_user_error_str_returns_message() -> None:
    from tooling.build.errors import BuildUserError

    error = BuildUserError(
        reason_code="build_failed",
        message="Docker build failed",
        image_name="caddy",
        target_name="rr",
    )

    assert str(error) == "Docker build failed"
    assert error.reason_code == "build_failed"
    assert error.image_name == "caddy"
    assert error.target_name == "rr"
