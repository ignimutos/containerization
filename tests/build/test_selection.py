from __future__ import annotations

import pytest

from tooling.build.models import ResolvedTargetState
from tooling.build.selection import (
    CLI_MINUS_TOKEN_PREFIX,
    SelectionSemanticError,
    SelectionSyntaxError,
    evaluate_manual_selector,
    normalize_expression_tokens,
    parse_manual_selector,
    resolved_images,
)


def _entry(image: str, target: str | None) -> ResolvedTargetState:
    return ResolvedTargetState(image_name=image, target_name=target)


def _pairs(entries: list[ResolvedTargetState]) -> list[tuple[str, str | None]]:
    return [(entry.image_name, entry.target_name) for entry in entries]


def test_parse_manual_selector_keeps_sign_and_ignores_empty_tokens() -> None:
    assert parse_manual_selector("alpha,,+beta\n\n-gamma,\n") == [
        "alpha",
        "+beta",
        "-gamma",
    ]


def test_parse_manual_selector_rejects_internal_whitespace() -> None:
    with pytest.raises(SelectionSyntaxError, match="internal whitespace"):
        parse_manual_selector("alpha: worker")


def test_normalize_expression_tokens_splits_comma_separated_argv_tokens() -> None:
    assert normalize_expression_tokens(["alpha,beta:worker", "+all", "-gamma:"]) == [
        "alpha",
        "beta:worker",
        "+all",
        "-gamma:",
    ]


def test_normalize_expression_tokens_restores_cli_minus_prefix() -> None:
    assert normalize_expression_tokens([f"{CLI_MINUS_TOKEN_PREFIX}caddy:naive"]) == [
        "-caddy:naive"
    ]


@pytest.mark.parametrize("expression", ["+", "-", ":release", "++alpha", "--alpha"])
def test_parse_manual_selector_rejects_syntax_errors_immediately(expression: str) -> None:
    with pytest.raises(SelectionSyntaxError):
        parse_manual_selector(expression)



def test_resolved_images_deduplicates_by_first_appearance_order() -> None:
    entries = [
        _entry("zeta", None),
        _entry("alpha", "release"),
        _entry("zeta", "worker"),
        _entry("beta", None),
        _entry("alpha", "debug"),
    ]

    assert resolved_images(entries) == ["zeta", "alpha", "beta"]



def test_evaluate_manual_selector_supports_all_plus_all_and_minus_all() -> None:
    entries = [
        _entry("zeta", None),
        _entry("alpha", "release"),
        _entry("alpha", "debug"),
        _entry("beta", None),
    ]

    assert _pairs(evaluate_manual_selector("all", entries)) == [
        ("alpha", "release"),
        ("alpha", "debug"),
        ("beta", None),
        ("zeta", None),
    ]
    assert _pairs(evaluate_manual_selector("+all", entries)) == [
        ("alpha", "release"),
        ("alpha", "debug"),
        ("beta", None),
        ("zeta", None),
    ]
    assert _pairs(evaluate_manual_selector("all,-all,+alpha:release", entries)) == [
        ("alpha", "release"),
    ]



def test_evaluate_manual_selector_supports_image_image_name_and_image_colon() -> None:
    entries = [
        _entry("alpha", None),
        _entry("alpha", "release"),
        _entry("beta", "worker"),
    ]

    assert _pairs(evaluate_manual_selector("alpha", entries)) == [
        ("alpha", None),
        ("alpha", "release"),
    ]
    assert _pairs(evaluate_manual_selector("alpha:release", entries)) == [
        ("alpha", "release"),
    ]
    assert _pairs(evaluate_manual_selector("alpha:", entries)) == [
        ("alpha", None),
    ]



def test_evaluate_manual_selector_applies_operations_left_to_right() -> None:
    entries = [
        _entry("alpha", None),
        _entry("alpha", "release"),
        _entry("beta", None),
    ]

    assert _pairs(evaluate_manual_selector("all,-alpha,+alpha:release", entries)) == [
        ("alpha", "release"),
        ("beta", None),
    ]



def test_evaluate_manual_selector_raises_on_empty_result() -> None:
    entries = [_entry("alpha", None)]

    with pytest.raises(SelectionSemanticError, match="empty"):
        evaluate_manual_selector("all,-all", entries)



def test_evaluate_manual_selector_aggregates_semantic_errors() -> None:
    entries = [
        _entry("alpha", "release"),
        _entry("beta", "worker"),
    ]

    with pytest.raises(SelectionSemanticError) as exc_info:
        evaluate_manual_selector("ghost,alpha:missing,beta:", entries)

    message = str(exc_info.value)
    assert "unknown image 'ghost'" in message
    assert "unknown target 'alpha:missing'" in message
    assert "no empty-name target for image 'beta'" in message



def test_evaluate_manual_selector_deduplicates_duplicate_resolved_entries() -> None:
    entries = [
        _entry("alpha", "release"),
        _entry("alpha", "release"),
        _entry("beta", None),
        _entry("beta", None),
    ]

    assert _pairs(evaluate_manual_selector("all", entries)) == [
        ("alpha", "release"),
        ("beta", None),
    ]
