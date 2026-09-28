from pathlib import Path
import subprocess
import tempfile

import pytest

from tooling.build.docker import BuildError, build_command, image_tags, run_build


def test_image_tags_matches_legacy_latest_and_version_rules() -> None:
    assert image_tags("rr", "1.2.3") == ("rr-latest", "rr-1.2.3")
    assert image_tags("rr", "base") == ("rr-latest", "rr-base")
    assert image_tags("base", "1.2.3") == ("base-latest", "base-1.2.3")
    assert image_tags("null", None) == ("latest", None)


@pytest.mark.parametrize("empty_version", [None, "", "null"])
def test_build_command_skips_version_tag_and_build_arg_for_empty_ci_version(empty_version: str | None) -> None:
    assert build_command(
        "demo/repo",
        name="rr",
        version=empty_version,
        build_target="caddy-rr",
        dockerfile="Dockerfile",
        local=False,
        platform="linux/amd64",
    ) == [
        "docker",
        "buildx",
        "build",
        "--push",
        "--target",
        "caddy-rr",
        "--platform",
        "linux/amd64",
        "-t",
        "demo/repo:rr-latest",
        "-f",
        "Dockerfile",
        ".",
    ]


def test_build_command_uses_docker_build_load_in_local_mode() -> None:
    assert build_command(
        "demo/repo",
        name="rr",
        version="1.2.3",
        build_target="caddy-rr",
        dockerfile="Dockerfile.debug",
        local=True,
    ) == [
        "docker",
        "build",
        "--load",
        "--target",
        "caddy-rr",
        "--build-arg",
        "VERSION=1.2.3",
        "-t",
        "demo/repo:rr-latest",
        "-f",
        "Dockerfile.debug",
        ".",
    ]


def test_build_command_uses_docker_buildx_build_push_in_ci_mode() -> None:
    assert build_command(
        "demo/repo",
        name="rr",
        version="1.2.3",
        build_target="caddy-rr",
        dockerfile="Dockerfile",
        local=False,
        platform="linux/amd64",
    ) == [
        "docker",
        "buildx",
        "build",
        "--push",
        "--target",
        "caddy-rr",
        "--platform",
        "linux/amd64",
        "--build-arg",
        "VERSION=1.2.3",
        "-t",
        "demo/repo:rr-1.2.3",
        "-t",
        "demo/repo:rr-latest",
        "-f",
        "Dockerfile",
        ".",
    ]


def test_build_command_treats_base_version_as_normal_string() -> None:
    assert build_command(
        "demo/repo",
        name="rr",
        version="base",
        build_target="caddy-rr",
        dockerfile="Dockerfile",
        local=False,
        platform="linux/amd64",
    ) == [
        "docker",
        "buildx",
        "build",
        "--push",
        "--target",
        "caddy-rr",
        "--platform",
        "linux/amd64",
        "--build-arg",
        "VERSION=base",
        "-t",
        "demo/repo:rr-base",
        "-t",
        "demo/repo:rr-latest",
        "-f",
        "Dockerfile",
        ".",
    ]


def test_run_build_executes_subprocess_with_check_true_in_image_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_dir = tmp_path / "caddy"
    image_dir.mkdir()
    calls: list[dict[str, object]] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool, stdout, stderr, text: bool) -> None:
        calls.append(
            {
                "command": command,
                "cwd": cwd,
                "check": check,
                "stdout_name": type(stdout).__name__,
                "stderr_name": type(stderr).__name__,
                "text": text,
            }
        )
        stdout.write("")
        stderr.write("")

    monkeypatch.setattr("tooling.build.docker.subprocess.run", fake_run)

    run_build(["docker", "build", "--load"], image_dir)

    assert calls == [
        {
            "command": ["docker", "build", "--load"],
            "cwd": image_dir,
            "check": True,
            "stdout_name": "_TemporaryFileWrapper",
            "stderr_name": "_TemporaryFileWrapper",
            "text": True,
        }
    ]


def test_run_build_raises_build_error_with_buffered_output_when_command_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_dir = tmp_path / "caddy"
    image_dir.mkdir()

    def fake_run(command: list[str], *, cwd: Path, check: bool, stdout, stderr, text: bool) -> None:
        stdout.write("layer 1\n")
        stderr.write("boom\n")
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
        )

    monkeypatch.setattr("tooling.build.docker.subprocess.run", fake_run)

    with pytest.raises(BuildError) as exc_info:
        run_build(["docker", "buildx", "build", "--push"], image_dir)

    assert exc_info.value.returncode == 1
    assert exc_info.value.command == ["docker", "buildx", "build", "--push"]
    assert exc_info.value.output == "layer 1\nboom\n"


def test_run_build_disables_buffering_in_debug_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image_dir = tmp_path / "caddy"
    image_dir.mkdir()
    calls: list[dict[str, object]] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool, stdout, stderr, text: bool) -> None:
        calls.append(
            {
                "command": command,
                "cwd": cwd,
                "check": check,
                "stdout": stdout,
                "stderr": stderr,
                "text": text,
            }
        )

    monkeypatch.setattr("tooling.build.docker.subprocess.run", fake_run)

    run_build(["docker", "build", "--load"], image_dir, debug=True)

    assert calls == [
        {
            "command": ["docker", "build", "--load"],
            "cwd": image_dir,
            "check": True,
            "stdout": None,
            "stderr": None,
            "text": True,
        }
    ]
