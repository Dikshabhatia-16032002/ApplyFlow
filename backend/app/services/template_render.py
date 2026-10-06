import re
from dataclasses import dataclass

KNOWN_VARIABLES = ("name", "company", "role", "location", "mobile", "linkedin_url")
_TOKEN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


@dataclass(frozen=True)
class RenderedMessage:
    subject: str
    body: str
    empty_variables: list[str]
    unknown_tokens: list[str]


def render_message(subject: str, body: str, fields: dict[str, str | None]) -> RenderedMessage:
    """Replace known variables. Unknown tokens stay in the text."""
    empty: list[str] = []
    unknown: list[str] = []
    seen_empty: set[str] = set()
    seen_unknown: set[str] = set()
    known = set(KNOWN_VARIABLES)

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in known:
            if token not in seen_unknown:
                seen_unknown.add(token)
                unknown.append(token)
            return match.group(0)
        raw = fields.get(token)
        value = "" if raw is None else raw.strip()
        if value == "":
            if token not in seen_empty:
                seen_empty.add(token)
                empty.append(token)
            return ""
        return value

    return RenderedMessage(
        subject=_TOKEN.sub(replace, subject),
        body=_TOKEN.sub(replace, body),
        empty_variables=empty,
        unknown_tokens=unknown,
    )
