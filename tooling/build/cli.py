from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .change_detection import select_targets
from .config import load_all_configs
from .docker import BuildError, build_command as create_build_command
from .docker import image_tags
from .docker import run_build
from .dockerhub import DockerHubClient
from .errors import BuildUserError, ResolverUserError
from .models import ResolvedTargetState, ResolverSpec, TargetConfig, TargetState
from .reporting import (
    BuildReport,
    BuildReportEntry,
    BuildReportState,
    build_summary_model,
    render_failure_summary_markdown,
    render_failure_summary_telegram_html,
    render_summary_markdown,
    render_summary_telegram_html,
)
from .resolvers import ResolverService
from .selection import (
    CLI_MINUS_TOKEN_PREFIX,
    evaluate_manual_selector,
    looks_like_expression_token,
    normalize_expression_tokens,
    resolved_images,
)
from .state import BuildStateStore, resolve_state_file
from .telegram import TelegramClient
from .template import DEFAULT_TEMPLATE, render_template


@dataclass(slots=True)
class BuildPlan:
    image_dir: Path
    dockerfile: str
    target: ResolvedTargetState
    build_target: str | None = None
    directory_name: str | None = None
    version_source: dict[str, Any] = field(default_factory=dict)
    component_sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    template: str | None = None
    repos: list[str] = field(default_factory=list)


def _display_target_name(target_name: str | None) -> str:
    return target_name or "default"


def _wrap_resolver_error(
    error: ResolverUserError,
    *,
    image_name: str,
    target_name: str | None,
) -> BuildUserError:
    return BuildUserError(
        reason_code=error.reason_code,
        message=error.message,
        image_name=image_name,
        target_name=_display_target_name(target_name),
    )


def _ensure_known_targets(selected: list[str], configs_by_name: dict[str, object]) -> None:
    unknown_targets = [name for name in selected if name not in configs_by_name]
    if unknown_targets:
        raise ValueError(f"unknown target(s): {', '.join(unknown_targets)}")


def resolve_target_builds(
    *,
    repo_root: Path,
    requested_targets: list[str],
    force: bool,
    state_file: Path | None,
    selected_entries: set[tuple[str, str]] | None = None,
) -> list[BuildPlan]:
    configs = load_all_configs(repo_root)
    configs_by_name = {item.directory_name: item for item in configs}
    selected = requested_targets or sorted(configs_by_name)
    _ensure_known_targets(selected, configs_by_name)
    resolver = ResolverService(
        token=os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
    )
    store = BuildStateStore(state_file) if state_file is not None else None

    builds: list[BuildPlan] = []
    for name in selected:
        loaded = configs_by_name[name]
        image_raw: dict[str, str] = {}
        try:
            image_version = resolve_value(
                resolver,
                loaded.config.version,
                raw_out=image_raw,
            )
        except ResolverUserError as exc:
            raise _wrap_resolver_error(exc, image_name=name, target_name=None) from exc
        targets = loaded.config.targets or [TargetConfig()]
        for target in targets:
            entry_key = (name, target.name or "")
            if selected_entries is not None and entry_key not in selected_entries:
                continue
            version_spec = target.version if target.version is not None else loaded.config.version
            version_raw: dict[str, str] = {}
            components_raw: dict[str, str] = {}
            try:
                version = (
                    resolve_value(resolver, target.version, raw_out=version_raw)
                    or image_version
                )
                components = resolve_components(
                    resolver,
                    target.sha,
                    raw_out=components_raw,
                )
            except ResolverUserError as exc:
                raise _wrap_resolver_error(exc, image_name=name, target_name=target.name) from exc
            version_raw_source = version_raw if target.version is not None else image_raw
            resolved_target = ResolvedTargetState(
                image_name=loaded.repo_name,
                target_name=target.name,
                version=version,
                components=components,
            )
            if not force and store is not None and not store.should_build(resolved_target):
                continue
            builds.append(
                BuildPlan(
                    image_dir=loaded.image_dir,
                    dockerfile=target.dockerfile,
                    target=resolved_target,
                    build_target=target.target,
                    directory_name=name,
                    version_source=_source_metadata(version_spec, raw=version_raw_source),
                    component_sources=_component_sources_metadata(
                        target.sha,
                        components,
                        raw=components_raw,
                    ),
                    template=_template_for(loaded.image_dir, target),
                    repos=_target_repos(target.sha),
                )
            )
    return builds


def _template_for(image_dir: Path, target: TargetConfig) -> str | None:
    """The template to render for a target, or `None` to use the Dockerfile as is.

    `targets[].template` overrides; otherwise an image is templated as soon as it
    ships a `Dockerfile.j2` next to its `config.yml`, so the common case needs no
    config field at all.
    """
    if target.template is not None:
        return target.template
    if (image_dir / DEFAULT_TEMPLATE).exists():
        return DEFAULT_TEMPLATE
    return None


def _target_repos(sha: str | ResolverSpec | None) -> list[str]:
    """Repos tracked for a target, used as the template's `repos` context.

    This is the same list `sha` feeds to `github_sha`, so a Dockerfile template
    never has to repeat what `config.yml` already declares.
    """
    if sha is None:
        return []
    if isinstance(sha, str):
        return [sha]
    if sha.github_sha is not None:
        return list(sha.github_sha.repos)
    return []


def resolve_value(
    resolver: ResolverService,
    value: str | ResolverSpec | None,
    *,
    raw_out: dict[str, str] | None = None,
) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if value.github_tag is not None:
        return resolver.resolve_github_tag(
            value.github_tag.repo,
            value.github_tag.regex,
            raw_out=raw_out,
        )
    if value.github_sha is not None:
        return resolver.resolve_github_sha(value.github_sha.repos)
    if value.alpine_pkg is not None:
        return resolver.resolve_alpine_pkg(
            value.alpine_pkg.package,
            value.alpine_pkg.branch,
            value.alpine_pkg.repository,
        )
    if value.docker_hub_tag is not None:
        return resolver.resolve_docker_hub_tag(
            value.docker_hub_tag.namespace,
            value.docker_hub_tag.repository,
            value.docker_hub_tag.regex,
        )
    if value.regex_match is not None:
        return resolver.resolve_regex_match(
            value.regex_match.url,
            value.regex_match.pattern,
        )
    raise ValueError("unsupported resolver spec")


def resolve_components(
    resolver: ResolverService,
    value: str | ResolverSpec | None,
    *,
    raw_out: dict[str, str] | None = None,
) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, str):
        return {"sha": value}
    if value.github_sha is not None:
        return resolver.resolve_github_sha_details(value.github_sha.repos)

    resolved = resolve_value(resolver, value, raw_out=raw_out)
    if resolved is None:
        return {}
    return {_component_key(value): resolved}


def _component_key(value: ResolverSpec) -> str:
    if value.github_tag is not None:
        parts = [f"repo={value.github_tag.repo}"]
        if value.github_tag.regex is not None:
            parts.append(f"regex={value.github_tag.regex}")
        return f"github_tag:{'|'.join(parts)}"
    if value.alpine_pkg is not None:
        return (
            "alpine_pkg:"
            f"package={value.alpine_pkg.package}"
            f"|branch={value.alpine_pkg.branch}"
            f"|repository={value.alpine_pkg.repository}"
        )
    if value.docker_hub_tag is not None:
        parts = [
            f"namespace={value.docker_hub_tag.namespace}",
            f"repository={value.docker_hub_tag.repository}",
        ]
        if value.docker_hub_tag.regex is not None:
            parts.append(f"regex={value.docker_hub_tag.regex}")
        return f"docker_hub_tag:{'|'.join(parts)}"
    if value.regex_match is not None:
        return (
            "regex_match:"
            f"url={value.regex_match.url}"
            f"|pattern={value.regex_match.pattern}"
        )
    raise ValueError("unsupported resolver spec")


def _literal_source_metadata(value: str) -> dict[str, Any]:
    source: dict[str, Any] = {"resolver": "literal", "kind": "literal", "value": value}
    trimmed = value.strip()
    if trimmed.startswith("https://"):
        source["url"] = trimmed
    return source


def _source_metadata(
    value: str | ResolverSpec | None,
    *,
    raw: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return _literal_source_metadata(value)
    if value.github_tag is not None:
        source: dict[str, Any] = {
            "resolver": "github_tag",
            "kind": "resolver",
            "repo": value.github_tag.repo,
        }
        if value.github_tag.regex is not None:
            source["regex"] = value.github_tag.regex
        raw_tag = (raw or {}).get("github_tag")
        if isinstance(raw_tag, str) and raw_tag:
            source["raw_tag"] = raw_tag
        return source
    if value.github_sha is not None:
        return {
            "resolver": "github_sha",
            "kind": "resolver",
            "repos": list(value.github_sha.repos),
        }
    if value.alpine_pkg is not None:
        return {
            "resolver": "alpine_pkg",
            "kind": "resolver",
            "package": value.alpine_pkg.package,
            "branch": value.alpine_pkg.branch,
            "repository": value.alpine_pkg.repository,
        }
    if value.docker_hub_tag is not None:
        source: dict[str, Any] = {
            "resolver": "docker_hub_tag",
            "kind": "resolver",
            "namespace": value.docker_hub_tag.namespace,
            "repository": value.docker_hub_tag.repository,
        }
        if value.docker_hub_tag.regex is not None:
            source["regex"] = value.docker_hub_tag.regex
        return source
    if value.regex_match is not None:
        return {
            "resolver": "regex_match",
            "kind": "resolver",
            "url": value.regex_match.url,
            "pattern": value.regex_match.pattern,
        }
    raise ValueError("unsupported resolver spec")


def _component_sources_metadata(
    value: str | ResolverSpec | None,
    resolved_components: dict[str, str],
    *,
    raw: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if isinstance(value, str):
        return {
            name: {"resolver": "literal", "value": resolved_value}
            for name, resolved_value in resolved_components.items()
        }
    if value.github_sha is not None:
        source = _source_metadata(value)
        return {
            name: {**source, "repo": name}
            for name in resolved_components
        }

    source = _source_metadata(value, raw=raw)
    key = _component_key(value)
    if key in resolved_components:
        return {key: source}
    return {
        name: dict(source)
        for name in resolved_components
    }



def _report_state_from_target_state(state: TargetState | dict[str, object] | None) -> BuildReportState:
    if state is None:
        return BuildReportState()
    if isinstance(state, TargetState):
        return BuildReportState(version=state.version, components=dict(state.components))
    version = state.get("version")
    components = state.get("components", {})
    if version is not None and not isinstance(version, str):
        raise ValueError("report state version must be a string or null")
    if not isinstance(components, dict):
        raise ValueError("report state components must be a mapping")
    return BuildReportState(version=version, components=dict(components))


@dataclass(slots=True)
class SelectedTargets:
    requested_targets: list[str]
    selected_entries: set[tuple[str, str]]
    metadata: dict[str, object]


def _build_selection_universe(configs: list[object]) -> list[ResolvedTargetState]:
    universe: list[ResolvedTargetState] = []
    for loaded in configs:
        targets = loaded.config.targets or [TargetConfig()]
        for target in targets:
            universe.append(
                ResolvedTargetState(
                    image_name=loaded.directory_name,
                    target_name=target.name,
                )
            )
    return universe


def _select_targets_from_args(
    *,
    configs: list[object],
    selector_tokens: list[str],
    changed_files: list[str],
) -> SelectedTargets:
    universe = _build_selection_universe(configs)
    all_image_names = {loaded.directory_name for loaded in configs}

    if selector_tokens:
        resolved_entries = evaluate_manual_selector(
            ",".join(selector_tokens),
            universe,
        )
        selection_mode = "manual-selectors"
        requested_selectors_raw: str | None = ",".join(selector_tokens)
        requested_selectors_normalized = list(selector_tokens)
    elif changed_files:
        selected_images = set(
            select_targets(changed_files=changed_files, all_image_names=all_image_names)
        )
        resolved_entries = [
            entry for entry in universe if entry.image_name in selected_images
        ]
        selection_mode = "changed-files"
        requested_selectors_raw = None
        requested_selectors_normalized = []
    else:
        resolved_entries = list(universe)
        selection_mode = "all"
        requested_selectors_raw = None
        requested_selectors_normalized = []

    requested_targets = resolved_images(resolved_entries)
    selected_entries = {
        (entry.image_name, entry.target_name or "")
        for entry in resolved_entries
    }
    metadata: dict[str, object] = {
        "trigger": "cli",
        "selection_mode": selection_mode,
        "requested_tokens_raw": requested_selectors_raw,
        "requested_tokens_normalized": requested_selectors_normalized,
        "resolved_image_keys": requested_targets,
    }
    return SelectedTargets(
        requested_targets=requested_targets,
        selected_entries=selected_entries,
        metadata=metadata,
    )


def _argv_value_options(parser: argparse.ArgumentParser) -> set[str]:
    value_options: set[str] = set()
    for action in parser._actions:
        if not action.option_strings:
            continue
        if action.nargs == 0:
            continue
        value_options.update(
            option for option in action.option_strings if option.startswith("--")
        )
    return value_options


def _escape_expression_like_argv(
    argv: list[str],
    *,
    value_options: set[str],
) -> list[str]:
    if not argv or argv[0] not in {"build", "resolve"}:
        return argv

    escaped = [argv[0]]
    expecting_value = False
    for token in argv[1:]:
        if expecting_value:
            escaped.append(token)
            expecting_value = False
            continue
        if token in value_options:
            escaped.append(token)
            expecting_value = True
            continue
        if token.startswith("--"):
            escaped.append(token)
            continue
        if token.startswith("-") and looks_like_expression_token(token):
            escaped.append(f"{CLI_MINUS_TOKEN_PREFIX}{token[1:]}")
            continue
        escaped.append(token)
    return escaped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tooling.build")
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("targets", nargs="*")
    resolve_parser.add_argument("--repo-root", type=Path, default=Path("."))
    resolve_parser.add_argument("--changed-file", action="append", default=[])
    resolve_parser.add_argument("--json", action="store_true")

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("targets", nargs="*")
    build_parser.add_argument("--repo-root", type=Path, default=Path("."))
    build_parser.add_argument("--changed-file", action="append", default=[])
    build_parser.add_argument("--registry-user", required=True)
    build_parser.add_argument("--state-file", type=Path)
    build_parser.add_argument("--force", action="store_true")
    build_parser.add_argument("--push", action="store_true")
    build_parser.add_argument("--platform")
    build_parser.add_argument("--report-file", type=Path)
    build_parser.add_argument("--debug", action="store_true")

    sync_readmes_parser = subparsers.add_parser("sync-readmes")
    sync_readmes_parser.add_argument("targets", nargs="*")
    sync_readmes_parser.add_argument("--report-file", type=Path)
    sync_readmes_parser.add_argument("--repo-root", type=Path, default=Path("."))
    sync_readmes_parser.add_argument("--dockerhub-namespace", required=True)
    sync_readmes_parser.add_argument("--dockerhub-username", required=True)
    sync_readmes_parser.add_argument("--dockerhub-password", required=True)

    send_telegram_parser = subparsers.add_parser("send-telegram")
    send_telegram_parser.add_argument("--report-file", type=Path, required=True)
    send_telegram_parser.add_argument("--bot-token", required=True)
    send_telegram_parser.add_argument("--chat-id", required=True)
    send_telegram_parser.add_argument(
        "--template",
        choices=("success", "failure"),
        default="success",
    )

    write_summary_parser = subparsers.add_parser("write-summary")
    write_summary_parser.add_argument("--report-file", type=Path, required=True)
    write_summary_parser.add_argument("--github-step-summary", type=Path)
    write_summary_parser.add_argument(
        "--format",
        choices=("markdown", "telegram", "both"),
        default="markdown",
    )

    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    args = parser.parse_args(
        _escape_expression_like_argv(raw_argv, value_options=_argv_value_options(parser))
    )

    if args.command in {"build", "resolve"}:
        args.targets = normalize_expression_tokens(args.targets)

    if args.command == "resolve":
        configs = load_all_configs(args.repo_root)
        selection = _select_targets_from_args(
            configs=configs,
            selector_tokens=args.targets,
            changed_files=args.changed_file,
        )
        if args.changed_file and not selection.selected_entries:
            if args.json:
                print("[]")
            return 0

        builds = resolve_target_builds(
            repo_root=args.repo_root,
            requested_targets=selection.requested_targets,
            force=True,
            state_file=None,
            selected_entries=selection.selected_entries,
        )
        if args.json:
            payload = [
                {
                    "image": build.directory_name or build.target.image_name,
                    "repository": build.target.image_name,
                    "target_name": build.target.target_name,
                    "selector": (
                        build.directory_name or build.target.image_name
                    )
                    if build.target.target_name is None
                    else f"{build.directory_name or build.target.image_name}:{build.target.target_name}",
                    "version": build.target.version,
                    "components": dict(build.target.components),
                    "dockerfile": build.dockerfile,
                    "template": build.template,
                    "build_target": build.build_target,
                }
                for build in builds
            ]
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        for build in builds:
            selector = (
                build.directory_name or build.target.image_name
                if build.target.target_name is None
                else f"{build.directory_name or build.target.image_name}:{build.target.target_name}"
            )
            print(
                f"{selector} version={build.target.version} dockerfile={build.dockerfile} build_target={build.build_target}"
            )
        return 0

    if args.command == "sync-readmes":
        configs = load_all_configs(args.repo_root)
        configs_by_name = {item.directory_name: item for item in configs}

        if args.report_file is not None and args.targets:
            raise ValueError("sync-readmes does not accept positional targets with --report-file")

        selected: list[str]
        if args.report_file is not None:
            report = BuildReport.read_json(args.report_file)
            selected = []
            seen_report_targets: set[str] = set()
            for entry in report.entries:
                if entry.image_key not in seen_report_targets:
                    selected.append(entry.image_key)
                    seen_report_targets.add(entry.image_key)
        else:
            selected = list(dict.fromkeys(args.targets))

        if not selected:
            if args.report_file is not None:
                print("[readme] skipped because build report has no entries")
                return 0
            raise ValueError("sync-readmes requires at least one target or --report-file with entries")

        _ensure_known_targets(selected, configs_by_name)
        client = DockerHubClient(
            username=args.dockerhub_username,
            password=args.dockerhub_password,
        )
        for name in selected:
            loaded = configs_by_name[name]
            readme_path = loaded.image_dir / "README.md"
            if not readme_path.exists():
                raise FileNotFoundError(
                    f"README not found for image '{name}': {readme_path}"
                )
            client.update_repository_description(
                namespace=args.dockerhub_namespace,
                repository=loaded.repo_name,
                full_description=readme_path.read_text(encoding="utf-8"),
            )
            print(
                f"[readme] synced repository={args.dockerhub_namespace}/{loaded.repo_name} source={readme_path}"
            )
        return 0

    if args.command == "send-telegram":
        report = BuildReport.read_json(args.report_file)
        if args.template == "failure":
            if report.metadata.get("result") != "failure":
                raise ValueError("failure template requires a failure report")
            message = render_failure_summary_telegram_html(report)
        else:
            model = build_summary_model(report)
            message = render_summary_telegram_html(model)
        TelegramClient(bot_token=args.bot_token).send_message(
            chat_id=args.chat_id,
            text=message,
        )
        print(f"[telegram] sent chat_id={args.chat_id} entries={len(report.entries)}")
        return 0

    if args.command == "write-summary":
        report = BuildReport.read_json(args.report_file)
        model = build_summary_model(report)
        success_markdown = render_summary_markdown(model)
        success_telegram = render_summary_telegram_html(model)
        is_failure = report.metadata.get("result") == "failure"
        markdown = (
            render_failure_summary_markdown(report)
            if is_failure
            else success_markdown
        )

        if args.format == "markdown":
            print(markdown)
        elif args.format == "telegram":
            print(success_telegram)
        else:
            telegram = (
                render_failure_summary_telegram_html(report)
                if is_failure
                else success_telegram
            )
            print(f"{markdown}\n\n{telegram}")

        if args.github_step_summary is not None:
            args.github_step_summary.parent.mkdir(parents=True, exist_ok=True)
            args.github_step_summary.write_text(f"{markdown}\n", encoding="utf-8")
        return 0

    selection = _select_targets_from_args(
        configs=load_all_configs(args.repo_root),
        selector_tokens=args.targets,
        changed_files=args.changed_file,
    )
    selection_entries = selection.selected_entries
    selection_metadata = selection.metadata

    actual_state_file = resolve_state_file(args.repo_root, args.state_file)

    resolved_image_keys_meta = selection_metadata.get("resolved_image_keys")
    if not isinstance(resolved_image_keys_meta, list):
        resolved_image_keys_meta = list(
            dict.fromkeys(image_name for image_name, _target_name in selection_entries)
        )

    report_metadata: dict[str, object] = {
        "trigger": selection_metadata.get("trigger", "cli"),
        "selection_mode": selection_metadata.get("selection_mode", "targets"),
        "requested_tokens_raw": selection_metadata.get("requested_tokens_raw"),
        "requested_tokens_normalized": selection_metadata.get("requested_tokens_normalized", []),
        "resolved_image_keys": resolved_image_keys_meta,
        "resolved_entries_count": len(selection_entries),
        "built_entries_count": 0,
        "force": args.force,
        "result": "success",
    }
    report = BuildReport(metadata=report_metadata)

    if args.changed_file and not args.targets and not selection_entries:
        builds = []
    else:
        try:
            builds = resolve_target_builds(
                repo_root=args.repo_root,
                requested_targets=selection.requested_targets,
                force=args.force,
                state_file=actual_state_file,
                selected_entries=selection_entries,
            )
        except BuildUserError as exc:
            print(
                f"[build] resolve failed image={exc.image_name} "
                f"target={exc.target_name} reason={exc.message}",
                file=sys.stderr,
            )
            report.metadata["result"] = "failure"
            report.metadata["failure"] = {
                "stage": "resolve",
                "image_name": exc.image_name,
                "target_name": exc.target_name,
                "message": exc.message,
            }
            if args.report_file is not None:
                report.write_json(args.report_file)
            return 1
    store = BuildStateStore(actual_state_file) if actual_state_file is not None else None

    failure_exit_code = 0
    rendered_dir = tempfile.mkdtemp(prefix="containerization-dockerfile-")
    try:
        failure_exit_code = _run_builds(
            builds,
            args=args,
            store=store,
            report=report,
            rendered_dir=Path(rendered_dir),
        )
    finally:
        shutil.rmtree(rendered_dir, ignore_errors=True)
    report.metadata["built_entries_count"] = len(report.entries)
    if store is not None:
        store.save()
    if args.report_file is not None:
        report.write_json(args.report_file)
    return failure_exit_code


def _materialize_dockerfile(build: BuildPlan, rendered_dir: Path) -> str:
    """Return the `-f` argument for one build.

    Untemplated targets keep using their checked-in Dockerfile path relative to
    the build context. Templated targets are rendered per target into a
    temporary file outside the repository, so a rendered Dockerfile is never
    committed and build contexts stay clean.
    """
    if build.template is None:
        return build.dockerfile

    template_path = build.image_dir / build.template
    if not template_path.exists():
        raise ValueError(f"template not found: {template_path}")

    rendered = render_template(
        template_path,
        {"repos": list(build.repos), "version": build.target.version},
    )
    rendered_path = rendered_dir / (
        f"{build.directory_name or build.target.image_name}-"
        f"{build.target.target_name or 'default'}-Dockerfile"
    )
    rendered_path.write_text(rendered, encoding="utf-8")
    return str(rendered_path)


def _run_builds(
    builds: list[BuildPlan],
    *,
    args: argparse.Namespace,
    store: BuildStateStore | None,
    report: BuildReport,
    rendered_dir: Path,
) -> int:
    failure_exit_code = 0
    for build in builds:
        target_name = build.target.target_name or "default"
        raw_previous_state = None
        if store is not None:
            get_state = getattr(store, "get_state", None)
            if callable(get_state):
                raw_previous_state = get_state(build.target.image_name, build.target.target_name)
        previous_state = _report_state_from_target_state(raw_previous_state)
        start_parts = [
            f"[build] start image={build.target.image_name}",
            f"target={target_name}",
            f"version={build.target.version}",
        ]
        if args.push and args.platform:
            start_parts.append(f"platform={args.platform}")
        print(" ".join(start_parts))

        try:
            dockerfile = _materialize_dockerfile(build, rendered_dir)
        except ValueError as exc:
            print(
                f"[build] failed image={build.target.image_name} "
                f"target={target_name} reason={exc}"
            )
            report.metadata["result"] = "failure"
            report.metadata["failure"] = {
                "stage": "template",
                "image_name": build.target.image_name,
                "target_name": target_name,
                "message": str(exc),
            }
            return 1

        command = create_build_command(
            f"{args.registry_user}/{build.target.image_name}",
            name=build.target.target_name,
            version=build.target.version,
            build_target=build.build_target,
            dockerfile=dockerfile,
            local=not args.push,
            platform=args.platform,
        )
        try:
            run_build(command, build.image_dir, debug=args.debug)
        except BuildError as exc:
            print(
                f"[build] failed image={build.target.image_name} target={target_name} exit_code={exc.returncode}"
            )
            print(f"[build] command={' '.join(exc.command)}")
            if exc.output:
                print("[build] docker output:")
                print(exc.output, end="" if exc.output.endswith("\n") else "\n")
            report.metadata["result"] = "failure"
            report.metadata["failure"] = {
                "stage": "build",
                "image_name": build.target.image_name,
                "target_name": target_name,
                "message": "docker build failed",
                "exit_code": exc.returncode,
                "command": " ".join(exc.command),
            }
            failure_exit_code = exc.returncode or 1
            break

        latest_tag, version_tag = image_tags(build.target.target_name, build.target.version)
        full_tags = [f"{args.registry_user}/{build.target.image_name}:{latest_tag}"]
        if version_tag is not None and args.push:
            full_tags.append(f"{args.registry_user}/{build.target.image_name}:{version_tag}")
        print(
            f"[build] success image={build.target.image_name} target={target_name} tag={args.registry_user}/{build.target.image_name}:{latest_tag}"
        )
        report.entries.append(
            BuildReportEntry(
                image_key=build.directory_name or build.target.image_name,
                image_name=build.target.image_name,
                target_name=build.target.target_name,
                old_state=previous_state,
                new_state=BuildReportState(
                    version=build.target.version,
                    components=dict(build.target.components),
                ),
                docker_tags=full_tags,
                version_source=dict(build.version_source),
                component_sources={
                    name: dict(source)
                    for name, source in build.component_sources.items()
                },
            )
        )
        if store is not None:
            store.record_success(build.target)
    return failure_exit_code
