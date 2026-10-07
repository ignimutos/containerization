from pathlib import PurePosixPath


GLOBAL_BUILD_TRIGGER_FILES = {"pyproject.toml", "uv.lock"}


def select_targets(*, changed_files: list[str], all_image_names: set[str]) -> list[str]:
    if not changed_files:
        return sorted(all_image_names)

    selected: set[str] = set()
    for changed_file in changed_files:
        path = PurePosixPath(changed_file)
        parts = path.parts
        if len(parts) >= 2 and parts[0] == "images":
            image_name = parts[1]
            if image_name in all_image_names:
                selected.add(image_name)
            continue
        if len(parts) >= 2 and parts[0] == "tooling" and parts[1] == "build":
            return sorted(all_image_names)
        if len(parts) >= 2 and parts[0] == "tests" and parts[1] == "build":
            return sorted(all_image_names)
        if changed_file in GLOBAL_BUILD_TRIGGER_FILES:
            return sorted(all_image_names)

    return sorted(selected)
