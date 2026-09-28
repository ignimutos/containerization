from pathlib import Path

import pytest
import yaml

from tooling.build.models import ResolvedTargetState
from tooling.build.naming import join_name_parts
from tooling.build.state import BuildStateStore, resolve_state_file


def test_join_name_parts_matches_shell_union_behavior() -> None:
    assert join_name_parts("tg-signer", None, "", "null", "base", "amd64") == "tg-signer-base-amd64"
    assert join_name_parts("base", "", None, "null") == "base"


def test_build_state_store_reads_nested_target_records(tmp_path: Path) -> None:
    version_file = tmp_path / "version.yml"
    version_file.write_text(
        """
        caddy:
          default:
            version: 1.2.3
            components: {}
          rr:
            version: 1.2.3
            components:
              sha: abc123
        """.strip()
        + "\n"
    )
    store = BuildStateStore(version_file)

    assert store.should_build("caddy", "base", "1.2.3", None) is True
    assert store.should_build("caddy", "rr", "1.2.3", "abc123") is False
    assert store.should_build("caddy", "rr", "1.2.3", "def456") is True
    assert store.should_build("caddy", None, None, None) is False


@pytest.mark.parametrize(
    ("image_name", "target_name"),
    [
        (None, None),
        ("", None),
    ],
)
def test_build_state_store_rejects_folded_empty_keys(
    tmp_path: Path,
    image_name: str | None,
    target_name: str | None,
) -> None:
    store = BuildStateStore(tmp_path / "version.yml")

    with pytest.raises(ValueError, match="build state key must not be empty"):
        store.should_build(image_name, target_name, "1.2.3", None)

    with pytest.raises(ValueError, match="build state key must not be empty"):
        store.record_success(image_name, target_name, "1.2.3", None)


def test_build_state_store_rejects_missing_image_name_even_with_target(tmp_path: Path) -> None:
    store = BuildStateStore(tmp_path / "version.yml")

    with pytest.raises(ValueError, match="build state key must not be empty"):
        store.should_build(None, "base", "1.2.3", None)

    with pytest.raises(ValueError, match="build state key must not be empty"):
        store.record_success(None, "base", "1.2.3", None)


def test_record_success_and_save_write_default_target_key_when_target_name_absent(
    tmp_path: Path,
) -> None:
    version_file = tmp_path / "state" / "version.yml"
    store = BuildStateStore(version_file)

    store.record_success(ResolvedTargetState(image_name="caddy", version="1.2.3"))
    store.record_success(
        ResolvedTargetState(
            image_name="caddy",
            target_name="rr",
            version="1.2.3",
            components={"sha": "abc123"},
        )
    )
    store.save()

    assert yaml.safe_load(version_file.read_text()) == {
        "caddy": {
            "default": {"version": "1.2.3", "components": {}},
            "rr": {"version": "1.2.3", "components": {"sha": "abc123"}},
        }
    }



def test_record_success_ignores_empty_state_and_save_does_not_crash(
    tmp_path: Path,
) -> None:
    version_file = tmp_path / "version.yml"
    store = BuildStateStore(version_file)

    store.record_success(ResolvedTargetState(image_name="caddy"))
    store.save()

    assert store._state == {}
    assert yaml.safe_load(version_file.read_text()) == {}


def test_build_state_store_should_build_compares_structured_components(
    tmp_path: Path,
) -> None:
    version_file = tmp_path / "version.yml"
    version_file.write_text(
        """
        caddy:
          rr:
            version: 1.2.3
            components:
              sha: abc123
              deps: def456
        """.strip()
        + "\n"
    )
    store = BuildStateStore(version_file)

    assert store.should_build(
        ResolvedTargetState(
            image_name="caddy",
            target_name="rr",
            version="1.2.3",
            components={"sha": "abc123", "deps": "def456"},
        )
    ) is False
    assert store.should_build(
        ResolvedTargetState(
            image_name="caddy",
            target_name="rr",
            version="1.2.3",
            components={"sha": "abc123", "deps": "zzz999"},
        )
    ) is True



def test_build_state_store_accepts_non_empty_folded_combined_key(tmp_path: Path) -> None:
    store = BuildStateStore(tmp_path / "version.yml")

    assert store.should_build("base", "rr", "1.2.3", None) is True



def test_build_state_store_persists_components_only_state(tmp_path: Path) -> None:
    version_file = tmp_path / "version.yml"
    store = BuildStateStore(version_file)

    state = ResolvedTargetState(
        image_name="caddy",
        target_name="rr",
        version=None,
        components={"sha": "abc123"},
    )
    store.record_success(state)
    store.save()

    assert yaml.safe_load(version_file.read_text()) == {
        "caddy": {
            "rr": {"version": None, "components": {"sha": "abc123"}},
        }
    }

    reloaded_store = BuildStateStore(version_file)
    assert reloaded_store.should_build(state) is False
    assert reloaded_store.should_build(
        ResolvedTargetState(
            image_name="caddy",
            target_name="rr",
            version=None,
            components={"sha": "zzz999"},
        )
    ) is True



def test_build_state_store_keeps_base_target_distinct_from_default_key(tmp_path: Path) -> None:
    version_file = tmp_path / "version.yml"
    version_file.write_text(
        """
        caddy:
          base:
            version: 1.2.3
            components: {}
        """.strip()
        + "\n"
    )
    store = BuildStateStore(version_file)

    assert store.should_build("caddy", "base", "1.2.3", None) is False
    assert store.should_build("caddy", None, "1.2.3", None) is True

    store.save()

    assert yaml.safe_load(version_file.read_text()) == {
        "caddy": {
            "base": {"version": "1.2.3", "components": {}},
        }
    }



def test_build_state_store_rejects_legacy_scalar_top_level_entry(tmp_path: Path) -> None:
    version_file = tmp_path / "version.yml"
    version_file.write_text("caddy: 1.2.3\n")

    with pytest.raises(ValueError, match="version.yml values must be mappings"):
        BuildStateStore(version_file)



def test_build_state_store_rejects_legacy_scalar_target_entry(tmp_path: Path) -> None:
    version_file = tmp_path / "version.yml"
    version_file.write_text("caddy:\n  rr: 1.2.3-abc123\n")

    with pytest.raises(ValueError, match="version.yml target values must be mappings"):
        BuildStateStore(version_file)



def test_resolved_target_state_from_legacy_maps_scalar_sha_to_named_component() -> None:
    state = ResolvedTargetState.from_legacy("caddy", "rr", "1.2.3", "abc123")

    assert state.components == {"sha": "abc123"}


@pytest.mark.parametrize("version", ["", "null"])
def test_resolved_target_state_to_target_state_normalizes_sentinel_versions_with_components(
    version: str,
) -> None:
    state = ResolvedTargetState(
        image_name="caddy",
        target_name="rr",
        version=version,
        components={"sha": "abc123"},
    )

    assert state.to_target_state() == ResolvedTargetState(
        image_name="caddy",
        target_name="rr",
        version=None,
        components={"sha": "abc123"},
    ).to_target_state()


def test_resolved_target_state_to_target_state_keeps_base_version_with_components() -> None:
    state = ResolvedTargetState(
        image_name="caddy",
        target_name="rr",
        version="base",
        components={"sha": "abc123"},
    )

    assert state.to_target_state() == ResolvedTargetState(
        image_name="caddy",
        target_name="rr",
        version="base",
        components={"sha": "abc123"},
    ).to_target_state()


@pytest.mark.parametrize("version", ["", "null"])
def test_resolved_target_state_to_target_state_drops_empty_sentinel_versions(
    version: str,
) -> None:
    state = ResolvedTargetState(
        image_name="caddy",
        target_name=None,
        version=version,
    )

    assert state.to_target_state() is None


def test_resolved_target_state_to_target_state_keeps_base_version_without_components() -> None:
    state = ResolvedTargetState(
        image_name="caddy",
        target_name=None,
        version="base",
    )

    assert state.to_target_state() == ResolvedTargetState(
        image_name="caddy",
        target_name=None,
        version="base",
    ).to_target_state()


def test_build_state_store_accepts_base_and_default_nested_target_keys(
    tmp_path: Path,
) -> None:
    version_file = tmp_path / "version.yml"
    version_file.write_text(
        """
        caddy:
          base:
            version: 1.2.3
            components: {}
          default:
            version: 1.2.4
            components: {}
        """.strip()
        + "\n"
    )

    store = BuildStateStore(version_file)

    assert store.should_build("caddy", "base", "1.2.3", None) is False
    assert store.should_build("caddy", None, "1.2.4", None) is False
    assert store.should_build("caddy", None, "1.2.3", None) is True


def test_build_state_store_rejects_malformed_yaml(tmp_path: Path) -> None:
    version_file = tmp_path / "version.yml"
    version_file.write_text("caddy: [1.2.3\n")

    with pytest.raises(yaml.YAMLError):
        BuildStateStore(version_file)



def test_build_state_store_rejects_non_mapping_top_level_values(tmp_path: Path) -> None:
    version_file = tmp_path / "version.yml"
    version_file.write_text("caddy: 123\n")

    with pytest.raises(ValueError, match="version.yml values must be mappings"):
        BuildStateStore(version_file)



def test_resolve_state_file_returns_explicit_path_when_provided(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspace"
    base_dir.mkdir()
    explicit_path = tmp_path / "custom" / "version.yml"

    assert resolve_state_file(base_dir, explicit_path) == explicit_path



def test_resolve_state_file_uses_sibling_version_branch_file_when_present(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "workspace"
    base_dir.mkdir()
    sibling_state_file = tmp_path / "version" / "version.yml"
    sibling_state_file.parent.mkdir()
    sibling_state_file.write_text("")

    assert resolve_state_file(base_dir) == sibling_state_file



def test_resolve_state_file_returns_none_when_no_supported_location_exists(
    tmp_path: Path,
) -> None:
    base_dir = tmp_path / "workspace"
    base_dir.mkdir()

    assert resolve_state_file(base_dir) is None
