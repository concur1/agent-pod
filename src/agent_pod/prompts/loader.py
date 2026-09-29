"""Load the ephemeral git-workflow skill from external files."""

from pathlib import Path

from agent_pod.types import STATE_DIR


def _bundled_prompt() -> Path:
    """Return the ephemeral git-workflow skill bundled with the package."""
    return Path(__file__).resolve().parent / "ephemeral-git-workflow.md"


def load_base_prompt() -> str:
    """Load the ephemeral git-workflow skill, preferring the bundled copy over the user's.

    Search order: the ephemeral-git-workflow.md bundled with the package, then
    ~/.config/container-agents/prompts/ephemeral-git-workflow.md (user config).

    Raises:
        FileNotFoundError: If the skill file cannot be found in any location.
    """
    bundled_prompt = _bundled_prompt()

    if bundled_prompt.exists():
        return bundled_prompt.read_text()

    user_prompt = Path.home() / STATE_DIR / "prompts" / "ephemeral-git-workflow.md"
    if user_prompt.exists():
        return user_prompt.read_text()

    raise FileNotFoundError(
        "Ephemeral git-workflow skill file not found. Expected at:\n"
        f"  - {bundled_prompt}\n"
        f"  - {user_prompt}\n\n"
        "Please ensure prompts/ephemeral-git-workflow.md exists in the package."
    )
