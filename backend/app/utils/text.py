import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SPACES = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Lowercase, turn punctuation into spaces, and collapse whitespace."""
    spaced = _NON_ALNUM.sub(" ", value.lower())
    return _SPACES.sub(" ", spaced).strip()
