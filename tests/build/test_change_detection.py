from tooling.build.change_detection import select_targets


def test_select_targets_maps_image_paths_to_image_names() -> None:
    assert select_targets(
        changed_files=["images/caddy/Dockerfile", "images/tg-signer/config.yml"],
        all_image_names={"caddy", "tg-signer", "tor2socks"},
    ) == ["caddy", "tg-signer"]


def test_select_targets_ignores_unknown_image_paths() -> None:
    assert select_targets(
        changed_files=["images/unknown/Dockerfile", "images/caddy/Dockerfile"],
        all_image_names={"caddy", "tg-signer"},
    ) == ["caddy"]


def test_select_targets_returns_all_for_shared_tooling_changes() -> None:
    assert select_targets(
        changed_files=["tooling/build/resolvers.py"],
        all_image_names={"caddy", "tg-signer"},
    ) == ["caddy", "tg-signer"]


def test_select_targets_returns_all_for_shared_test_changes() -> None:
    assert select_targets(
        changed_files=["tests/build/test_cli.py"],
        all_image_names={"caddy", "tg-signer"},
    ) == ["caddy", "tg-signer"]


def test_select_targets_returns_all_for_dependency_metadata_changes() -> None:
    assert select_targets(
        changed_files=["pyproject.toml"],
        all_image_names={"caddy", "tg-signer"},
    ) == ["caddy", "tg-signer"]
