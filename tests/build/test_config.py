from pathlib import Path
from textwrap import dedent

import pytest

from tooling.build.config import discover_image_configs, load_build_config
from tooling.build.models import AlpinePkgArgs, DockerHubTagArgs, GitHubShaArgs, GitHubTagArgs, ResolverSpec


def test_load_build_config_uses_directory_name_as_default_image_name(tmp_path: Path) -> None:
    image_dir = tmp_path / "images" / "caddy"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        dedent(
            """
            version:
              github_tag:
                repo: caddyserver/caddy
            targets:
              - target: caddy-base
                sha:
                  github_sha:
                    repos:
                      - caddy-dns/cloudflare
              - name: rr
                target: caddy-rr
                sha:
                  github_sha:
                    repos:
                      - caddy-dns/cloudflare
                      - caddyserver/replace-response
            """
        ).strip()
    )

    config = load_build_config(image_dir)

    assert config.image_name == "caddy"
    assert config.version == ResolverSpec(
        github_tag=GitHubTagArgs(repo="caddyserver/caddy")
    )
    assert len(config.targets) == 2
    assert config.targets[0].name is None
    assert config.targets[0].target == "caddy-base"
    assert config.targets[0].sha == ResolverSpec(
        github_sha=GitHubShaArgs(repos=["caddy-dns/cloudflare"])
    )
    assert config.targets[1].name == "rr"
    assert config.targets[1].target == "caddy-rr"


def test_load_build_config_rejects_base_target_name(tmp_path: Path) -> None:
    image_dir = tmp_path / "images" / "caddy"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        dedent(
            """
            targets:
              - name: base
            """
        ).strip()
    )

    with pytest.raises(ValueError, match="targets\[\]\.name must not be 'base'"):
        load_build_config(image_dir)


def test_load_build_config_keeps_unnamed_default_target(tmp_path: Path) -> None:
    image_dir = tmp_path / "images" / "caddy"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        dedent(
            """
            targets:
              - target: caddy-base
              - name: rr
                target: caddy-rr
            """
        ).strip()
    )

    config = load_build_config(image_dir)

    assert [target.name for target in config.targets] == [None, "rr"]
    assert [target.target for target in config.targets] == ["caddy-base", "caddy-rr"]


def test_load_build_config_prefers_explicit_name_and_allows_empty_targets(tmp_path: Path) -> None:
    image_dir = tmp_path / "images" / "tor2socks"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        dedent(
            """
            name: custom-tor
            version:
              alpine_pkg:
                package: tor
                branch: edge
                repository: community
            """
        ).strip()
    )

    config = load_build_config(image_dir)

    assert config.image_name == "custom-tor"
    assert config.version == ResolverSpec(
        alpine_pkg=AlpinePkgArgs(
            package="tor",
            branch="edge",
            repository="community",
        )
    )
    assert config.targets == []



def test_load_build_config_supports_docker_hub_tag_version(tmp_path: Path) -> None:
    image_dir = tmp_path / "images" / "caddy"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        dedent(
            """
            version:
              docker_hub_tag:
                namespace: library
                repository: caddy
                regex: ^(\\d+\\.\\d+\\.\\d+)-builder-alpine$
            """
        ).strip()
    )

    config = load_build_config(image_dir)

    assert config.version is not None
    resolver = getattr(config.version, "docker_hub_tag")
    assert resolver is not None
    assert resolver.namespace == "library"
    assert resolver.repository == "caddy"
    assert resolver.regex == r"^(\d+\.\d+\.\d+)-builder-alpine$"


def test_repo_caddy_and_naive_server_use_caddy_builder_alpine_docker_hub_tag() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    expected = ResolverSpec(
        docker_hub_tag=DockerHubTagArgs(
            namespace="library",
            repository="caddy",
            regex=r"^(\d+\.\d+\.\d+)-builder-alpine$",
        )
    )

    caddy_config = load_build_config(repo_root / "images" / "caddy")
    assert caddy_config.version == expected

    naive_config = load_build_config(repo_root / "images" / "naive-server")
    assert naive_config.targets
    assert naive_config.targets[0].version == expected


def test_discover_image_configs_returns_sorted_config_paths(tmp_path: Path) -> None:
    for name in ["tor2socks", "caddy"]:
        image_dir = tmp_path / "images" / name
        image_dir.mkdir(parents=True)
        (image_dir / "config.yml").write_text("targets: []\n")

    found = discover_image_configs(tmp_path)

    assert found == [
        tmp_path / "images" / "caddy" / "config.yml",
        tmp_path / "images" / "tor2socks" / "config.yml",
    ]


@pytest.mark.parametrize("raw", ["false\n", "0\n", "[]\n"])
def test_load_build_config_rejects_non_mapping_root(tmp_path: Path, raw: str) -> None:
    image_dir = tmp_path / "images" / "broken-root"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(raw)

    with pytest.raises(ValueError, match="config.yml must contain a mapping"):
        load_build_config(image_dir)


def test_load_build_config_rejects_invalid_targets_shape(tmp_path: Path) -> None:
    image_dir = tmp_path / "images" / "broken-targets"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets: not-a-list\n")

    with pytest.raises(ValueError, match="targets"):
        load_build_config(image_dir)


def test_load_build_config_rejects_invalid_target_entry_shape(tmp_path: Path) -> None:
    image_dir = tmp_path / "images" / "broken-target-entry"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text("targets:\n  - not-a-mapping\n")

    with pytest.raises(ValueError, match="each target"):
        load_build_config(image_dir)


def test_load_build_config_rejects_invalid_string_fields(tmp_path: Path) -> None:
    image_dir = tmp_path / "images" / "broken-fields"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        dedent(
            """
            name: [bad]
            targets:
              - target: 123
                dockerfile: false
            """
        ).strip()
    )

    with pytest.raises(ValueError, match="name"):
        load_build_config(image_dir)


def test_load_build_config_rejects_invalid_resolver_shape(tmp_path: Path) -> None:
    image_dir = tmp_path / "images" / "broken-resolver"
    image_dir.mkdir(parents=True)
    (image_dir / "config.yml").write_text(
        dedent(
            """
            version:
              github_tag:
                repo: caddyserver/caddy
              alpine_pkg:
                package: tor
            """
        ).strip()
    )

    with pytest.raises(ValueError, match="exactly one resolver"):
        load_build_config(image_dir)
