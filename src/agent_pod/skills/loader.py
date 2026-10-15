"""Load bundled skills from external files."""

from pathlib import Path

from agent_pod.types import STATE_DIR


def load_skill(skill_name: str) -> str:
    """Load a bundled skill, preferring the bundled copy over the user's.

    Search order: `<skill_name>/SKILL.md` bundled with the package, then
    `~/.config/container-agents/prompts/<skill_name>.md` (user config).

    Raises:
        FileNotFoundError: If the skill file cannot be found in any location.
    """
    bundled_prompt = Path(__file__).resolve().parent / skill_name / "SKILL.md"

    if bundled_prompt.exists():
        return bundled_prompt.read_text()

    user_prompt = Path.home() / STATE_DIR / "prompts" / f"{skill_name}.md"
    if user_prompt.exists():
        return user_prompt.read_text()

    raise FileNotFoundError(
        f"Skill file for '{skill_name}' not found. Expected at:\n"
        f"  - {bundled_prompt}\n"
        f"  - {user_prompt}\n\n"
        f"Please ensure skills/{skill_name}/SKILL.md exists in the package."
    )
