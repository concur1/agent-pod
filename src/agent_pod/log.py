"""Logging for agent-pod: warnings/errors to stderr, DEBUG detail under ``-v``.

The single ``agent_pod`` logger is pre-wired to stderr so warnings render with the
CLI's existing ``Warning:``/``Error:`` prefix whether called through ``ap`` or as a
library. ``configure_logging`` only switches the level (DEBUG under ``-v``).
"""

import logging
import sys

_PREFIXES = {
    logging.INFO: "Info",
    logging.WARNING: "Warning",
    logging.ERROR: "Error",
    logging.CRITICAL: "Error",
}


class _StderrHandler(logging.Handler):
    """Write one formatted line to the *current* sys.stderr on every emit.

    Resolving stderr per-emit (instead of holding ``sys.stderr`` at construction)
    keeps the handler in step with ``capsys``-style redirects in tests.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(_CliFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


class _CliFormatter(logging.Formatter):
    """One clean line per record, keeping the CLI's established ``Prefix:`` style,
    with the traceback appended when present (under ``-v``)."""

    def format(self, record: logging.LogRecord) -> str:
        prefix = _PREFIXES.get(record.levelno, record.levelname)
        line = f"{prefix}: {record.getMessage()}"
        if record.exc_info:
            line += "\n" + (record.exc_text or self.formatException(record.exc_info))
        return line


logger = logging.getLogger("agent_pod")
logger.addHandler(_StderrHandler())
logger.setLevel(logging.WARNING)
logger.propagate = False


def configure_logging(verbose: bool = False) -> None:
    """Set the level: DEBUG with ``-v``, else WARNING (errors on stderr only)."""
    logger.setLevel(logging.DEBUG if verbose else logging.WARNING)
