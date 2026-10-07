from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2

DEFAULT_TEMPLATE = "Dockerfile.j2"


def render_template(template_path: Path, context: dict[str, Any]) -> str:
    """Render one Dockerfile template against an already-resolved build target.

    Templates live next to the image's `config.yml` and are loaded by basename,
    so `{% include %}` only reaches files inside the image directory. Image
    specific build knowledge that cannot be derived from `config.yml` (a module
    whose upstream repo differs from the path the build tool expects) belongs in
    the template, not in `config.yml`.

    Null context values are dropped rather than rendered as the string `None`:
    a template that requires the value then fails loudly through
    `StrictUndefined` instead of emitting a broken Dockerfile.
    """
    environment = jinja2.Environment(
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
        loader=jinja2.FileSystemLoader(str(template_path.parent)),
    )
    try:
        template = environment.get_template(template_path.name)
    except jinja2.TemplateNotFound as exc:
        raise ValueError(f"template not found: {template_path}") from exc
    defined_context = {
        name: value for name, value in context.items() if value is not None
    }
    return template.render(**defined_context)
