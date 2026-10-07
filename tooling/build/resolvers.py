from __future__ import annotations

import hashlib
import re

import httpx

from .errors import ResolverUserError

_TLS_MARKERS = ("SSL", "TLS", "CERT", "UNEXPECTED_EOF_WHILE_READING")
_BRACKETED_TOKEN_RE = re.compile(r"\[([^\]]+)\]")


def _github_lookup_message(resolver_kind: str, repo: str, reason: str) -> str:
    return f"GitHub {resolver_kind} lookup failed for {repo}: {reason}"


def _raise_github_payload_error(
    *,
    resolver_kind: str,
    repo: str,
    reason: str,
    cause: Exception | None = None,
) -> None:
    if cause is None:
        raise ResolverUserError(
            reason_code="github_payload_error",
            message=_github_lookup_message(resolver_kind, repo, reason),
            repo=repo,
            resolver_kind=resolver_kind,
        )

    raise ResolverUserError(
        reason_code="github_payload_error",
        message=_github_lookup_message(resolver_kind, repo, reason),
        repo=repo,
        resolver_kind=resolver_kind,
    ) from cause


def _tls_token_from_text(text: str) -> str | None:
    match = _BRACKETED_TOKEN_RE.search(text)
    if match is None:
        return None

    tokens = re.findall(r"[A-Z][A-Z0-9_:-]*", match.group(1))
    if not tokens:
        return None
    return tokens[-1]


def _raise_github_request_error(
    exc: httpx.RequestError,
    *,
    resolver_kind: str,
    repo: str,
) -> None:
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout)):
        raise ResolverUserError(
            reason_code="github_timeout",
            message=_github_lookup_message(resolver_kind, repo, "GitHub request timed out"),
            repo=repo,
            resolver_kind=resolver_kind,
        ) from exc

    if isinstance(exc, httpx.ConnectError):
        text = str(exc)
        upper_text = text.upper()
        if any(marker in upper_text for marker in _TLS_MARKERS):
            token = _tls_token_from_text(text)
            reason = (
                f"TLS connection failed ({token})"
                if token is not None
                else "TLS connection failed"
            )
            raise ResolverUserError(
                reason_code="github_tls_error",
                message=_github_lookup_message(resolver_kind, repo, reason),
                repo=repo,
                resolver_kind=resolver_kind,
            ) from exc

        raise ResolverUserError(
            reason_code="github_connection_error",
            message=_github_lookup_message(resolver_kind, repo, "Network connection failed"),
            repo=repo,
            resolver_kind=resolver_kind,
        ) from exc

    raise ResolverUserError(
        reason_code="github_request_error",
        message=_github_lookup_message(resolver_kind, repo, "GitHub request failed"),
        repo=repo,
        resolver_kind=resolver_kind,
    ) from exc


def _github_response_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""

    if not isinstance(payload, dict):
        return ""

    message = payload.get("message")
    return message if isinstance(message, str) else ""


def _raise_github_status_error(
    response: httpx.Response,
    *,
    resolver_kind: str,
    repo: str,
) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = response.status_code

        if status == 401:
            raise ResolverUserError(
                reason_code="github_auth_failed",
                message=_github_lookup_message(resolver_kind, repo, "authentication failed"),
                repo=repo,
                resolver_kind=resolver_kind,
            ) from exc

        if status == 403:
            lowered = _github_response_message(response).lower()
            if (
                response.headers.get("x-ratelimit-remaining") == "0"
                or response.headers.get("retry-after")
                or "rate limit" in lowered
            ):
                raise ResolverUserError(
                    reason_code="github_rate_limited",
                    message=_github_lookup_message(resolver_kind, repo, "GitHub rate limit exceeded"),
                    repo=repo,
                    resolver_kind=resolver_kind,
                ) from exc

            raise ResolverUserError(
                reason_code="github_access_denied",
                message=_github_lookup_message(resolver_kind, repo, "GitHub access denied"),
                repo=repo,
                resolver_kind=resolver_kind,
            ) from exc

        if status == 404:
            raise ResolverUserError(
                reason_code="github_not_found",
                message=_github_lookup_message(resolver_kind, repo, "repository not found"),
                repo=repo,
                resolver_kind=resolver_kind,
            ) from exc

        if status == 429:
            raise ResolverUserError(
                reason_code="github_rate_limited",
                message=_github_lookup_message(resolver_kind, repo, "GitHub rate limit exceeded"),
                repo=repo,
                resolver_kind=resolver_kind,
            ) from exc

        if 500 <= status <= 599:
            raise ResolverUserError(
                reason_code="github_server_error",
                message=_github_lookup_message(resolver_kind, repo, f"GitHub server error (HTTP {status})"),
                repo=repo,
                resolver_kind=resolver_kind,
            ) from exc

        raise ResolverUserError(
            reason_code="github_http_error",
            message=_github_lookup_message(resolver_kind, repo, f"GitHub request failed (HTTP {status})"),
            repo=repo,
            resolver_kind=resolver_kind,
        ) from exc


class ResolverService:
    def __init__(
        self,
        *,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = token
        self._client = httpx.Client(transport=transport, follow_redirects=True)

    def resolve_github_tag(
        self,
        repo: str,
        regex: str | None = None,
        *,
        raw_out: dict[str, str] | None = None,
    ) -> str:
        if not repo:
            raise ValueError("repo must not be empty")

        tag = self._resolve_github_tag_with_auth(repo, use_token=bool(self._token))
        if tag is None and self._token:
            tag = self._resolve_github_tag_with_auth(repo, use_token=False)
        if tag is None:
            raise ValueError(f"Unable to resolve latest tag for '{repo}'")

        if raw_out is not None and tag:
            raw_out["github_tag"] = tag

        tag = tag.removeprefix("v")
        if regex:
            match = re.search(regex, tag)
            if match is None:
                raise ValueError(f"Tag '{tag}' does not match regex '{regex}'")
            group = match.group(1) if match.lastindex else match.group(0)
            if not group:
                raise ValueError(f"Tag '{tag}' does not match regex '{regex}'")
            return group
        return tag

    def resolve_github_sha_details(self, repos: list[str]) -> dict[str, str]:
        if not repos:
            raise ValueError("at least one repo is required")

        details: dict[str, str] = {}
        for repo in repos:
            try:
                response = self._client.get(
                    f"https://api.github.com/repos/{repo}/commits",
                    params={"per_page": 1, "page": 1},
                    headers=self._github_headers(),
                )
            except httpx.RequestError as exc:
                _raise_github_request_error(exc, resolver_kind="commit", repo=repo)

            if response.status_code >= 400:
                _raise_github_status_error(response, resolver_kind="commit", repo=repo)

            try:
                payload = response.json()
            except ValueError as exc:
                _raise_github_payload_error(
                    resolver_kind="commit",
                    repo=repo,
                    reason="invalid JSON payload for commits list",
                    cause=exc,
                )

            details[repo] = self._extract_github_list_field(
                payload,
                repo=repo,
                field="sha",
                resolver_kind="commit",
            )
        return details

    def resolve_github_sha(self, repos: list[str]) -> str:
        details = self.resolve_github_sha_details(repos)
        ordered_shas = [details[repo] for repo in repos]
        digest_input = f"{' '.join(ordered_shas)}\n".encode()
        return hashlib.sha256(digest_input).hexdigest()

    def resolve_regex_match(self, url: str, pattern: str) -> str:
        if not url:
            raise ValueError("url must not be empty")
        if not pattern:
            raise ValueError("pattern must not be empty")

        response = self._client.get(url)
        response.raise_for_status()

        match = re.search(pattern, response.text)
        if match is None:
            raise ValueError(f"Pattern '{pattern}' did not match '{url}'")
        if match.lastindex:
            return match.group(1)
        return match.group(0)

    def resolve_docker_hub_tag(
        self,
        namespace: str,
        repository: str,
        regex: str | None = None,
    ) -> str:
        if not namespace:
            raise ValueError("namespace must not be empty")
        if not repository:
            raise ValueError("repository must not be empty")

        next_url = f"https://hub.docker.com/v2/namespaces/{namespace}/repositories/{repository}/tags"
        params: dict[str, str] | None = {"page_size": "100"}
        while next_url:
            response = self._client.get(next_url, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("expected a dict payload for Docker Hub tags")

            results = payload.get("results")
            if not isinstance(results, list):
                raise ValueError("expected a list payload for Docker Hub tags")

            for item in results:
                if not isinstance(item, dict):
                    raise ValueError("expected Docker Hub tag entries to be mappings")
                name = item.get("name")
                if not isinstance(name, str) or not name:
                    raise ValueError("expected Docker Hub tag names to be non-empty strings")
                if regex is None:
                    return name
                match = re.search(regex, name)
                if match is None:
                    continue
                if match.lastindex:
                    group = match.group(1)
                    if group:
                        return group
                    continue
                return match.group(0)

            raw_next = payload.get("next")
            if raw_next in {None, ""}:
                break
            if not isinstance(raw_next, str):
                raise ValueError("expected Docker Hub next page URL to be a string")
            next_url = raw_next
            params = None

        if regex is None:
            raise ValueError(f"Unable to resolve latest Docker Hub tag for '{namespace}/{repository}'")
        raise ValueError(f"No Docker Hub tags for '{namespace}/{repository}' matched regex '{regex}'")

    def resolve_alpine_pkg(
        self,
        target: str,
        branch: str = "v3.21",
        repository: str = "main",
    ) -> str:
        if not target:
            raise ValueError("target must not be empty")

        return self.resolve_regex_match(
            f"https://pkgs.alpinelinux.org/package/{branch}/{repository}/x86_64/{target}",
            r'<th class="header">Version</th>\s*<td>\s*<strong(?:\s[^>]*)?>(.*?)</strong>',
        )

    def _resolve_github_tag_with_auth(self, repo: str, *, use_token: bool) -> str | None:
        try:
            release_response = self._client.get(
                f"https://api.github.com/repos/{repo}/releases/latest",
                headers=self._github_headers(use_token=use_token),
            )
        except httpx.RequestError as exc:
            _raise_github_request_error(exc, resolver_kind="tag", repo=repo)
        if release_response.status_code == 401 and use_token:
            return None

        if release_response.status_code != 404:
            if release_response.status_code >= 400:
                _raise_github_status_error(release_response, resolver_kind="tag", repo=repo)

            try:
                release_payload = release_response.json()
            except ValueError as exc:
                _raise_github_payload_error(
                    resolver_kind="tag",
                    repo=repo,
                    reason="invalid JSON payload for latest release",
                    cause=exc,
                )

            if not isinstance(release_payload, dict):
                _raise_github_payload_error(
                    resolver_kind="tag",
                    repo=repo,
                    reason="expected a dict payload for latest release",
                )

            tag = release_payload.get("tag_name")
            if isinstance(tag, str) and tag:
                return tag
            if tag is not None:
                _raise_github_payload_error(
                    resolver_kind="tag",
                    repo=repo,
                    reason="field 'tag_name' must be a non-empty string",
                )

        try:
            tags_response = self._client.get(
                f"https://api.github.com/repos/{repo}/tags",
                params={"per_page": 1},
                headers=self._github_headers(use_token=use_token),
            )
        except httpx.RequestError as exc:
            _raise_github_request_error(exc, resolver_kind="tag", repo=repo)
        if tags_response.status_code == 401 and use_token:
            return None
        if tags_response.status_code >= 400:
            _raise_github_status_error(tags_response, resolver_kind="tag", repo=repo)

        try:
            tags_payload = tags_response.json()
        except ValueError as exc:
            _raise_github_payload_error(
                resolver_kind="tag",
                repo=repo,
                reason="invalid JSON payload for tags list",
                cause=exc,
            )

        if not isinstance(tags_payload, list) or not tags_payload:
            _raise_github_payload_error(
                resolver_kind="tag",
                repo=repo,
                reason="expected a non-empty list payload",
            )

        first_item = tags_payload[0]
        if not isinstance(first_item, dict):
            _raise_github_payload_error(
                resolver_kind="tag",
                repo=repo,
                reason="expected the first list item to be a dict",
            )

        tag_name = first_item.get("name")
        if not isinstance(tag_name, str) or not tag_name:
            _raise_github_payload_error(
                resolver_kind="tag",
                repo=repo,
                reason="field 'name' must be a non-empty string",
            )
        return tag_name

    def _extract_github_list_field(
        self,
        payload: object,
        *,
        repo: str,
        field: str,
        resolver_kind: str,
    ) -> str:
        if not isinstance(payload, list) or not payload:
            _raise_github_payload_error(
                resolver_kind=resolver_kind,
                repo=repo,
                reason="expected a non-empty list payload",
            )

        first_item = payload[0]
        if not isinstance(first_item, dict):
            _raise_github_payload_error(
                resolver_kind=resolver_kind,
                repo=repo,
                reason="expected the first list item to be a dict",
            )

        value = first_item.get(field)
        if not isinstance(value, str) or not value:
            _raise_github_payload_error(
                resolver_kind=resolver_kind,
                repo=repo,
                reason=f"field '{field}' must be a non-empty string",
            )
        return value

    def _github_headers(self, *, use_token: bool | None = None) -> dict[str, str]:
        if use_token is None:
            use_token = bool(self._token)
        if use_token and self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}
