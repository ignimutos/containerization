from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import (
    AlpinePkgArgs,
    BuildConfig,
    DockerHubTagArgs,
    GitHubShaArgs,
    GitHubTagArgs,
    RegexMatchArgs,
    ResolverSpec,
    TargetConfig,
)


@dataclass(slots=True)
class LoadedImageConfig:
    image_dir: Path
    config_path: Path
    config: BuildConfig

    @property
    def directory_name(self) -> str:
        return self.image_dir.name

    @property
    def repo_name(self) -> str:
        return self.config.image_name


def discover_image_configs(repo_root: str | Path) -> list[Path]:
    repo_root = Path(repo_root)
    return sorted((repo_root / "images").glob("*/config.yml"))


def load_all_configs(repo_root: str | Path) -> list[LoadedImageConfig]:
    return [
        LoadedImageConfig(
            image_dir=config_path.parent,
            config_path=config_path,
            config=load_build_config(config_path.parent),
        )
        for config_path in discover_image_configs(repo_root)
    ]


def load_build_config(image_dir: str | Path) -> BuildConfig:
    image_dir = Path(image_dir)
    config_path = image_dir / "config.yml"
    if not config_path.exists():
        return BuildConfig(image_name=image_dir.name)

    raw_data = yaml.safe_load(config_path.read_text())
    if raw_data is None:
        raw_data = {}
    if not isinstance(raw_data, dict):
        raise ValueError("config.yml must contain a mapping")

    image_name = _load_string_field(raw_data, "name", "name") or image_dir.name
    raw_targets = raw_data.get("targets", [])
    if raw_targets is None:
        raw_targets = []
    if not isinstance(raw_targets, list):
        raise ValueError("targets must be a list")

    return BuildConfig(
        image_name=image_name,
        version=_load_resolver_field(raw_data, "version", "version"),
        targets=[_load_target_config(item) for item in raw_targets],
    )


def _load_target_config(raw_target: Any) -> TargetConfig:
    if not isinstance(raw_target, dict):
        raise ValueError("each target must be a mapping")

    dockerfile = _load_string_field(raw_target, "dockerfile", "targets[].dockerfile") or "Dockerfile"
    name = _load_string_field(raw_target, "name", "targets[].name")
    if name == "base":
        raise ValueError("targets[].name must not be 'base'")

    return TargetConfig(
        target=_load_string_field(raw_target, "target", "targets[].target"),
        name=name,
        version=_load_resolver_field(raw_target, "version", "targets[].version"),
        sha=_load_resolver_field(raw_target, "sha", "targets[].sha"),
        dockerfile=dockerfile,
        template=_load_string_field(raw_target, "template", "targets[].template"),
    )


def _load_string_field(raw_data: dict[str, Any], key: str, label: str) -> str | None:
    value = raw_data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _load_resolver_field(raw_data: dict[str, Any], key: str, label: str) -> str | ResolverSpec | None:
    value = raw_data.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a string or mapping")
    return _parse_resolver_spec(value, label)


def _parse_resolver_spec(value: dict[str, Any], label: str) -> ResolverSpec:
    resolvers: dict[str, Any] = {}
    for resolver_name in ("github_tag", "github_sha", "alpine_pkg", "docker_hub_tag", "regex_match"):
        if resolver_name not in value:
            continue
        resolver_value = value[resolver_name]
        if not isinstance(resolver_value, dict):
            raise ValueError(f"{label}.{resolver_name} must be a mapping")
        resolvers[resolver_name] = _build_resolver_args(resolver_name, resolver_value, f"{label}.{resolver_name}")
    return ResolverSpec(**resolvers)


def _build_resolver_args(resolver_name: str, resolver_value: dict[str, Any], label: str) -> Any:
    if resolver_name == "github_tag":
        repo = _require_string_field(resolver_value, "repo", f"{label}.repo")
        regex = _optional_string_field(resolver_value, "regex", f"{label}.regex")
        return GitHubTagArgs(repo=repo, regex=regex)
    if resolver_name == "github_sha":
        repos = resolver_value.get("repos")
        if not isinstance(repos, list) or not repos or any(not isinstance(repo, str) for repo in repos):
            raise ValueError(f"{label}.repos must be a non-empty list of strings")
        return GitHubShaArgs(repos=repos)
    if resolver_name == "alpine_pkg":
        package = _require_string_field(resolver_value, "package", f"{label}.package")
        branch = _optional_string_field(resolver_value, "branch", f"{label}.branch") or "v3.21"
        repository = _optional_string_field(resolver_value, "repository", f"{label}.repository") or "main"
        return AlpinePkgArgs(package=package, branch=branch, repository=repository)
    if resolver_name == "docker_hub_tag":
        namespace = _require_string_field(resolver_value, "namespace", f"{label}.namespace")
        repository = _require_string_field(resolver_value, "repository", f"{label}.repository")
        regex = _optional_string_field(resolver_value, "regex", f"{label}.regex")
        return DockerHubTagArgs(namespace=namespace, repository=repository, regex=regex)
    if resolver_name == "regex_match":
        url = _require_string_field(resolver_value, "url", f"{label}.url")
        pattern = _require_string_field(resolver_value, "pattern", f"{label}.pattern")
        return RegexMatchArgs(url=url, pattern=pattern)
    raise ValueError(f"unsupported resolver: {resolver_name}")


def _require_string_field(raw_data: dict[str, Any], key: str, label: str) -> str:
    value = _optional_string_field(raw_data, key, label)
    if value is None or value == "":
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _optional_string_field(raw_data: dict[str, Any], key: str, label: str) -> str | None:
    value = raw_data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value
