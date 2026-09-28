from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(slots=True)
class BuildReportState:
    version: str | None = None
    components: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.components = dict(self.components)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in self.components.items()):
            raise ValueError("report state components must be string mappings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "components": dict(self.components),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "BuildReportState":
        if payload is None:
            return cls()
        version = payload.get("version")
        components = payload.get("components", {})
        if version is not None and not isinstance(version, str):
            raise ValueError("report state version must be a string or null")
        if not isinstance(components, Mapping):
            raise ValueError("report state components must be a mapping")
        return cls(version=version, components=dict(components))


@dataclass(slots=True)
class BuildReportEntry:
    image_key: str
    image_name: str
    target_name: str | None
    old_state: BuildReportState = field(default_factory=BuildReportState)
    new_state: BuildReportState = field(default_factory=BuildReportState)
    docker_tags: list[str] = field(default_factory=list)
    version_source: dict[str, Any] = field(default_factory=dict)
    component_sources: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.image_key == "":
            raise ValueError("report entry image_key must be a non-empty string")
        self.docker_tags = list(self.docker_tags)
        if any(not isinstance(tag, str) for tag in self.docker_tags):
            raise ValueError("docker tags must be strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_key": self.image_key,
            "image_name": self.image_name,
            "target_name": self.target_name,
            "old_state": self.old_state.to_dict(),
            "new_state": self.new_state.to_dict(),
            "docker_tags": list(self.docker_tags),
            "version_source": dict(self.version_source),
            "component_sources": {
                name: dict(source)
                for name, source in self.component_sources.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BuildReportEntry":
        if "version_source" not in payload or "component_sources" not in payload:
            raise ValueError("report entry requires version_source and component_sources")

        docker_tags = payload.get("docker_tags", [])
        if not isinstance(docker_tags, list):
            raise ValueError("docker_tags must be a list")

        version_source = payload["version_source"]
        if not isinstance(version_source, Mapping):
            raise ValueError("report entry version_source must be a mapping")

        component_sources = payload["component_sources"]
        if not isinstance(component_sources, Mapping):
            raise ValueError("report entry component_sources must be a mapping")
        if any(not isinstance(source, Mapping) for source in component_sources.values()):
            raise ValueError("report entry component_sources values must be mappings")

        image_name = str(payload["image_name"])
        image_key = payload.get("image_key")
        if not isinstance(image_key, str) or image_key == "":
            raise ValueError("report entry image_key must be a non-empty string")

        return cls(
            image_key=image_key,
            image_name=image_name,
            target_name=payload.get("target_name"),
            old_state=BuildReportState.from_dict(payload.get("old_state")),
            new_state=BuildReportState.from_dict(payload.get("new_state")),
            docker_tags=[str(tag) for tag in docker_tags],
            version_source=dict(version_source),
            component_sources={
                str(name): dict(source)
                for name, source in component_sources.items()
            },
        )


@dataclass(slots=True)
class BuildReport:
    entries: list[BuildReportEntry] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.metadata = dict(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "entries": [entry.to_dict() for entry in self.entries],
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BuildReport":
        raw_entries = payload.get("entries", [])
        if not isinstance(raw_entries, list):
            raise ValueError("entries must be a list")

        raw_metadata = payload.get("metadata", {})
        if raw_metadata is None:
            raw_metadata = {}
        if not isinstance(raw_metadata, Mapping):
            raise ValueError("metadata must be a mapping")

        return cls(
            entries=[BuildReportEntry.from_dict(entry) for entry in raw_entries],
            metadata=dict(raw_metadata),
        )

    def write_json(self, path: str | Path) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def read_json(cls, path: str | Path) -> "BuildReport":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("report payload must be a mapping")
        return cls.from_dict(payload)


@dataclass(slots=True)
class SummaryValue:
    text: str
    link: str | None = None


@dataclass(slots=True)
class SummaryDetailRow:
    component_name: str
    label: str
    source_link: str | None
    old_value: SummaryValue
    new_value: SummaryValue


@dataclass(slots=True)
class SummaryTag:
    text: str
    link: str | None


@dataclass(slots=True)
class SummaryEntry:
    image_name: str
    target_name: str
    old_version: SummaryValue
    new_version: SummaryValue
    detail_rows: list[SummaryDetailRow]
    tags: list[SummaryTag]


@dataclass(slots=True)
class SummaryModel:
    changed_targets: int
    header_rows: list[tuple[str, str]]
    entries: list[SummaryEntry]


def build_summary_model(report: BuildReport) -> SummaryModel:
    metadata: dict[str, Any] = dict(report.metadata)

    built_entries_count = _as_int(metadata.get("built_entries_count"))
    if built_entries_count is None:
        built_entries_count = len(report.entries)

    header_rows = _build_header_rows(metadata)

    entries: list[SummaryEntry] = []
    for entry in sorted(report.entries, key=lambda item: (item.image_name, item.target_name or "")):
        version_source_link = _source_link(entry.version_source)
        old_version = _value_with_links(
            entry.old_state.version,
            source=entry.version_source,
            source_link=version_source_link,
            raw_value=entry.new_state.version,
        )
        new_version = _value_with_links(
            entry.new_state.version,
            source=entry.version_source,
            source_link=version_source_link,
            raw_value=entry.new_state.version,
        )

        detail_rows = _build_changed_detail_rows(entry)

        tags = [SummaryTag(text=tag, link=_docker_tag_link(tag)) for tag in entry.docker_tags]
        entries.append(
            SummaryEntry(
                image_name=entry.image_name,
                target_name=entry.target_name or "default",
                old_version=old_version,
                new_version=new_version,
                detail_rows=detail_rows,
                tags=tags,
            )
        )

    return SummaryModel(
        changed_targets=built_entries_count,
        header_rows=header_rows,
        entries=entries,
    )


def _build_changed_detail_rows(entry: BuildReportEntry) -> list[SummaryDetailRow]:
    detail_rows: list[SummaryDetailRow] = []
    all_components = set(entry.old_state.components) | set(entry.new_state.components)
    for component_name in all_components:
        old_raw = entry.old_state.components.get(component_name)
        new_raw = entry.new_state.components.get(component_name)
        if old_raw == new_raw:
            continue
        if old_raw == entry.old_state.version and new_raw == entry.new_state.version:
            continue

        source = entry.component_sources.get(component_name, {})
        source_link = _source_link(source)
        detail_rows.append(
            SummaryDetailRow(
                component_name=component_name,
                label=_component_label(source, component_name),
                source_link=source_link,
                old_value=_value_with_links(
                    old_raw,
                    source=source,
                    source_link=source_link,
                    raw_value=new_raw,
                ),
                new_value=_value_with_links(
                    new_raw,
                    source=source,
                    source_link=source_link,
                    raw_value=new_raw,
                ),
            )
        )
    detail_rows.sort(key=lambda row: (row.label, row.component_name))
    return detail_rows


def render_summary_markdown(model: SummaryModel) -> str:
    lines = ["Build summary", f"Changed targets: {model.changed_targets}"]
    lines.extend(f"{name}: {value}" for name, value in model.header_rows)

    for entry in model.entries:
        lines.append("")
        lines.append(f"### {_safe_markdown(entry.image_name)}/{_safe_markdown(entry.target_name)}")
        lines.append(
            "version: "
            f"{_markdown_value(entry.old_version)} -> {_markdown_value(entry.new_version)}"
        )

        if entry.detail_rows:
            lines.append("<details>")
            lines.append("<summary>组件变动明细 / Component Changes</summary>")
            lines.append("")
            for row in entry.detail_rows:
                name = _markdown_link_or_text(row.label, row.source_link)
                lines.append(
                    f"- {name}: {_markdown_value(row.old_value)} -> {_markdown_value(row.new_value)}"
                )
            lines.append("</details>")

        if entry.tags:
            lines.append("tags:")
            for tag in entry.tags:
                lines.append(f"- {_markdown_link_or_text(tag.text, tag.link)}")

    return "\n".join(lines)


def render_summary_telegram_html(model: SummaryModel) -> str:
    lines = ["Build summary", f"Changed targets: {model.changed_targets}"]
    lines.extend(f"{_safe_html(name)}: {_safe_html(value)}" for name, value in model.header_rows)

    for entry in model.entries:
        lines.append("")
        lines.append(
            "<blockquote expandable>"
            f"<b>{_safe_html(entry.image_name)}/{_safe_html(entry.target_name)}</b>"
        )
        lines.append(
            "version: "
            f"{_html_value(entry.old_version)} -&gt; {_html_value(entry.new_version)}"
        )

        if entry.detail_rows:
            lines.append("组件变动明细 / Component Changes:")
            for row in entry.detail_rows:
                name = _html_link_or_text(row.label, row.source_link)
                lines.append(
                    "  "
                    f"{name}: {_html_value(row.old_value)} -&gt; {_html_value(row.new_value)}"
                )

        if entry.tags:
            lines.append("tags:")
            for tag in entry.tags:
                lines.append(f"  {_html_link_or_text(tag.text, tag.link)}")

        lines.append("</blockquote>")

    return "\n".join(lines)


def format_telegram_summary(report: BuildReport) -> str:
    return render_summary_telegram_html(build_summary_model(report))


def render_failure_summary_markdown(report: BuildReport) -> str:
    failure = _failure_metadata(report.metadata)

    image_name = _failure_text(failure.get("image_name"))
    target_name = _failure_text(failure.get("target_name"))

    lines = [
        "Build failed",
        f"Stage: {_safe_markdown(_failure_text(failure.get('stage')))}",
        f"Target: {_safe_markdown(_failure_target(image_name, target_name))}",
        f"Message: {_safe_markdown(_failure_text(failure.get('message')))}",
    ]

    exit_code = failure.get("exit_code")
    if exit_code is not None:
        lines.append(f"Exit code: {_safe_markdown(str(exit_code))}")

    command = failure.get("command")
    if command not in (None, ""):
        lines.append(f"Command: {_safe_markdown(str(command))}")

    if report.entries:
        lines.append(f"Successful entries: {len(report.entries)}")

    return "\n".join(lines)


def render_failure_summary_telegram_html(report: BuildReport) -> str:
    failure = _failure_metadata(report.metadata)

    image_name = _failure_text(failure.get("image_name"))
    target_name = _failure_text(failure.get("target_name"))

    lines = [
        "Build failed",
        f"Stage: {_safe_html(_failure_text(failure.get('stage')))}",
        f"Target: {_safe_html(_failure_target(image_name, target_name))}",
        f"Message: {_safe_html(_failure_text(failure.get('message')))}",
    ]

    exit_code = failure.get("exit_code")
    if exit_code is not None:
        lines.append(f"Exit code: {_safe_html(str(exit_code))}")

    command = failure.get("command")
    if command not in (None, ""):
        lines.append(f"Command: {_safe_html(str(command))}")

    if report.entries:
        lines.append(f"Successful entries: {len(report.entries)}")

    return "\n".join(lines)


def _failure_metadata(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    failure = metadata.get("failure", {})
    if isinstance(failure, Mapping):
        return failure
    return {}


def _failure_text(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    return str(value)


def _failure_target(image_name: str, target_name: str) -> str:
    if image_name == "N/A" and target_name == "N/A":
        return "N/A"
    if image_name == "N/A":
        return target_name
    if target_name == "N/A":
        return image_name
    return f"{image_name}/{target_name}"


def _build_header_rows(metadata: Mapping[str, Any]) -> list[tuple[str, str]]:
    rows = [
        ("Mode", _meta_value(metadata.get("trigger"))),
        ("Args(norm)", _meta_value(_normalized_args(metadata.get("requested_tokens_normalized")))),
        ("Resolved entries", _meta_value(_resolved_entries_count(metadata))),
    ]
    return [(name, value) for name, value in rows if value != "N/A"]


def _resolved_entries_count(metadata: Mapping[str, Any]) -> Any:
    direct = _as_int(metadata.get("resolved_entries_count"))
    if direct is not None:
        return direct
    resolved_entries = metadata.get("resolved_entries")
    if isinstance(resolved_entries, list):
        return len(resolved_entries)
    return None


def _resolved_images_count(value: Any) -> Any:
    if isinstance(value, list):
        return len(value)
    return None


def _normalized_args(value: Any) -> str | None:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return None


def _meta_value(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    return str(value)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return None


def _component_label(source: Mapping[str, Any], component_name: str) -> str:
    resolver = str(source.get("resolver", "")).strip()
    if resolver in {"github_sha", "github_tag"}:
        repo = _github_repo(source)
        if repo is not None:
            return repo
    return f"{_source_readable_name(source)} [{component_name}]"


def _source_readable_name(source: Mapping[str, Any]) -> str:
    resolver = str(source.get("resolver", "")).strip()
    names = {
        "github_tag": "GitHub tag",
        "github_sha": "GitHub commit",
        "alpine_pkg": "Alpine package",
        "docker_hub_tag": "Docker Hub tag",
        "regex_match": "Regex match",
        "literal": "Literal",
    }
    return names.get(resolver, "Source")


def _value_with_links(
    value: str | None,
    *,
    source: Mapping[str, Any],
    source_link: str | None,
    raw_value: str | None = None,
) -> SummaryValue:
    if value in (None, ""):
        return SummaryValue(text="N/A", link=source_link)

    text = _short_hex(value)
    value_link = _resolver_value_link(source, value, raw_value=raw_value)
    return SummaryValue(text=text, link=value_link or source_link)


def _resolver_value_link(
    source: Mapping[str, Any],
    value: str,
    *,
    raw_value: str | None = None,
) -> str | None:
    resolver = str(source.get("resolver", "")).strip()
    if resolver == "github_tag":
        repo = _github_repo(source)
        if repo is None:
            return None
        tag = _github_tag_value_for_link(source, value, raw_value)
        return _safe_https_url(f"https://github.com/{repo}/releases/tag/{tag}")
    if resolver == "github_sha":
        repo = _github_repo(source)
        if repo is None:
            return None
        return _safe_https_url(f"https://github.com/{repo}/commit/{value}")
    if resolver == "alpine_pkg":
        return _alpine_package_url(source)
    if resolver == "docker_hub_tag":
        return _docker_hub_repository_url(source)
    if resolver == "regex_match":
        return _safe_https_url(str(source.get("url", "")))
    if resolver == "literal":
        return _safe_https_url(str(source.get("url", "")))
    return None


_TAG_WRAPPER_PATTERN = re.compile(r"^[A-Za-z._-]*$")


def _github_tag_value_for_link(
    source: Mapping[str, Any],
    value: str,
    raw_value: str | None,
) -> str:
    raw_tag = source.get("raw_tag")
    if not isinstance(raw_tag, str) or not raw_tag:
        return value
    if not raw_value:
        return value
    if value == raw_value:
        return raw_tag
    if raw_tag.endswith(raw_value):
        prefix, suffix = raw_tag[: len(raw_tag) - len(raw_value)], ""
    elif raw_tag.startswith(raw_value):
        prefix, suffix = "", raw_tag[len(raw_value):]
    else:
        return value
    if not (_TAG_WRAPPER_PATTERN.match(prefix) and _TAG_WRAPPER_PATTERN.match(suffix)):
        return value
    return f"{prefix}{value}{suffix}"


def _source_link(source: Mapping[str, Any]) -> str | None:
    resolver = str(source.get("resolver", "")).strip()
    if resolver in {"github_tag", "github_sha"}:
        repo = _github_repo(source)
        if repo is None:
            return None
        return _safe_https_url(f"https://github.com/{repo}")
    if resolver == "alpine_pkg":
        return _alpine_package_url(source)
    if resolver == "docker_hub_tag":
        return _docker_hub_repository_url(source)
    if resolver == "regex_match":
        return _safe_https_url(str(source.get("url", "")))
    if resolver == "literal":
        return _safe_https_url(str(source.get("url", "")))
    return None


def _github_repo(source: Mapping[str, Any]) -> str | None:
    repo = source.get("repo")
    if isinstance(repo, str) and repo.strip():
        return repo.strip()
    repos = source.get("repos")
    if isinstance(repos, list) and repos:
        first = repos[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    return None


def _alpine_package_url(source: Mapping[str, Any]) -> str | None:
    branch = source.get("branch")
    repository = source.get("repository")
    package = source.get("package")
    if not all(isinstance(item, str) and item for item in (branch, repository, package)):
        return None
    return _safe_https_url(
        f"https://pkgs.alpinelinux.org/package/{branch}/{repository}/x86_64/{package}"
    )



def _docker_hub_repository_url(source: Mapping[str, Any]) -> str | None:
    namespace = source.get("namespace")
    repository = source.get("repository")
    if not all(isinstance(item, str) and item for item in (namespace, repository)):
        return None
    return _safe_https_url(f"https://hub.docker.com/r/{namespace}/{repository}/tags")


def _docker_tag_link(tag: str) -> str | None:
    if ":" not in tag:
        return None
    repo, version = tag.rsplit(":", 1)
    if "/" not in repo:
        return None
    namespace, image = repo.split("/", 1)
    if not namespace or not image or not version:
        return None
    return _safe_https_url(
        f"https://hub.docker.com/r/{namespace}/{image}/tags?name={version}"
    )


def _short_hex(value: str) -> str:
    compact = value.strip()
    if len(compact) >= 8 and all(char in "0123456789abcdefABCDEF" for char in compact):
        return compact[:7]
    return compact


def _markdown_value(value: SummaryValue) -> str:
    return _markdown_link_or_text(value.text, value.link)


def _html_value(value: SummaryValue) -> str:
    return _html_link_or_text(value.text, value.link)


def _markdown_link_or_text(text: str, link: str | None) -> str:
    if link:
        return f"[{_safe_markdown(text)}]({_safe_markdown_url(link)})"
    return _safe_markdown(text)


def _html_link_or_text(text: str, link: str | None) -> str:
    safe_text = _safe_html(text)
    if link:
        return f"<a href=\"{_safe_html(link)}\">{safe_text}</a>"
    return safe_text


def _safe_markdown_url(value: str) -> str:
    return value.replace(" ", "%20").replace(")", "%29")


def _safe_markdown(value: str) -> str:
    cleaned = value.replace("\0", "?").replace("\r", " ").replace("\n", " ")
    for char in "\\`*_[]()":
        cleaned = cleaned.replace(char, f"\\{char}")
    return cleaned


def _safe_html(value: str) -> str:
    return (
        value.replace("\0", "?")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _safe_https_url(url: str) -> str | None:
    value = url.strip()
    if not value:
        return None
    if not value.startswith("https://"):
        return None
    if any(
        char in value for char in ('"', "'", "<", ">")
    ):
        return None
    if any(char.isspace() or ord(char) < 0x20 for char in value):
        return None
    return value
