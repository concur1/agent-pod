"""Generate the config reference section of ``docs/reference/config.md``.

Introspects the Pydantic config models in ``agent_pod.types`` and renders every
field (key, type, default, description) into the generated block of the
reference doc, so the docs can't drift from the validator.

Run with ``uv run python -m agent_pod.gen_config_docs`` (or ``make docs-ref``).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from agent_pod.types import FileMount, FlakeOverrides, PassthroughEnv, UserConfig

MARKER_START = "<!-- generated:config-keys:start -->"
MARKER_END = "<!-- generated:config-keys:end -->"
DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "reference" / "config.md"

# The user-editable models, in doc order: top-level/profile keys, then the
# nested `files` and `flake` objects they reference.
GROUPS: list[tuple[str, str, type[BaseModel]]] = [
    (
        "Top-level config and profiles",
        "The top level of a config file accepts every key below; all but "
        "`profile`/`profiles` are also valid inside a `profiles.<name>` entry.",
        UserConfig,
    ),
    ("`files` entries", "Each entry of the `files` list.", FileMount),
    (
        "`passthrough_envs` entries",
        "Each entry of the `passthrough_envs` list; every forwarded variable "
        "needs a description so the generated agent instructions can say what "
        "it grants.",
        PassthroughEnv,
    ),
    ("`flake` entries", "`flake` overrides the agent's flake config.", FlakeOverrides),
]


def render_type(annotation: Any) -> str:
    """Render a Python annotation as a compact YAML-ish type string."""
    if isinstance(annotation, str):
        return annotation
    if annotation is type(None):
        return "null"
    if annotation is str:
        return "str"
    if annotation is bool:
        return "bool"
    origin = get_origin(annotation)
    if origin is None:
        return getattr(annotation, "__name__", str(annotation))
    args = get_args(annotation)
    if origin in (Union, UnionType):
        return " | ".join(render_type(a) for a in args)
    if origin is Literal:
        return " | ".join(f"{a}" for a in args)
    if origin in (list, tuple, set):
        return f"{origin.__name__}[{render_type(args[0])}]"
    if origin is dict:
        return f"dict[{render_type(args[0])}, {render_type(args[1])}]"
    return str(annotation)


def render_default(field: FieldInfo) -> str:
    """Render a field's default as YAML-ish text, or an empty string if required."""
    if field.is_required():
        return ""
    return json.dumps(field.get_default(call_default_factory=True), sort_keys=True)


def render_table(model: type[BaseModel]) -> str:
    """Render one model's fields as a markdown table.

    A compact Key/Type/Default/Description reference (the invariant column set
    helm-docs uses); readable examples live in the hand-written annotated
    YAML section further down, not crammed into table cells.
    """
    rows = ["| Key | Type | Default | Description |", "|---|---|---|---|"]
    for name, field in model.model_fields.items():
        default = render_default(field) or "—"
        column_type = render_type(field.annotation).replace("|", "\\|")
        description = field.description or ""
        description = " ".join(description.split()).replace("|", "\\|")
        rows.append(f"| `{name}` | `{column_type}` | `{default}` | {description} |")
    return "\n".join(rows)


def render_fields() -> str:
    """Render the complete generated section (heading, groups, tables)."""
    lines = [
        "## Config keys",
        "",
        "Every key you can set, generated from the Pydantic config models so the "
        "reference can't drift from the validator.",
    ]
    for title, note, model in GROUPS:
        lines += ["", f"### {title}", "", note, "", render_table(model)]
    return "\n".join(lines) + "\n"


def splice(doc: str, section: str) -> str:
    """Replace the generated block in `doc` (between the markers) with `section`."""
    start = doc.index(MARKER_START)
    end = doc.index(MARKER_END) + len(MARKER_END)
    return doc[:start] + f"{MARKER_START}\n{section}{MARKER_END}" + doc[end:]


def main() -> None:
    """Regenerate the generated block of the config reference doc in place."""
    doc = DOC_PATH.read_text()
    DOC_PATH.write_text(splice(doc, render_fields()))


if __name__ == "__main__":
    main()
