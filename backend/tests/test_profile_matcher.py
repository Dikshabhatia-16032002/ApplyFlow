from decimal import Decimal
from uuid import uuid4

from app.seed import PROFILE_SEEDS, keywords_for
from app.services.profile_matcher import KeywordProfileMatcher, MatchProfile


def _seed_matcher(threshold: Decimal = Decimal("0.800")) -> KeywordProfileMatcher:
    profiles = [
        MatchProfile(uuid4(), name, 0, tuple(sorted(keywords_for(name, raw))))
        for name, raw in PROFILE_SEEDS
    ]
    return KeywordProfileMatcher(profiles, threshold)


def test_examples_from_the_matching_spec() -> None:
    matcher = _seed_matcher()

    genai = matcher.match("GenAI Engineer", "unused job description")
    assert genai.profile_name == "Applied AI Engineer"
    assert genai.confidence == Decimal("0.905")
    assert genai.method == "keyword"
    assert genai.needs_review is False

    learning = matcher.match("Machine Learning Engineer", None)
    assert learning.profile_name == "AI/ML Engineer"
    assert learning.confidence == Decimal("1.000")

    react = matcher.match("React Developer", None)
    assert react.profile_name == "Frontend Engineer"
    assert react.confidence == Decimal("1.000")

    engineer = matcher.match("Engineer", None)
    assert engineer.profile_id is None
    assert engineer.needs_review is True
    assert engineer.reason == "needs_review"
    assert engineer.method == "unmatched"


def test_phrase_match_does_not_split_a_word() -> None:
    profile_id = uuid4()
    matcher = KeywordProfileMatcher(
        [MatchProfile(profile_id, "Frontend Engineer", 0, ("react",))],
        Decimal("0.800"),
    )
    assert matcher.match("reactivity lead", None).profile_id is None
    hit = matcher.match("Senior React Lead", None)
    assert hit.profile_id == profile_id
    assert hit.confidence == Decimal("0.905")


def test_low_confidence_and_ties() -> None:
    react = MatchProfile(uuid4(), "Frontend Engineer", 0, ("react",))
    nodes = MatchProfile(uuid4(), "Backend Engineer", 0, ("nodes",))
    tied = KeywordProfileMatcher([react, nodes], Decimal("0.800"))
    ambiguous = tied.match("react nodes", None)
    assert ambiguous.reason == "ambiguous"
    assert ambiguous.profile_id is None

    backend = MatchProfile(uuid4(), "Backend Engineer", 5, ("nodes",))
    ranked = KeywordProfileMatcher([react, backend], Decimal("0.800"))
    winner = ranked.match("react nodes", None)
    assert winner.profile_name == "Backend Engineer"
    assert winner.method == "keyword"

    strict = KeywordProfileMatcher([react], Decimal("0.950"))
    assert strict.match("react lead", None).reason == "needs_review"
    assert strict.match("react", None).confidence == Decimal("1.000")
