from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ResolvedTargetState


_WHITESPACE_RE = re.compile(r"\s")
CLI_MINUS_TOKEN_PREFIX = "__cli_minus_token__"


class SelectionSyntaxError(ValueError):
    pass


class SelectionSemanticError(ValueError):
    pass


@dataclass(slots=True)
class _Universe:
    ordered: list[ResolvedTargetState]
    by_image: dict[str, list[ResolvedTargetState]]
    by_pair: dict[tuple[str, str | None], ResolvedTargetState]


def normalize_expression_tokens(raw_tokens: list[str]) -> list[str]:
    tokens: list[str] = []
    for raw in raw_tokens:
        restored = raw
        if restored.startswith(CLI_MINUS_TOKEN_PREFIX):
            restored = f"-{restored.removeprefix(CLI_MINUS_TOKEN_PREFIX)}"
        tokens.extend(parse_manual_selector(restored))
    return tokens


def looks_like_expression_token(token: str) -> bool:
    if token.startswith("--"):
        return False
    try:
        parse_manual_selector(token)
    except SelectionSyntaxError:
        return False
    return True


def parse_manual_selector(expression: str) -> list[str]:
    raw_tokens = re.split(r"[\n,]", expression)
    tokens: list[str] = []

    for raw in raw_tokens:
        token = raw.strip(" \t\r\n")
        if token == "":
            continue
        if _WHITESPACE_RE.search(token):
            raise SelectionSyntaxError(f"manual selector token contains internal whitespace: {token!r}")

        if token[0] in "+-":
            operation = token[0]
            body = token[1:]
            if body == "":
                raise SelectionSyntaxError(f"manual selector token missing body: {token!r}")
            if body[0] in "+-":
                raise SelectionSyntaxError(f"manual selector token has invalid sign prefix: {token!r}")
            _validate_selector_body(body, token)
            tokens.append(f"{operation}{body}")
            continue

        _validate_selector_body(token, token)
        tokens.append(token)

    return tokens


def resolved_images(resolved_entries: list[ResolvedTargetState]) -> list[str]:
    seen: set[str] = set()
    images: list[str] = []

    for entry in resolved_entries:
        if entry.image_name in seen:
            continue
        seen.add(entry.image_name)
        images.append(entry.image_name)

    return images


def evaluate_manual_selector(
    expression: str,
    resolved_entries: list[ResolvedTargetState],
) -> list[ResolvedTargetState]:
    tokens = parse_manual_selector(expression)
    universe = _build_universe(resolved_entries)

    selected: set[tuple[str, str | None]] = set()
    semantic_errors: list[str] = []

    for token in tokens:
        if token[0] in "+-":
            operation = token[0]
            body = token[1:]
        else:
            operation = "+"
            body = token

        matched, error = _match_token(body, universe)
        if error is not None:
            semantic_errors.append(error)
            continue

        if operation == "+":
            selected.update(matched)
        else:
            selected.difference_update(matched)

    if semantic_errors:
        raise SelectionSemanticError("; ".join(semantic_errors))

    output: list[ResolvedTargetState] = []
    emitted: set[tuple[str, str | None]] = set()
    for entry in universe.ordered:
        key = (entry.image_name, entry.target_name)
        if key not in selected or key in emitted:
            continue
        emitted.add(key)
        output.append(entry)

    if not output:
        raise SelectionSemanticError("manual selector resolved to empty result")
    return output


def _build_universe(resolved_entries: list[ResolvedTargetState]) -> _Universe:
    by_image: dict[str, list[ResolvedTargetState]] = {}
    by_pair: dict[tuple[str, str | None], ResolvedTargetState] = {}

    for entry in resolved_entries:
        by_image.setdefault(entry.image_name, []).append(entry)
        by_pair[(entry.image_name, entry.target_name)] = entry

    ordered: list[ResolvedTargetState] = []
    for image_name in sorted(by_image):
        ordered.extend(by_image[image_name])

    return _Universe(ordered=ordered, by_image=by_image, by_pair=by_pair)


def _validate_selector_body(body: str, token: str) -> None:
    if body == "":
        raise SelectionSyntaxError(f"manual selector token missing body: {token!r}")

    if body.startswith(":"):
        raise SelectionSyntaxError(f"manual selector token has missing image before colon: {token!r}")


def _match_token(
    body: str,
    universe: _Universe,
) -> tuple[set[tuple[str, str | None]], str | None]:
    if body == "all":
        return {(entry.image_name, entry.target_name) for entry in universe.ordered}, None

    if ":" not in body:
        image_name = body
        entries = universe.by_image.get(image_name)
        if entries is None:
            return set(), f"unknown image '{image_name}'"
        return {(entry.image_name, entry.target_name) for entry in entries}, None

    image_name, target_name = body.split(":", 1)
    entries = universe.by_image.get(image_name)
    if entries is None:
        return set(), f"unknown image '{image_name}'"

    if target_name == "":
        key = (image_name, None)
        if key not in universe.by_pair:
            return set(), f"no empty-name target for image '{image_name}'"
        return {key}, None

    key = (image_name, target_name)
    if key not in universe.by_pair:
        return set(), f"unknown target '{image_name}:{target_name}'"
    return {key}, None
