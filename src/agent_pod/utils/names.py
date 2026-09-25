"""Container naming utilities."""

import random

from agent_pod.types import AgentConfig

# Humanized session ids (ADR 005): adjective-noun pairs that are memorable, safe
# as session/container/ref names, and collision-free when minted against used ids.
_ADJECTIVES = [
    "amber",
    "brisk",
    "clean",
    "coral",
    "crisp",
    "dusky",
    "early",
    "frosted",
    "gentle",
    "glossy",
    "hearty",
    "ivory",
    "jazzy",
    "kind",
    "lively",
    "mellow",
    "nimble",
    "quiet",
    "rusty",
    "sage",
    "sunny",
    "velvet",
    "vivid",
    "warm",
]
_NOUNS = [
    "acorn",
    "alpine",
    "beacon",
    "cactus",
    "delta",
    "ember",
    "fern",
    "fox",
    "grove",
    "harbor",
    "isle",
    "jasper",
    "key",
    "lamp",
    "meadow",
    "nickel",
    "opal",
    "otter",
    "plume",
    "quill",
    "ridge",
    "serene",
    "timber",
    "willow",
]


def humanized_id(used: set[str] | None = None) -> str:
    """A memorable adjective-noun name (e.g. 'crisp-lamp'), unique against ``used``.

    Regenerates on collision; raises if the word lists are exhausted (practically
    never). Safe as a session name, podman container name, and git ref suffix.
    """
    taken = used or set()
    for _ in range(len(_ADJECTIVES) * len(_NOUNS)):
        name = f"{random.choice(_ADJECTIVES)}-{random.choice(_NOUNS)}"
        if name not in taken:
            return name
    raise RuntimeError("could not mint a unique session id")


def valid_session_name(name: str) -> bool:
    """Whether `name` is safe as a session name.

    Rejects path separators, dot segments, and whitespace, which could escape the
    agent state dir (or the podman container name) via `..` or an absolute path.
    """
    if not name or name in {".", ".."}:
        return False
    return "/" not in name and "\\" not in name and not any(c.isspace() for c in name)


def get_instance_name(config: AgentConfig, session: str) -> str:
    """Return the container name for an agent config and session."""
    base = config.container_name
    return base if session == "default" else f"{base}-{session}"
