"""The committed config reference doc must match what the models generate."""

from agent_pod.gen_config_docs import DOC_PATH, GROUPS, render_fields, splice


def test_config_reference_is_up_to_date() -> None:
    """Regenerating the doc from the models must not change the committed file."""
    doc = DOC_PATH.read_text()
    assert doc == splice(doc, render_fields())


def test_field_examples_validate_against_their_models() -> None:
    """Every field example must be a valid value for its model.

    Required sibling fields (e.g. FileMount's `name`/`permissions`) are filled
    with their own first example so the candidate config validates.
    """
    for _, _, model in GROUPS:
        for name, field in model.model_fields.items():
            required_siblings = {
                req: model.model_fields[req].examples[0]
                for req, sibling in model.model_fields.items()
                if sibling.is_required() and req != name
            }
            for example in field.examples:
                model.model_validate({**required_siblings, name: example})
