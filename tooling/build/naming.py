"""Helpers for build names that must match the legacy shell `union()` rule.

`join_name_parts()` is intentionally narrow: it is only for identifiers that
must collapse the shell sentinel values still used by the current scripts.
It is not a general-purpose string join helper.
"""

_IGNORED_NAME_PARTS = frozenset({"", "null"})


def join_name_parts(*parts: str | None) -> str:
    """Join build name parts using the legacy shell `union()` semantics.

    The legacy shell implementation treats `None`, `""`, and `"null"`
    as omitted segments, so callers that use this helper will produce
    the same keys and values as the existing scripts.
    """
    values: list[str] = []
    for part in parts:
        if part is None or part in _IGNORED_NAME_PARTS:
            continue
        values.append(part)
    return "-".join(values)
