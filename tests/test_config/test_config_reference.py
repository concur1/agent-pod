"""The committed config reference doc must match what the models generate."""

from agent_pod.gen_config_docs import DOC_PATH, render_fields, splice


def test_config_reference_is_up_to_date() -> None:
    """Regenerating the doc from the models must not change the committed file."""
    doc = DOC_PATH.read_text()
    assert doc == splice(doc, render_fields())
