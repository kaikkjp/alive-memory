"""Input sanitization — strip ANSI escapes and control characters."""

import re

# ANSI escape sequences: CSI (ESC[ or 0x9b), OSC (ESC] ... BEL or ST)
# CSI full spec: prefix (ESC[ or 0x9b), optional private param (? > !),
# parameter bytes (0-9 ; :), intermediate bytes (space-/), final byte (@-~)
_ANSI_RE = re.compile(
    r'\x1b\[[?>=!]?[0-9;:]*[ -/]*[@-~]'   # CSI via ESC (full spec)
    r'|\x9b[?>=!]?[0-9;:]*[ -/]*[@-~]'    # CSI via C1 control (U+009B)
    r'|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)' # OSC: ESC] ... BEL or ST
)

# Control characters (except newline \n and tab \t), including C1 range
_CTRL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')


def sanitize_input(text: str) -> str:
    """Strip ANSI escapes and control characters from visitor input."""
    if not text:
        return text
    text = _ANSI_RE.sub('', text)
    text = _CTRL_RE.sub('', text)
    return text.strip()
