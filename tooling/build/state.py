from __future__ import annotations

from pathlib import Path

import yaml

from .models import ResolvedTargetState, TargetState

_DEFAULT_TARGET_KEY = "default"


class BuildStateStore:
    def __init__(self, state_file: str | Path) -> None:
        self.state_file = Path(state_file)
        self._state = self._load_state()

    def should_build(
        self,
        image_name: str | ResolvedTargetState | None,
        target_name: str | None = None,
        version: str | None = None,
        sha: str | None = None,
    ) -> bool:
        resolved = self._coerce_resolved_state(image_name, target_name, version, sha)
        image_key, target_key = self._build_state_keys(
            resolved.image_name,
            resolved.target_name,
        )
        current = resolved.to_target_state()
        if current is None:
            return False

        previous = self._state.get(image_key, {}).get(target_key)
        return previous != current

    def record_success(
        self,
        image_name: str | ResolvedTargetState | None,
        target_name: str | None = None,
        version: str | None = None,
        sha: str | None = None,
    ) -> None:
        resolved = self._coerce_resolved_state(image_name, target_name, version, sha)
        current = resolved.to_target_state()
        if current is None:
            return

        image_key, target_key = self._build_state_keys(
            resolved.image_name,
            resolved.target_name,
        )
        targets = self._state.setdefault(image_key, {})
        targets[target_key] = current

    def get_state(
        self,
        image_name: str,
        target_name: str | None = None,
    ) -> TargetState | None:
        image_key, target_key = self._build_state_keys(image_name, target_name)
        return self._state.get(image_key, {}).get(target_key)

    def save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        serialized: dict[str, object] = {}
        for image_name, targets in self._state.items():
            serialized[image_name] = {
                target_name: {
                    "version": target_state.version,
                    "components": dict(target_state.components),
                }
                for target_name, target_state in targets.items()
            }
        with self.state_file.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(
                serialized,
                handle,
                sort_keys=False,
                default_flow_style=False,
            )

    def _load_state(self) -> dict[str, dict[str, TargetState]]:
        if not self.state_file.exists():
            return {}
        raw_data = yaml.safe_load(self.state_file.read_text())
        if raw_data is None:
            return {}
        if not isinstance(raw_data, dict):
            raise ValueError("version.yml must contain a mapping")

        return self._load_nested_state(raw_data)

    def _load_nested_state(self, raw_data: dict[object, object]) -> dict[str, dict[str, TargetState]]:
        state: dict[str, dict[str, TargetState]] = {}
        for image_name, raw_targets in raw_data.items():
            if not isinstance(image_name, str):
                raise ValueError("version.yml keys must be strings")
            if raw_targets is None:
                state[image_name] = {}
                continue
            if not isinstance(raw_targets, dict):
                raise ValueError("version.yml values must be mappings")

            targets: dict[str, TargetState] = {}
            for target_name, raw_target_state in raw_targets.items():
                if not isinstance(target_name, str):
                    raise ValueError("version.yml target keys must be strings")
                normalized_target_name = self._build_target_key(target_name)
                targets[normalized_target_name] = self._parse_target_state(raw_target_state)
            state[image_name] = targets
        return state

    def _parse_target_state(self, raw_target_state: object) -> TargetState:
        if not isinstance(raw_target_state, dict):
            raise ValueError("version.yml target values must be mappings")

        version = raw_target_state.get("version")
        if version is not None and not isinstance(version, str):
            raise ValueError("version.yml target versions must be strings")

        raw_components = raw_target_state.get("components", {})
        if raw_components is None:
            raw_components = {}
        if not isinstance(raw_components, dict) or any(
            not isinstance(component_name, str) or not isinstance(component_value, str)
            for component_name, component_value in raw_components.items()
        ):
            raise ValueError("version.yml target components must be string mappings")

        return TargetState(version=version, components=dict(raw_components))

    def _build_state_keys(
        self,
        image_name: str | None,
        target_name: str | None,
    ) -> tuple[str, str]:
        image_key = self._build_image_key(image_name)
        target_key = self._build_target_key(target_name)
        return image_key, target_key

    def _coerce_resolved_state(
        self,
        image_name: str | ResolvedTargetState | None,
        target_name: str | None,
        version: str | None,
        sha: str | None,
    ) -> ResolvedTargetState:
        if isinstance(image_name, ResolvedTargetState):
            return image_name
        return ResolvedTargetState.from_legacy(image_name, target_name, version, sha)

    def _build_image_key(self, image_name: str | None) -> str:
        if image_name in {None, ""}:
            raise ValueError("build state key must not be empty")
        return image_name

    def _build_target_key(self, target_name: str | None) -> str:
        if target_name is None:
            return _DEFAULT_TARGET_KEY
        return target_name


def resolve_state_file(
    base_dir: str | Path, state_file: str | Path | None = None
) -> Path | None:
    if state_file is not None:
        return Path(state_file)

    base_dir = Path(base_dir)
    sibling_state_file = base_dir.parent / "version" / "version.yml"
    if sibling_state_file.exists():
        return sibling_state_file

    return None
