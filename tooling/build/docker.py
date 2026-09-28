from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile

from .naming import join_name_parts


@dataclass
class BuildError(Exception):
    command: list[str]
    returncode: int
    output: str = ""


def image_tags(name: str | None, version: str | None) -> tuple[str, str | None]:
    latest_tag = join_name_parts(name, "latest")
    if version in {None, "", "null"}:
        version_tag = None
    else:
        version_tag = join_name_parts(name, version) or None
    return latest_tag, version_tag


def build_command(
    repository: str,
    *,
    name: str | None,
    version: str | None,
    build_target: str | None,
    dockerfile: str,
    local: bool,
    platform: str | None = None,
) -> list[str]:
    latest_tag, version_tag = image_tags(name, version)
    command = ["docker"]
    if local:
        command.extend(["build", "--load"])
    else:
        command.extend(["buildx", "build", "--push"])

    if build_target:
        command.extend(["--target", build_target])
    if platform and not local:
        command.extend(["--platform", platform])
    if version not in {None, "", "null"}:
        command.extend(["--build-arg", f"VERSION={version}"])
    if version_tag and not local:
        command.extend(["-t", f"{repository}:{version_tag}"])
    command.extend(["-t", f"{repository}:{latest_tag}", "-f", dockerfile, "."])
    return command


def run_build(command: list[str], image_dir: str | Path, debug: bool = False) -> None:
    if debug:
        try:
            subprocess.run(
                command,
                cwd=Path(image_dir),
                check=True,
                stdout=None,
                stderr=None,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise BuildError(command=command, returncode=exc.returncode) from exc
        return

    with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8") as stdout_file, tempfile.NamedTemporaryFile(
        mode="w+", encoding="utf-8"
    ) as stderr_file:
        try:
            subprocess.run(
                command,
                cwd=Path(image_dir),
                check=True,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            stdout_file.seek(0)
            stderr_file.seek(0)
            output = stdout_file.read()
            stderr = stderr_file.read()
            if stderr:
                output = f"{output}{stderr}" if output else stderr
            raise BuildError(command=command, returncode=exc.returncode, output=output) from exc
