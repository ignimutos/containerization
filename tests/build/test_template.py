from pathlib import Path

import pytest

from tooling.build.cli import _template_for
from tooling.build.models import TargetConfig
from tooling.build.template import render_template


def test_render_template_expands_repos_per_target(tmp_path: Path) -> None:
    template_path = tmp_path / "Dockerfile.j2"
    template_path.write_text(
        "xcaddy build{% for repo in repos %} \\\n"
        "      --with github.com/{{ repo }}{% endfor %}\n"
    )

    rendered = render_template(
        template_path,
        {"repos": ["caddy-dns/cloudflare", "mholt/caddy-l4"], "version": "2.11.2"},
    )

    assert rendered == (
        "xcaddy build \\\n"
        "      --with github.com/caddy-dns/cloudflare \\\n"
        "      --with github.com/mholt/caddy-l4\n"
    )


def test_render_template_uses_non_null_context_only(tmp_path: Path) -> None:
    template_path = tmp_path / "Dockerfile.j2"
    template_path.write_text("ARG VERSION={{ version }}\n")

    rendered = render_template(template_path, {"version": "1.2.3", "repos": []})

    assert rendered == "ARG VERSION=1.2.3\n"


def test_render_template_fails_loudly_on_undefined_context(tmp_path: Path) -> None:
    template_path = tmp_path / "Dockerfile.j2"
    template_path.write_text("ARG VERSION={{ version }}\n")

    with pytest.raises(Exception):
        render_template(template_path, {})


def test_render_template_reports_missing_template(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="template not found"):
        render_template(tmp_path / "Dockerfile.j2", {})


def test_explicit_template_field_wins_over_default(tmp_path: Path) -> None:
    image_dir = tmp_path / "images" / "alpha"
    image_dir.mkdir(parents=True)
    (image_dir / "Dockerfile.j2").write_text("default\n")
    (image_dir / "Other.j2").write_text("explicit\n")

    assert _template_for(image_dir, TargetConfig()) == "Dockerfile.j2"
    assert _template_for(image_dir, TargetConfig(template="Other.j2")) == "Other.j2"


def test_image_without_template_file_is_not_templated(tmp_path: Path) -> None:
    image_dir = tmp_path / "images" / "alpha"
    image_dir.mkdir(parents=True)

    assert _template_for(image_dir, TargetConfig()) is None
