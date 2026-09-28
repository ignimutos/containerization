from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Iterable


_IGNORED_VERSIONS = frozenset({"", "null"})


@dataclass(slots=True)
class GitHubTagArgs:
    repo: str
    regex: str | None = None


@dataclass(slots=True)
class GitHubShaArgs:
    repos: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AlpinePkgArgs:
    package: str
    branch: str = "v3.21"
    repository: str = "main"


@dataclass(slots=True)
class DockerHubTagArgs:
    namespace: str
    repository: str
    regex: str | None = None


@dataclass(slots=True)
class RegexMatchArgs:
    url: str
    pattern: str


@dataclass(slots=True)
class ResolverSpec:
    github_tag: GitHubTagArgs | None = None
    github_sha: GitHubShaArgs | None = None
    alpine_pkg: AlpinePkgArgs | None = None
    docker_hub_tag: DockerHubTagArgs | None = None
    regex_match: RegexMatchArgs | None = None

    def __post_init__(self) -> None:
        values = [self.github_tag, self.github_sha, self.alpine_pkg, self.docker_hub_tag, self.regex_match]
        if sum(value is not None for value in values) != 1:
            raise ValueError("resolver spec must define exactly one resolver")


@dataclass(slots=True)
class TargetConfig:
    target: str | None = None
    name: str | None = None
    version: str | ResolverSpec | None = None
    sha: str | ResolverSpec | None = None
    dockerfile: str = "Dockerfile"
    template: str | None = None


@dataclass(slots=True)
class BuildConfig:
    image_name: str
    version: str | ResolverSpec | None = None
    targets: list[TargetConfig] = field(default_factory=list)


@dataclass(slots=True)
class TargetState:
    version: str | None = None
    components: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ResolvedTargetState:
    image_name: str
    target_name: str | None = None
    version: str | None = None
    components: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_legacy(
        cls,
        image_name: str | None,
        target_name: str | None,
        version: str | None,
        sha: str | None,
    ) -> "ResolvedTargetState":
        if image_name is None:
            image_name = ""
        components = {"sha": sha} if sha else {}
        return cls(
            image_name=image_name,
            target_name=target_name,
            version=version,
            components=components,
        )

    def __post_init__(self) -> None:
        self.components = _normalize_components(self.components)

    def to_target_state(self) -> TargetState | None:
        normalized_version = None if self.version in _IGNORED_VERSIONS else self.version
        if normalized_version is None and not self.components:
            return None
        return TargetState(version=normalized_version, components=dict(self.components))


def _iter_present_values(values: Iterable[str | None]) -> Iterable[str]:
    for value in values:
        if value:
            yield value


def _normalize_components(
    components: Mapping[str, str] | Iterable[str],
) -> dict[str, str]:
    if isinstance(components, Mapping):
        normalized = dict(components)
    else:
        normalized = {
            str(index): value
            for index, value in enumerate(_iter_present_values(components))
        }
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in normalized.items()):
        raise ValueError("components must be string mappings")
    return normalized
