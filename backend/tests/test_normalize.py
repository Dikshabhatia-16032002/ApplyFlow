from app.seed import PROFILE_SEEDS, keywords_for
from app.utils.text import normalize_text


def test_normalize_text_collapses_punctuation_and_case() -> None:
    assert normalize_text("  AI/ML Engineer ") == "ai ml engineer"
    assert normalize_text("Full-Stack") == "full stack"
    assert normalize_text("front-end") == "front end"


def test_seed_keywords_do_not_overlap_across_profiles() -> None:
    seen: dict[str, str] = {}
    for name, raw_keywords in PROFILE_SEEDS:
        for keyword in keywords_for(name, raw_keywords):
            assert keyword not in seen, f"{keyword} is on both {seen.get(keyword)} and {name}"
            seen[keyword] = name
