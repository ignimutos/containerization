import json
import subprocess
from pathlib import Path

import pytest
import yaml

from tooling.build.cli import main, resolve_target_builds
from tooling.build.models import ResolvedTargetState
from tooling.build.reporting import (
    BuildReport,
    build_summary_model,
    render_failure_summary_markdown,
    render_failure_summary_telegram_html,
    render_summary_markdown,
    render_summary_telegram_html,
)


def test_build_command_with_changed_file_selects_all_targets_in_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tooling.build import cli as cli_module

    alpha_dir = tmp_path / "images" / "alpha"
    alpha_dir.mkdir(parents=True)
    (alpha_dir / "config.yml").write_text("version: 1.0.0\n")

    beta_dir = tmp_path / "images" / "beta"
    beta_dir.mkdir(parents=True)
    (beta_dir / "config.yml").write_text(
        """
version: 2.0.0
targets:
  - {}
  - name: release
""".strip()
        + "\n"
    )

    run_calls: list[list[str]] = []

    def fake_run_build(command: list[str], image_dir: Path, debug: bool = False) -> None:
        run_calls.append(command)

    monkeypatch.setattr(cli_module, "run_build", fake_run_build)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "build",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
            "--changed-file",
            "images/beta/config.yml",
        ]
    )

    assert exit_code == 0
    assert len(run_calls) == 2
    assert any("ignimutos/beta:latest" in part for command in run_calls for part in command)
    assert any("ignimutos/beta:release-latest" in part for command in run_calls for part in command)
    assert all("ignimutos/alpha:latest" not in " ".join(command) for command in run_calls)


def test_build_command_with_non_matching_changed_file_is_noop_and_writes_empty_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tooling.build import cli as cli_module

    image_dir = tmp_path / "images" / "alpha"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("version: 1.0.0\n")

    report_file = tmp_path / "reports" / "build-report.json"

    def fail_resolve_target_builds(**_kwargs):
        pytest.fail("resolve_target_builds should not run for empty changed-file selection")

    monkeypatch.setattr(cli_module, "resolve_target_builds", fail_resolve_target_builds)
    monkeypatch.setattr(
        cli_module,
        "run_build",
        lambda *args, **kwargs: pytest.fail("run_build should not run for empty changed-file selection"),
    )
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "build",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
            "--changed-file",
            "docs/notes.txt",
            "--report-file",
            str(report_file),
        ]
    )

    assert exit_code == 0
    report_payload = json.loads(report_file.read_text(encoding="utf-8"))
    assert report_payload["entries"] == []
    assert report_payload["metadata"] == {
        "trigger": "cli",
        "selection_mode": "changed-files",
        "requested_tokens_raw": None,
        "requested_tokens_normalized": [],
        "resolved_image_keys": [],
        "resolved_entries_count": 0,
        "built_entries_count": 0,
        "force": False,
        "result": "success",
    }


def test_resolve_command_supports_json_output(tmp_path: Path, capsys) -> None:
    alpha_dir = tmp_path / "images" / "alpha"
    alpha_dir.mkdir(parents=True)
    (alpha_dir / "config.yml").write_text(
        """
name: alpha-repo
version: 1.2.3
targets:
  - dockerfile: Dockerfile.base
  - name: release
    target: runtime
    dockerfile: Dockerfile.release
    version: 2.0.0
""".strip()
        + "\n"
    )

    exit_code = main(["resolve", "alpha", "--repo-root", str(tmp_path), "--json"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == [
        {
            "image": "alpha",
            "repository": "alpha-repo",
            "target_name": None,
            "selector": "alpha",
            "version": "1.2.3",
            "components": {},
            "dockerfile": "Dockerfile.base",
            "template": None,
            "build_target": None,
        },
        {
            "image": "alpha",
            "repository": "alpha-repo",
            "target_name": "release",
            "selector": "alpha:release",
            "version": "2.0.0",
            "components": {},
            "dockerfile": "Dockerfile.release",
            "template": None,
            "build_target": "runtime",
        },
    ]


def test_resolve_command_with_non_matching_changed_file_outputs_empty_json(
    tmp_path: Path,
    capsys,
) -> None:
    alpha_dir = tmp_path / "images" / "alpha"
    alpha_dir.mkdir(parents=True)
    (alpha_dir / "config.yml").write_text("version: 1.0.0\n")

    exit_code = main(
        [
            "resolve",
            "--repo-root",
            str(tmp_path),
            "--changed-file",
            "docs/notes.txt",
            "--json",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.strip() == "[]"


def test_build_command_accepts_minus_prefixed_expression_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tooling.build import cli as cli_module

    image_dir = tmp_path / "images" / "alpha"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        "targets:\n  - {}\n  - name: release\n",
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def fake_resolve_target_builds(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(cli_module, "resolve_target_builds", fake_resolve_target_builds)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "build",
            "all",
            "-alpha:release",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
        ]
    )

    assert exit_code == 0
    assert captured["requested_targets"] == ["alpha"]
    assert captured["selected_entries"] == {("alpha", "")}


def test_build_command_keeps_long_option_value_that_starts_with_dash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tooling.build import cli as cli_module

    image_dir = tmp_path / "images" / "alpha"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("version: 1.0.0\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_resolve_target_builds(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(cli_module, "resolve_target_builds", fake_resolve_target_builds)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "build",
            "all",
            "--platform",
            "-linux/amd64",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
        ]
    )

    assert exit_code == 0
    assert captured["requested_targets"] == ["alpha"]


def test_build_plan_type_is_exposed() -> None:
    from tooling.build import cli as cli_module

    assert hasattr(cli_module, "BuildPlan")



def test_resolve_target_builds_prefers_personal_access_token_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_dir = tmp_path / "images" / "telegram"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("version: 1.0.0\n")

    captured_tokens: list[str | None] = []

    class FakeResolverService:
        def __init__(self, *, token: str | None = None, transport: object | None = None) -> None:
            captured_tokens.append(token)
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

    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "pat-token")
    monkeypatch.setattr("tooling.build.cli.ResolverService", FakeResolverService)

    resolve_target_builds(
        repo_root=tmp_path,
        requested_targets=["telegram"],
        force=True,
        state_file=None,
    )

    assert captured_tokens == ["pat-token"]


def test_resolve_target_builds_uses_github_token_when_pat_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_dir = tmp_path / "images" / "telegram"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("version: 1.0.0\n")

    captured_tokens: list[str | None] = []

    class FakeResolverService:
        def __init__(self, *, token: str | None = None, transport: object | None = None) -> None:
            captured_tokens.append(token)
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

    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setattr("tooling.build.cli.ResolverService", FakeResolverService)

    resolve_target_builds(
        repo_root=tmp_path,
        requested_targets=["telegram"],
        force=True,
        state_file=None,
    )

    assert captured_tokens == ["github-token"]


def test_resolve_target_builds_uses_full_resolver_identity_in_component_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_dir = tmp_path / "images" / "telegram"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        """
image_name: telegram
version:
  docker_hub_tag:
    namespace: library
    repository: caddy
    regex: ^(\\d+\\.\\d+\\.\\d+)-alpine$
targets:
  - name: release
    sha:
      github_tag:
        repo: owner/repo
        regex: ^v?(\\d+\\.\\d+\\.\\d+)$
  - name: worker
    sha:
      alpine_pkg:
        package: lyrebird
        branch: edge
        repository: community
  - name: mirror
    sha:
      regex_match:
        url: https://example.invalid/releases.txt
        pattern: release=(\\d+\\.\\d+\\.\\d+)
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
            assert repo == "owner/repo"
            assert regex == r"^v?(\d+\.\d+\.\d+)$"
            return "2.4.6"

        def resolve_docker_hub_tag(
            self,
            namespace: str,
            repository: str,
            regex: str | None = None,
        ) -> str:
            assert namespace == "library"
            assert repository == "caddy"
            assert regex == r"^(\d+\.\d+\.\d+)-alpine$"
            return "2.11.2"

        def resolve_alpine_pkg(
            self,
            target: str,
            branch: str = "v3.21",
            repository: str = "main",
        ) -> str:
            assert target == "lyrebird"
            assert branch == "edge"
            assert repository == "community"
            return "2.4.6-r0"

        def resolve_regex_match(self, url: str, pattern: str) -> str:
            assert url == "https://example.invalid/releases.txt"
            assert pattern == r"release=(\d+\.\d+\.\d+)"
            return "2.4.6"

    monkeypatch.setattr("tooling.build.cli.ResolverService", FakeResolverService)

    builds = resolve_target_builds(
        repo_root=tmp_path,
        requested_targets=["telegram"],
        force=True,
        state_file=None,
    )

    assert builds[0].version_source == {
        "resolver": "docker_hub_tag",
        "kind": "resolver",
        "namespace": "library",
        "repository": "caddy",
        "regex": r"^(\d+\.\d+\.\d+)-alpine$",
    }
    assert {build.target.target_name: build.target.components for build in builds} == {
        "release": {
            "github_tag:repo=owner/repo|regex=^v?(\\d+\\.\\d+\\.\\d+)$": "2.4.6"
        },
        "worker": {
            "alpine_pkg:package=lyrebird|branch=edge|repository=community": "2.4.6-r0"
        },
        "mirror": {
            "regex_match:url=https://example.invalid/releases.txt|pattern=release=(\\d+\\.\\d+\\.\\d+)": "2.4.6"
        },
    }



def test_resolve_target_builds_raises_readable_error_for_unknown_target(tmp_path: Path) -> None:
    image_dir = tmp_path / "images" / "telegram"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")

    with pytest.raises(ValueError, match=r"unknown target\(s\): missing"):
        resolve_target_builds(
            repo_root=tmp_path,
            requested_targets=["missing"],
            force=True,
            state_file=None,
        )


@pytest.mark.parametrize(
    "argv",
    [
        ["resolve", "missing"],
        ["build", "missing", "--registry-user", "ignimutos"],
    ],
)
def test_main_commands_raise_readable_error_for_unknown_target(
    tmp_path: Path,
    argv: list[str],
) -> None:
    image_dir = tmp_path / "images" / "telegram"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")

    with pytest.raises(ValueError, match=r"unknown image 'missing'"):
        main([*argv, "--repo-root", str(tmp_path)])


def test_resolve_target_builds_treats_regex_match_identity_change_as_state_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_dir = tmp_path / "images" / "telegram"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        """
image_name: telegram
version: 1.0.0
targets:
  - name: worker
    sha:
      regex_match:
        url: https://example.invalid/releases.txt
        pattern: release=(\\d+\\.\\d+\\.\\d+)
""".strip()
        + "\n"
    )

    state_file = tmp_path / "version" / "version.yml"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(
        yaml.safe_dump(
            {
                "telegram": {
                    "worker": {
                        "version": "1.0.0",
                        "components": {
                            "regex_match:url=https://example.invalid/releases.txt|pattern=version=(\\d+\\.\\d+\\.\\d+)": "2.4.6"
                        },
                    }
                }
            },
            sort_keys=False,
        )
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
            pytest.fail("unexpected github tag resolution")

        def resolve_alpine_pkg(
            self,
            target: str,
            branch: str = "v3.21",
            repository: str = "main",
        ) -> str:
            pytest.fail("unexpected alpine package resolution")

        def resolve_regex_match(self, url: str, pattern: str) -> str:
            assert url == "https://example.invalid/releases.txt"
            assert pattern == r"release=(\d+\.\d+\.\d+)"
            return "2.4.6"

    monkeypatch.setattr("tooling.build.cli.ResolverService", FakeResolverService)

    builds = resolve_target_builds(
        repo_root=tmp_path,
        requested_targets=["telegram"],
        force=False,
        state_file=state_file,
    )

    assert len(builds) == 1
    assert builds[0].target.components == {
        "regex_match:url=https://example.invalid/releases.txt|pattern=release=(\\d+\\.\\d+\\.\\d+)": "2.4.6"
    }


def test_resolve_target_builds_skips_unchanged_targets_and_includes_changed_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_dir = tmp_path / "images" / "telegram"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        """
image_name: telegram
version: 1.0.0
targets:
  - name: unchanged
    sha:
      alpine_pkg:
        package: lyrebird
  - name: changed
    sha:
      alpine_pkg:
        package: nightjar
""".strip()
        + "\n"
    )

    state_file = tmp_path / "version" / "version.yml"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(
        yaml.safe_dump(
            {
                "telegram": {
                    "unchanged": {
                        "version": "1.0.0",
                        "components": {
                            "alpine_pkg:package=lyrebird|branch=v3.21|repository=main": "2.4.6-r0"
                        },
                    },
                    "changed": {
                        "version": "1.0.0",
                        "components": {
                            "alpine_pkg:package=nightjar|branch=v3.21|repository=main": "0.9.0-r0"
                        },
                    },
                }
            },
            sort_keys=False,
        )
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
            pytest.fail("unexpected github tag resolution")

        def resolve_alpine_pkg(
            self,
            target: str,
            branch: str = "v3.21",
            repository: str = "main",
        ) -> str:
            versions = {
                "lyrebird": "2.4.6-r0",
                "nightjar": "1.0.0-r0",
            }
            return versions[target]

        def resolve_regex_match(self, url: str, pattern: str) -> str:
            pytest.fail("unexpected regex resolution")

    monkeypatch.setattr("tooling.build.cli.ResolverService", FakeResolverService)

    builds = resolve_target_builds(
        repo_root=tmp_path,
        requested_targets=["telegram"],
        force=False,
        state_file=state_file,
    )

    assert [build.target.target_name for build in builds] == ["changed"]
    assert builds[0].target.components == {
        "alpine_pkg:package=nightjar|branch=v3.21|repository=main": "1.0.0-r0"
    }



def test_build_command_runs_single_target_without_touching_real_docker(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from tooling.build import cli as cli_module
    BuildPlan = cli_module.BuildPlan

    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")

    monkeypatch.setattr(
        cli_module,
        "resolve_target_builds",
        lambda **_: [
            BuildPlan(
                image_dir=image_dir,
                dockerfile="Dockerfile",
                target=ResolvedTargetState(
                    image_name="tg-signer",
                    target_name=None,
                    version="0.8.5",
                ),
                build_target=None,
            )
        ],
    )

    run_calls: list[dict[str, object]] = []

    def fake_run_build(command: list[str], image_dir: Path, debug: bool = False) -> None:
        run_calls.append({"command": command, "image_dir": image_dir, "debug": debug})

    monkeypatch.setattr(cli_module, "run_build", fake_run_build)

    created_stores: list[object] = []

    class FakeStore:
        def __init__(self, state_file: Path | None) -> None:
            self.state_file = state_file
            self.records: list[ResolvedTargetState] = []
            self.saved = False
            created_stores.append(self)

        def record_success(self, state: ResolvedTargetState) -> None:
            self.records.append(state)

        def save(self) -> None:
            self.saved = True

    monkeypatch.setattr(cli_module, "BuildStateStore", FakeStore)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: tmp_path / "version" / "version.yml")

    exit_code = main(
        [
            "build",
            "tg-signer",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert run_calls == [
        {
            "command": [
                "docker",
                "build",
                "--load",
                "--build-arg",
                "VERSION=0.8.5",
                "-t",
                "ignimutos/tg-signer:latest",
                "-f",
                "Dockerfile",
                ".",
            ],
            "image_dir": image_dir,
            "debug": False,
        }
    ]
    assert "[build] start image=tg-signer target=default version=0.8.5" in captured.out
    assert "[build] success image=tg-signer target=default tag=ignimutos/tg-signer:latest" in captured.out
    assert len(created_stores) == 1
    assert created_stores[0].records == [
        ResolvedTargetState(
            image_name="tg-signer",
            target_name=None,
            version="0.8.5",
        )
    ]
    assert created_stores[0].saved is True


def test_build_command_prints_single_line_resolver_failure_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tooling.build import cli as cli_module
    from tooling.build.errors import BuildUserError

    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")

    def fail_resolve_target_builds(**_kwargs):
        raise BuildUserError(
            reason_code="github_tls_error",
            message=(
                "GitHub tag lookup failed for amchii/tg-signer: "
                "TLS connection failed (UNEXPECTED_EOF_WHILE_READING)"
            ),
            image_name="tg-signer",
            target_name="default",
        )

    monkeypatch.setattr(cli_module, "resolve_target_builds", fail_resolve_target_builds)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "build",
            "tg-signer",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == (
        "[build] resolve failed image=tg-signer target=default "
        "reason=GitHub tag lookup failed for amchii/tg-signer: "
        "TLS connection failed (UNEXPECTED_EOF_WHILE_READING)\n"
    )
    assert "Traceback" not in captured.err
    assert "httpx.ConnectError" not in captured.err
    assert "httpcore.ConnectError" not in captured.err
    assert "_ssl.c:" not in captured.err


def test_build_command_writes_failure_report_file_on_resolver_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tooling.build import cli as cli_module
    from tooling.build.errors import BuildUserError

    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")
    report_file = tmp_path / "reports" / "build-report.json"

    def fail_resolve_target_builds(**_kwargs):
        raise BuildUserError(
            reason_code="github_tls_error",
            message=(
                "GitHub tag lookup failed for amchii/tg-signer: "
                "TLS connection failed (UNEXPECTED_EOF_WHILE_READING)"
            ),
            image_name="tg-signer",
            target_name="default",
        )

    monkeypatch.setattr(cli_module, "resolve_target_builds", fail_resolve_target_builds)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: None)

    exit_code = main(
        [
            "build",
            "tg-signer",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
            "--report-file",
            str(report_file),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == (
        "[build] resolve failed image=tg-signer target=default "
        "reason=GitHub tag lookup failed for amchii/tg-signer: "
        "TLS connection failed (UNEXPECTED_EOF_WHILE_READING)\n"
    )
    report_payload = json.loads(report_file.read_text(encoding="utf-8"))
    assert report_payload["entries"] == []
    assert report_payload["metadata"] == {
        "trigger": "cli",
        "selection_mode": "manual-selectors",
        "requested_tokens_raw": "tg-signer",
        "requested_tokens_normalized": ["tg-signer"],
        "resolved_image_keys": ["tg-signer"],
        "resolved_entries_count": 1,
        "built_entries_count": 0,
        "force": False,
        "result": "failure",
        "failure": {
            "stage": "resolve",
            "image_name": "tg-signer",
            "target_name": "default",
            "message": (
                "GitHub tag lookup failed for amchii/tg-signer: "
                "TLS connection failed (UNEXPECTED_EOF_WHILE_READING)"
            ),
        },
    }


def test_build_command_returns_nonzero_and_reports_failure_output(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from tooling.build import cli as cli_module
    BuildPlan = cli_module.BuildPlan

    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")

    monkeypatch.setattr(
        cli_module,
        "resolve_target_builds",
        lambda **_: [
            BuildPlan(
                image_dir=image_dir,
                dockerfile="Dockerfile",
                target=ResolvedTargetState(
                    image_name="tg-signer",
                    target_name=None,
                    version="0.8.5",
                ),
                build_target=None,
            )
        ],
    )

    def fake_run_build(command: list[str], image_dir: Path, debug: bool = False) -> None:
        assert debug is False
        raise cli_module.BuildError(command=command, returncode=1, output="step 1\nboom\n")

    monkeypatch.setattr(cli_module, "run_build", fake_run_build)

    class FakeStore:
        def __init__(self, state_file: Path | None) -> None:
            self.state_file = state_file
            self.saved = False

        def record_success(self, *_args, **_kwargs) -> None:
            pytest.fail("record_success should not run on failure")

        def save(self) -> None:
            self.saved = True

    monkeypatch.setattr(cli_module, "BuildStateStore", FakeStore)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: tmp_path / "version" / "version.yml")

    exit_code = main(
        [
            "build",
            "tg-signer",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "[build] start image=tg-signer target=default version=0.8.5" in captured.out
    assert "[build] failed image=tg-signer target=default exit_code=1" in captured.out
    assert "[build] command=docker build --load --build-arg VERSION=0.8.5 -t ignimutos/tg-signer:latest -f Dockerfile ." in captured.out
    assert "[build] docker output:" in captured.out
    assert "step 1\nboom" in captured.out


def test_build_command_without_state_file_does_not_create_tmp_fallback_store(
    tmp_path: Path, monkeypatch
) -> None:
    from tooling.build import cli as cli_module

    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")

    monkeypatch.setattr(cli_module, "resolve_target_builds", lambda **_: [])
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: None)

    def fail_build_state_store(*_args, **_kwargs):
        pytest.fail("BuildStateStore should not be created when state_file is None")

    monkeypatch.setattr(cli_module, "BuildStateStore", fail_build_state_store)

    exit_code = main(
        [
            "build",
            "tg-signer",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
        ]
    )

    assert exit_code == 0


def test_build_command_persists_partial_state_and_report_before_nonzero_return(
    tmp_path: Path, monkeypatch
) -> None:
    from tooling.build import cli as cli_module
    BuildPlan = cli_module.BuildPlan

    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")
    report_file = tmp_path / "reports" / "build-report.json"

    plans = [
        BuildPlan(
            image_dir=image_dir,
            dockerfile="Dockerfile",
            target=ResolvedTargetState(
                image_name="tg-signer",
                target_name="release",
                version="0.8.5",
                components={"sha": "newsha1"},
            ),
            build_target=None,
        ),
        BuildPlan(
            image_dir=image_dir,
            dockerfile="Dockerfile",
            target=ResolvedTargetState(
                image_name="tg-signer",
                target_name="worker",
                version="0.8.6",
                components={"sha": "newsha2"},
            ),
            build_target=None,
        ),
    ]
    monkeypatch.setattr(cli_module, "resolve_target_builds", lambda **_: plans)

    run_count = {"value": 0}

    def fake_run_build(command: list[str], image_dir: Path, debug: bool = False) -> None:
        run_count["value"] += 1
        if run_count["value"] == 2:
            raise cli_module.BuildError(command=command, returncode=7, output="second failed\n")

    monkeypatch.setattr(cli_module, "run_build", fake_run_build)

    class FakeStore:
        def __init__(self, state_file: Path | None) -> None:
            self.state_file = state_file
            self.saved = False
            self.records: list[ResolvedTargetState] = []

        def get_state(self, image_name: str, target_name: str | None = None):
            return None

        def record_success(self, state: ResolvedTargetState) -> None:
            self.records.append(state)

        def save(self) -> None:
            self.saved = True

    created_store = FakeStore(tmp_path / "version" / "version.yml")
    monkeypatch.setattr(cli_module, "BuildStateStore", lambda *_args, **_kwargs: created_store)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: tmp_path / "version" / "version.yml")

    exit_code = main(
        [
            "build",
            "tg-signer",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
            "--report-file",
            str(report_file),
        ]
    )

    assert exit_code == 7
    assert created_store.saved is True
    assert created_store.records == [plans[0].target]
    report_payload = json.loads(report_file.read_text())
    assert report_payload["entries"] == [
        {
            "image_key": "tg-signer",
            "image_name": "tg-signer",
            "target_name": "release",
            "old_state": {
                "version": None,
                "components": {},
            },
            "new_state": {
                "version": "0.8.5",
                "components": {"sha": "newsha1"},
            },
            "docker_tags": [
                "ignimutos/tg-signer:release-latest",
            ],
            "version_source": {},
            "component_sources": {},
        }
    ]
    assert report_payload["metadata"] == {
        "trigger": "cli",
        "selection_mode": "manual-selectors",
        "requested_tokens_raw": "tg-signer",
        "requested_tokens_normalized": ["tg-signer"],
        "resolved_image_keys": ["tg-signer"],
        "resolved_entries_count": 1,
        "built_entries_count": 1,
        "force": False,
        "result": "failure",
        "failure": {
            "stage": "build",
            "image_name": "tg-signer",
            "target_name": "worker",
            "message": "docker build failed",
            "exit_code": 7,
            "command": "docker build --load --build-arg VERSION=0.8.6 -t ignimutos/tg-signer:worker-latest -f Dockerfile .",
        },
    }


def test_build_command_passes_debug_flag(tmp_path: Path, monkeypatch, capsys) -> None:
    from tooling.build import cli as cli_module
    BuildPlan = cli_module.BuildPlan

    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")

    monkeypatch.setattr(
        cli_module,
        "resolve_target_builds",
        lambda **_: [
            BuildPlan(
                image_dir=image_dir,
                dockerfile="Dockerfile",
                target=ResolvedTargetState(
                    image_name="tg-signer",
                    target_name=None,
                    version="0.8.5",
                ),
                build_target=None,
            )
        ],
    )

    def fake_run_build(command: list[str], image_dir: Path, debug: bool = False) -> None:
        assert debug is True

    monkeypatch.setattr(cli_module, "run_build", fake_run_build)

    class FakeStore:
        def __init__(self, state_file: Path | None) -> None:
            self.state_file = state_file
            self.records: list[ResolvedTargetState] = []
            self.saved = False

        def record_success(self, state: ResolvedTargetState) -> None:
            self.records.append(state)

        def save(self) -> None:
            self.saved = True

    created_store = FakeStore(None)
    monkeypatch.setattr(cli_module, "BuildStateStore", lambda *_args, **_kwargs: created_store)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: tmp_path / "version" / "version.yml")

    exit_code = main(
        [
            "build",
            "tg-signer",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
            "--debug",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "[build] start image=tg-signer target=default version=0.8.5" in captured.out
    assert "platform=" not in captured.out
    assert "[build] success image=tg-signer target=default tag=ignimutos/tg-signer:latest" in captured.out
    assert created_store.records == [
        ResolvedTargetState(
            image_name="tg-signer",
            target_name=None,
            version="0.8.5",
        )
    ]
    assert created_store.saved is True


def test_build_command_omits_platform_in_logs_for_local_builds(tmp_path: Path, monkeypatch, capsys) -> None:
    from tooling.build import cli as cli_module
    BuildPlan = cli_module.BuildPlan

    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")

    monkeypatch.setattr(
        cli_module,
        "resolve_target_builds",
        lambda **_: [
            BuildPlan(
                image_dir=image_dir,
                dockerfile="Dockerfile",
                target=ResolvedTargetState(
                    image_name="tg-signer",
                    target_name=None,
                    version="0.8.5",
                ),
                build_target=None,
            )
        ],
    )

    def fake_run_build(command: list[str], image_dir: Path, debug: bool = False) -> None:
        assert command[0:3] == ["docker", "build", "--load"]
        assert "--platform" not in command

    monkeypatch.setattr(cli_module, "run_build", fake_run_build)

    class FakeStore:
        def __init__(self, state_file: Path | None) -> None:
            self.state_file = state_file
            self.records: list[ResolvedTargetState] = []
            self.saved = False

        def record_success(self, state: ResolvedTargetState) -> None:
            self.records.append(state)

        def save(self) -> None:
            self.saved = True

    created_store = FakeStore(None)
    monkeypatch.setattr(cli_module, "BuildStateStore", lambda *_args, **_kwargs: created_store)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: tmp_path / "version" / "version.yml")

    exit_code = main(
        [
            "build",
            "tg-signer",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
            "--platform",
            "linux/arm64",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "[build] start image=tg-signer target=default version=0.8.5" in captured.out
    assert "platform=linux/arm64" not in captured.out
    assert created_store.records == [
        ResolvedTargetState(
            image_name="tg-signer",
            target_name=None,
            version="0.8.5",
        )
    ]
    assert created_store.saved is True


def test_build_command_reports_platform_for_push_builds(tmp_path: Path, monkeypatch, capsys) -> None:
    from tooling.build import cli as cli_module
    BuildPlan = cli_module.BuildPlan

    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")

    monkeypatch.setattr(
        cli_module,
        "resolve_target_builds",
        lambda **_: [
            BuildPlan(
                image_dir=image_dir,
                dockerfile="Dockerfile",
                target=ResolvedTargetState(
                    image_name="tg-signer",
                    target_name=None,
                    version="0.8.5",
                ),
                build_target=None,
            )
        ],
    )

    def fake_run_build(command: list[str], image_dir: Path, debug: bool = False) -> None:
        assert command[0:4] == ["docker", "buildx", "build", "--push"]
        assert "--platform" in command

    monkeypatch.setattr(cli_module, "run_build", fake_run_build)

    class FakeStore:
        def __init__(self, state_file: Path | None) -> None:
            self.state_file = state_file
            self.records: list[ResolvedTargetState] = []
            self.saved = False

        def record_success(self, state: ResolvedTargetState) -> None:
            self.records.append(state)

        def save(self) -> None:
            self.saved = True

    created_store = FakeStore(None)
    monkeypatch.setattr(cli_module, "BuildStateStore", lambda *_args, **_kwargs: created_store)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: tmp_path / "version" / "version.yml")

    exit_code = main(
        [
            "build",
            "tg-signer",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
            "--push",
            "--platform",
            "linux/arm64",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "[build] start image=tg-signer target=default version=0.8.5 platform=linux/arm64" in captured.out
    assert created_store.records == [
        ResolvedTargetState(
            image_name="tg-signer",
            target_name=None,
            version="0.8.5",
        )
    ]
    assert created_store.saved is True



def test_build_command_writes_report_file_for_successful_builds(
    tmp_path: Path, monkeypatch
) -> None:
    from tooling.build import cli as cli_module
    BuildPlan = cli_module.BuildPlan

    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")
    report_file = tmp_path / "reports" / "build-report.json"

    target_state = ResolvedTargetState(
        image_name="tg-signer",
        target_name="release",
        version="0.8.5",
        components={"sha": "newsha"},
    )

    monkeypatch.setattr(
        cli_module,
        "resolve_target_builds",
        lambda **_: [
            BuildPlan(
                image_dir=image_dir,
                dockerfile="Dockerfile",
                target=target_state,
                build_target=None,
            )
        ],
    )

    monkeypatch.setattr(cli_module, "run_build", lambda *args, **kwargs: None)

    class FakeStore:
        def __init__(self, state_file: Path | None) -> None:
            self.state_file = state_file
            self.saved = False

        def record_success(self, *_args, **_kwargs) -> None:
            pass

        def save(self) -> None:
            self.saved = True

        def get_state(self, image_name: str, target_name: str | None = None):
            assert image_name == "tg-signer"
            assert target_name == "release"
            return {
                "version": "0.8.4",
                "components": {"sha": "oldsha"},
            }

    created_store = FakeStore(None)
    monkeypatch.setattr(cli_module, "BuildStateStore", lambda *_args, **_kwargs: created_store)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: tmp_path / "version" / "version.yml")

    exit_code = main(
        [
            "build",
            "tg-signer",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
            "--report-file",
            str(report_file),
        ]
    )

    assert exit_code == 0
    assert created_store.saved is True
    report_payload = json.loads(report_file.read_text())
    assert report_payload["entries"] == [
        {
            "image_key": "tg-signer",
            "image_name": "tg-signer",
            "target_name": "release",
            "old_state": {
                "version": "0.8.4",
                "components": {"sha": "oldsha"},
            },
            "new_state": {
                "version": "0.8.5",
                "components": {"sha": "newsha"},
            },
            "docker_tags": [
                "ignimutos/tg-signer:release-latest",
            ],
            "version_source": {},
            "component_sources": {},
        }
    ]
    assert report_payload["metadata"] == {
        "trigger": "cli",
        "selection_mode": "manual-selectors",
        "requested_tokens_raw": "tg-signer",
        "requested_tokens_normalized": ["tg-signer"],
        "resolved_image_keys": ["tg-signer"],
        "resolved_entries_count": 1,
        "built_entries_count": 1,
        "force": False,
        "result": "success",
    }



def test_build_command_populates_source_metadata_from_resolvers_and_enables_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tooling.build import cli as cli_module

    image_dir = tmp_path / "images" / "telegram"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        """
name: telegram
version:
  github_tag:
    repo: upstream/telegram
targets:
  - name: release
    sha:
      github_sha:
        repos:
          - upstream/telegram
""".strip()
        + "\n"
    )

    report_file = tmp_path / "reports" / "build-report.json"

    class FakeResolverService:
        def __init__(self, *, token: str | None = None, transport: object | None = None) -> None:
            self.token = token
            self.transport = transport

        def resolve_github_tag(
            self,
            repo: str,
            regex: str | None = None,
            *,
            raw_out: dict[str, str] | None = None,
        ) -> str:
            assert repo == "upstream/telegram"
            assert regex is None
            if raw_out is not None:
                raw_out["github_tag"] = "v1.2.3"
            return "1.2.3"

        def resolve_github_sha_details(self, repos: list[str]) -> dict[str, str]:
            assert repos == ["upstream/telegram"]
            return {"upstream/telegram": "f88ac37b64e9f26698f6eb6324d9f4f8264f5a70"}

        def resolve_github_sha(self, repos: list[str]) -> str:
            pytest.fail("unexpected github sha digest resolution")

        def resolve_alpine_pkg(
            self,
            target: str,
            branch: str = "v3.21",
            repository: str = "main",
        ) -> str:
            pytest.fail("unexpected alpine package resolution")

        def resolve_regex_match(self, url: str, pattern: str) -> str:
            pytest.fail("unexpected regex resolution")

    monkeypatch.setattr(cli_module, "ResolverService", FakeResolverService)
    monkeypatch.setattr(cli_module, "run_build", lambda *args, **kwargs: None)

    class FakeStore:
        def __init__(self, state_file: Path | None) -> None:
            self.state_file = state_file
            self.saved = False

        def record_success(self, *_args, **_kwargs) -> None:
            pass

        def save(self) -> None:
            self.saved = True

        def get_state(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(cli_module, "BuildStateStore", FakeStore)
    monkeypatch.setattr(
        cli_module,
        "resolve_state_file",
        lambda *args, **kwargs: tmp_path / "version" / "version.yml",
    )

    exit_code = main(
        [
            "build",
            "telegram",
            "--force",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
            "--report-file",
            str(report_file),
        ]
    )

    assert exit_code == 0

    report = BuildReport.read_json(report_file)
    assert len(report.entries) == 1

    entry = report.entries[0]
    assert entry.version_source == {
        "resolver": "github_tag",
        "kind": "resolver",
        "repo": "upstream/telegram",
        "raw_tag": "v1.2.3",
    }
    assert entry.component_sources == {
        "upstream/telegram": {
            "resolver": "github_sha",
            "kind": "resolver",
            "repos": ["upstream/telegram"],
            "repo": "upstream/telegram",
        }
    }

    summary = render_summary_markdown(build_summary_model(report))
    assert "https://github.com/upstream/telegram/releases/tag/v1.2.3" in summary
    assert "https://github.com/upstream/telegram/commit/f88ac37b64e9f26698f6eb6324d9f4f8264f5a70" in summary



def test_build_command_writes_empty_report_file_for_noop_builds(
    tmp_path: Path, monkeypatch
) -> None:
    from tooling.build import cli as cli_module

    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: []\n")

    report_file = tmp_path / "reports" / "build-report.json"

    monkeypatch.setattr(cli_module, "resolve_target_builds", lambda **_: [])
    monkeypatch.setattr(cli_module, "run_build", lambda *args, **kwargs: pytest.fail("run_build should not be called"))

    class FakeStore:
        def __init__(self, state_file: Path | None) -> None:
            self.state_file = state_file
            self.saved = False

        def record_success(self, *_args, **_kwargs) -> None:
            pytest.fail("record_success should not be called")

        def save(self) -> None:
            self.saved = True

        def get_state(self, *_args, **_kwargs):
            return None

    created_store = FakeStore(None)
    monkeypatch.setattr(cli_module, "BuildStateStore", lambda *_args, **_kwargs: created_store)
    monkeypatch.setattr(cli_module, "resolve_state_file", lambda *args, **kwargs: tmp_path / "version" / "version.yml")

    exit_code = main(
        [
            "build",
            "tg-signer",
            "--repo-root",
            str(tmp_path),
            "--registry-user",
            "ignimutos",
            "--report-file",
            str(report_file),
        ]
    )

    assert exit_code == 0
    assert created_store.saved is True
    report_payload = json.loads(report_file.read_text())
    assert report_payload["entries"] == []
    assert report_payload["metadata"] == {
        "trigger": "cli",
        "selection_mode": "manual-selectors",
        "requested_tokens_raw": "tg-signer",
        "requested_tokens_normalized": ["tg-signer"],
        "resolved_image_keys": ["tg-signer"],
        "resolved_entries_count": 1,
        "built_entries_count": 0,
        "force": False,
        "result": "success",
    }


def test_sync_readmes_command_uses_configured_repo_name_and_readme_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from tooling.build import cli as cli_module

    image_dir = tmp_path / "images" / "telegram"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("name: telegram-api\n")
    (image_dir / "README.md").write_text("# Telegram API\n\nSynced README.\n")

    init_args: list[tuple[str, str]] = []
    sync_calls: list[dict[str, str]] = []

    class FakeDockerHubClient:
        def __init__(self, *, username: str, password: str, transport=None) -> None:
            assert transport is None
            init_args.append((username, password))

        def update_repository_description(
            self,
            *,
            namespace: str,
            repository: str,
            full_description: str,
        ) -> None:
            sync_calls.append(
                {
                    "namespace": namespace,
                    "repository": repository,
                    "full_description": full_description,
                }
            )

    monkeypatch.setattr(cli_module, "DockerHubClient", FakeDockerHubClient)

    exit_code = main(
        [
            "sync-readmes",
            "telegram",
            "--repo-root",
            str(tmp_path),
            "--dockerhub-namespace",
            "ignimutos",
            "--dockerhub-username",
            "docker-user",
            "--dockerhub-password",
            "docker-pass",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert init_args == [("docker-user", "docker-pass")]
    assert sync_calls == [
        {
            "namespace": "ignimutos",
            "repository": "telegram-api",
            "full_description": "# Telegram API\n\nSynced README.\n",
        }
    ]
    assert (
        f"[readme] synced repository=ignimutos/telegram-api source={image_dir / 'README.md'}"
        in captured.out
    )


def test_sync_readmes_command_requires_targets_or_report_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one target or --report-file"):
        main(
            [
                "sync-readmes",
                "--repo-root",
                str(tmp_path),
                "--dockerhub-namespace",
                "ignimutos",
                "--dockerhub-username",
                "user",
                "--dockerhub-password",
                "pass",
            ]
        )


def test_sync_readmes_command_supports_report_file_and_deduplicates_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from tooling.build import cli as cli_module

    alpha_dir = tmp_path / "images" / "alpha"
    alpha_dir.mkdir(parents=True)
    (alpha_dir / "config.yml").write_text("name: alpha-repo\n")
    (alpha_dir / "README.md").write_text("# Alpha\n")

    beta_dir = tmp_path / "images" / "beta"
    beta_dir.mkdir(parents=True)
    (beta_dir / "config.yml").write_text("name: beta-repo\n")
    (beta_dir / "README.md").write_text("# Beta\n")

    report_file = tmp_path / ".tmp" / "build-report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "image_key": "alpha",
                        "image_name": "alpha",
                        "target_name": None,
                        "version_source": {},
                        "component_sources": {},
                    },
                    {
                        "image_key": "alpha",
                        "image_name": "alpha",
                        "target_name": "release",
                        "version_source": {},
                        "component_sources": {},
                    },
                    {
                        "image_key": "beta",
                        "image_name": "beta",
                        "target_name": "worker",
                        "version_source": {},
                        "component_sources": {},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    synced_repositories: list[str] = []

    class FakeDockerHubClient:
        def __init__(self, *, username: str, password: str, transport=None) -> None:
            assert transport is None
            assert username == "docker-user"
            assert password == "docker-pass"

        def update_repository_description(
            self,
            *,
            namespace: str,
            repository: str,
            full_description: str,
        ) -> None:
            assert namespace == "ignimutos"
            assert full_description in {"# Alpha\n", "# Beta\n"}
            synced_repositories.append(repository)

    monkeypatch.setattr(cli_module, "DockerHubClient", FakeDockerHubClient)

    exit_code = main(
        [
            "sync-readmes",
            "--report-file",
            str(report_file),
            "--repo-root",
            str(tmp_path),
            "--dockerhub-namespace",
            "ignimutos",
            "--dockerhub-username",
            "docker-user",
            "--dockerhub-password",
            "docker-pass",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert synced_repositories == ["alpha-repo", "beta-repo"]
    assert "[readme] synced repository=ignimutos/alpha-repo" in captured.out
    assert "[readme] synced repository=ignimutos/beta-repo" in captured.out



def test_sync_readmes_command_rejects_targets_with_report_file(
    tmp_path: Path,
) -> None:
    image_dir = tmp_path / "images" / "alpha"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("name: alpha-repo\n")
    (image_dir / "README.md").write_text("# Alpha\n")

    report_file = tmp_path / ".tmp" / "build-report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(
        json.dumps(
            {
                "entries": [
                    {"image_name": "alpha", "target_name": None},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="sync-readmes does not accept positional targets with --report-file",
    ):
        main(
            [
                "sync-readmes",
                "alpha",
                "--report-file",
                str(report_file),
                "--repo-root",
                str(tmp_path),
                "--dockerhub-namespace",
                "ignimutos",
                "--dockerhub-username",
                "user",
                "--dockerhub-password",
                "pass",
            ]
        )


def test_sync_readmes_command_raises_readable_error_for_unknown_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tooling.build import cli as cli_module

    image_dir = tmp_path / "images" / "telegram"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("name: telegram-api\n")

    class FakeDockerHubClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def update_repository_description(self, **_kwargs) -> None:
            pytest.fail("update_repository_description should not run for unknown targets")

    monkeypatch.setattr(cli_module, "DockerHubClient", FakeDockerHubClient)

    with pytest.raises(ValueError, match=r"unknown target\(s\): missing"):
        main(
            [
                "sync-readmes",
                "missing",
                "--repo-root",
                str(tmp_path),
                "--dockerhub-namespace",
                "ignimutos",
                "--dockerhub-username",
                "user",
                "--dockerhub-password",
                "pass",
            ]
        )


def test_sync_readmes_command_reports_missing_readme(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tooling.build import cli as cli_module
    from tooling.build.config import LoadedImageConfig
    from tooling.build.models import BuildConfig

    image_dir = tmp_path / "images" / "tg-signer"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("name: telegram-signer\n")

    monkeypatch.setattr(
        cli_module,
        "load_all_configs",
        lambda _repo_root: [
            LoadedImageConfig(
                image_dir=image_dir,
                config_path=image_dir / "config.yml",
                config=BuildConfig(image_name="telegram-signer"),
            )
        ],
    )

    class FakeDockerHubClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def update_repository_description(self, **_kwargs) -> None:
            pytest.fail("update_repository_description should not run when README is missing")

    monkeypatch.setattr(cli_module, "DockerHubClient", FakeDockerHubClient)

    with pytest.raises(FileNotFoundError, match="README not found for image 'tg-signer'"):
        main(
            [
                "sync-readmes",
                "tg-signer",
                "--repo-root",
                str(tmp_path),
                "--dockerhub-namespace",
                "ignimutos",
                "--dockerhub-username",
                "user",
                "--dockerhub-password",
                "pass",
            ]
        )



def test_send_telegram_command_supports_success_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from tooling.build import cli as cli_module

    report = BuildReport.from_dict(
        {
            "entries": [
                {
                    "image_key": "telegram-api",
                    "image_name": "telegram-api",
                    "target_name": "release",
                    "old_state": {
                        "version": "1.0.0",
                        "components": {"sha": "oldsha"},
                    },
                    "new_state": {
                        "version": "1.1.0",
                        "components": {"sha": "newsha"},
                    },
                    "docker_tags": ["ignimutos/telegram-api:release-latest"],
                    "version_source": {},
                    "component_sources": {},
                }
            ],
            "metadata": {
                "result": "success",
            },
        }
    )
    report_file = tmp_path / "reports" / "build-report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(json.dumps(report.to_dict()), encoding="utf-8")

    sent_messages: list[dict[str, str]] = []

    class FakeTelegramClient:
        def __init__(self, *, bot_token: str, transport=None) -> None:
            assert transport is None
            sent_messages.append({"bot_token": bot_token})

        def send_message(self, *, chat_id: str, text: str) -> None:
            sent_messages.append({"chat_id": chat_id, "text": text})

    monkeypatch.setattr(cli_module, "TelegramClient", FakeTelegramClient)

    exit_code = main(
        [
            "send-telegram",
            "--report-file",
            str(report_file),
            "--bot-token",
            "123:abc",
            "--chat-id",
            "-1001234567890",
            "--template",
            "success",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert sent_messages == [
        {"bot_token": "123:abc"},
        {
            "chat_id": "-1001234567890",
            "text": render_summary_telegram_html(build_summary_model(report)),
        },
    ]
    assert "[telegram] sent chat_id=-1001234567890 entries=1" in captured.out


def test_send_telegram_command_supports_failure_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from tooling.build import cli as cli_module

    report = BuildReport.from_dict(
        {
            "entries": [],
            "metadata": {
                "result": "failure",
                "failure": {
                    "stage": "build",
                    "image_name": "tg-signer",
                    "target_name": "worker",
                    "message": "docker build failed",
                    "exit_code": 7,
                    "command": "docker build ...",
                },
            },
        }
    )
    report_file = tmp_path / "reports" / "build-report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(json.dumps(report.to_dict()), encoding="utf-8")

    sent_messages: list[dict[str, str]] = []

    class FakeTelegramClient:
        def __init__(self, *, bot_token: str, transport=None) -> None:
            assert transport is None
            sent_messages.append({"bot_token": bot_token})

        def send_message(self, *, chat_id: str, text: str) -> None:
            sent_messages.append({"chat_id": chat_id, "text": text})

    monkeypatch.setattr(cli_module, "TelegramClient", FakeTelegramClient)

    exit_code = main(
        [
            "send-telegram",
            "--report-file",
            str(report_file),
            "--bot-token",
            "123:abc",
            "--chat-id",
            "-1001234567890",
            "--template",
            "failure",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert sent_messages == [
        {"bot_token": "123:abc"},
        {
            "chat_id": "-1001234567890",
            "text": render_failure_summary_telegram_html(report),
        },
    ]
    assert "[telegram] sent chat_id=-1001234567890 entries=0" in captured.out



def test_send_telegram_command_rejects_failure_template_for_success_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tooling.build import cli as cli_module

    report = BuildReport.from_dict(
        {
            "entries": [],
            "metadata": {
                "result": "success",
            },
        }
    )
    report_file = tmp_path / "reports" / "build-report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(json.dumps(report.to_dict()), encoding="utf-8")

    sent_messages: list[dict[str, str]] = []

    class FakeTelegramClient:
        def __init__(self, *, bot_token: str, transport=None) -> None:
            pytest.fail("TelegramClient should not be instantiated for invalid template/report combination")

        def send_message(self, *, chat_id: str, text: str) -> None:
            sent_messages.append({"chat_id": chat_id, "text": text})

    monkeypatch.setattr(cli_module, "TelegramClient", FakeTelegramClient)

    with pytest.raises(ValueError, match="failure template requires a failure report"):
        main(
            [
                "send-telegram",
                "--report-file",
                str(report_file),
                "--bot-token",
                "123:abc",
                "--chat-id",
                "-1001234567890",
                "--template",
                "failure",
            ]
        )

    assert sent_messages == []



def test_write_summary_command_prints_markdown_by_default(tmp_path: Path, capsys) -> None:
    report = BuildReport.from_dict({"entries": []})
    report_file = tmp_path / ".tmp" / "build-report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(json.dumps(report.to_dict()), encoding="utf-8")

    exit_code = main(
        [
            "write-summary",
            "--report-file",
            str(report_file),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    expected = render_summary_markdown(build_summary_model(report))
    assert captured.out == expected + "\n"




def test_write_summary_command_prints_telegram_with_explicit_format(tmp_path: Path, capsys) -> None:
    report = BuildReport.from_dict({"entries": []})
    report_file = tmp_path / ".tmp" / "build-report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(json.dumps(report.to_dict()), encoding="utf-8")

    exit_code = main(
        [
            "write-summary",
            "--report-file",
            str(report_file),
            "--format",
            "telegram",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    expected = render_summary_telegram_html(build_summary_model(report))
    assert captured.out == expected + "\n"



def test_write_summary_command_keeps_success_telegram_for_failure_report(
    tmp_path: Path,
    capsys,
) -> None:
    report = BuildReport.from_dict(
        {
            "entries": [],
            "metadata": {
                "result": "failure",
                "failure": {
                    "stage": "resolve",
                    "image_name": "tg-signer",
                    "target_name": "default",
                    "message": "resolver exploded",
                },
            },
        }
    )
    report_file = tmp_path / ".tmp" / "build-report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(json.dumps(report.to_dict()), encoding="utf-8")

    exit_code = main(
        [
            "write-summary",
            "--report-file",
            str(report_file),
            "--format",
            "telegram",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    expected = render_summary_telegram_html(build_summary_model(report))
    assert captured.out == expected + "\n"



def test_write_summary_command_prints_both_markdown_and_telegram_in_order(
    tmp_path: Path,
    capsys,
) -> None:
    report = BuildReport.from_dict({"entries": []})
    report_file = tmp_path / ".tmp" / "build-report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(json.dumps(report.to_dict()), encoding="utf-8")

    exit_code = main(
        [
            "write-summary",
            "--report-file",
            str(report_file),
            "--format",
            "both",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    expected_markdown = render_summary_markdown(build_summary_model(report))
    expected_telegram = render_summary_telegram_html(build_summary_model(report))
    assert captured.out == f"{expected_markdown}\n\n{expected_telegram}\n"



def test_write_summary_command_uses_failure_markdown_when_report_failed(
    tmp_path: Path,
    capsys,
) -> None:
    report = BuildReport.from_dict(
        {
            "entries": [],
            "metadata": {
                "result": "failure",
                "failure": {
                    "stage": "resolve",
                    "image_name": "tg-signer",
                    "target_name": "default",
                    "message": "resolver exploded",
                },
            },
        }
    )
    report_file = tmp_path / ".tmp" / "build-report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(json.dumps(report.to_dict()), encoding="utf-8")

    exit_code = main(
        [
            "write-summary",
            "--report-file",
            str(report_file),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == render_failure_summary_markdown(report) + "\n"


def test_write_summary_command_prints_failure_markdown_and_telegram_for_both(
    tmp_path: Path,
    capsys,
) -> None:
    report = BuildReport.from_dict(
        {
            "entries": [],
            "metadata": {
                "result": "failure",
                "failure": {
                    "stage": "build",
                    "image_name": "tg-signer",
                    "target_name": "worker",
                    "message": "docker build failed",
                    "exit_code": 9,
                    "command": "docker build ...",
                },
            },
        }
    )
    report_file = tmp_path / ".tmp" / "build-report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(json.dumps(report.to_dict()), encoding="utf-8")

    exit_code = main(
        [
            "write-summary",
            "--report-file",
            str(report_file),
            "--format",
            "both",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    expected_markdown = render_failure_summary_markdown(report)
    expected_telegram = render_failure_summary_telegram_html(report)
    assert captured.out == f"{expected_markdown}\n\n{expected_telegram}\n"


def test_write_summary_command_writes_github_step_summary_with_trailing_newline(
    tmp_path: Path,
    capsys,
) -> None:
    report = BuildReport.from_dict({"entries": []})
    report_file = tmp_path / ".tmp" / "build-report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(json.dumps(report.to_dict()), encoding="utf-8")
    summary_file = tmp_path / ".tmp" / "summary.md"

    exit_code = main(
        [
            "write-summary",
            "--report-file",
            str(report_file),
            "--github-step-summary",
            str(summary_file),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    expected_markdown = render_summary_markdown(build_summary_model(report))
    assert captured.out == expected_markdown + "\n"
    assert summary_file.read_text(encoding="utf-8") == expected_markdown + "\n"


def test_build_workflow_uses_direct_build_args(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((repo_root / ".github" / "workflows" / "build.yml").read_text())

    on_section = workflow.get("on") if isinstance(workflow, dict) else None
    if on_section is None and isinstance(workflow, dict):
        on_section = workflow.get(True)
    assert on_section is not None

    dispatch_inputs = on_section["workflow_dispatch"]["inputs"]
    assert dispatch_inputs["targets"]["type"] == "string"
    assert dispatch_inputs["force"]["type"] == "boolean"
    assert dispatch_inputs["force"]["default"] is False

    assert on_section["push"]["branches"] == ["main"]

    steps = workflow["jobs"]["build"]["steps"]
    steps_by_name = {step["name"]: step for step in steps}

    assert workflow["env"]["BUILD_REPORT_FILE"] == ".tmp/build-report.json"
    assert "SELECTION_FILE" not in workflow["env"]
    assert "Select build targets" not in steps_by_name

    build_step = steps_by_name["Build selected targets"]
    assert "python -m tooling.build build" in build_step["run"]
    assert "--report-file \"$BUILD_REPORT_FILE\"" in build_step["run"]
    assert "args+=(--changed-file \"$file\")" in build_step["run"]
    assert "RAW_TARGETS=\"$raw_targets\" python -c" in build_step["run"]
    assert "INPUT_FORCE" in build_step["env"]
    assert "if [[ \"$INPUT_FORCE\" == 'true' ]]; then" in build_step["run"]
    assert "args+=(--force)" in build_step["run"]
    assert "select-targets" not in build_step["run"]
    assert "selection-file" not in build_step["run"]

    build_script = tmp_path / "build-step.sh"
    build_script.write_text(build_step["run"], encoding="utf-8")
    syntax_check = subprocess.run(
        ["bash", "-n", str(build_script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax_check.returncode == 0, syntax_check.stderr

    report_guard = "hashFiles('main/.tmp/build-report.json') != ''"

    success_telegram_step = steps_by_name["Send Telegram success summary"]
    assert success_telegram_step["if"] == f"success() && {report_guard}"
    assert "python -m tooling.build send-telegram" in success_telegram_step["run"]
    assert "--report-file \"$BUILD_REPORT_FILE\"" in success_telegram_step["run"]
    assert "--template success" in success_telegram_step["run"]

    failure_telegram_step = steps_by_name["Send Telegram failure summary"]
    assert failure_telegram_step["if"] == f"failure() && {report_guard}"
    assert "python -m tooling.build send-telegram" in failure_telegram_step["run"]
    assert "--report-file \"$BUILD_REPORT_FILE\"" in failure_telegram_step["run"]
    assert "--template failure" in failure_telegram_step["run"]

    summary_step = steps_by_name["Write build summary"]
    assert summary_step["if"] == f"always() && {report_guard}"
    assert "python -m tooling.build write-summary" in summary_step["run"]
    assert "--report-file \"$BUILD_REPORT_FILE\"" in summary_step["run"]
    assert "--github-step-summary \"$GITHUB_STEP_SUMMARY\"" in summary_step["run"]
    assert "--format markdown" in summary_step["run"]
    assert "selection-file" not in summary_step["run"]



