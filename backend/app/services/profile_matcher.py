"""Keyword matching. The job description is accepted and ignored."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.utils.text import normalize_text

_EXACT = Decimal("1.000")
_PHRASE = Decimal("0.900")
_THOUSAND = Decimal(1000)


@dataclass(frozen=True)
class MatchProfile:
    profile_id: UUID
    name: str
    priority: int
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class MatchResult:
    profile_id: UUID | None
    profile_name: str | None
    confidence: Decimal | None
    method: str
    matched_keywords: tuple[str, ...]
    needs_review: bool
    reason: str | None


class ProfileMatcher(Protocol):
    def match(self, role: str, job_description: str | None) -> MatchResult: ...


class KeywordProfileMatcher:
    def __init__(self, profiles: Sequence[MatchProfile], threshold: Decimal) -> None:
        self._profiles = list(profiles)
        self._threshold = threshold

    def match(self, role: str, job_description: str | None) -> MatchResult:
        del job_description
        normalized = normalize_text(role)
        if not normalized:
            return _review("needs_review")

        scored: list[tuple[MatchProfile, Decimal, tuple[str, ...]]] = []
        for profile in self._profiles:
            best: Decimal | None = None
            keywords: list[str] = []
            for keyword in profile.keywords:
                score = _score(keyword, normalized)
                if score is None:
                    continue
                if best is None or score > best:
                    best = score
                    keywords = [keyword]
                elif score == best:
                    keywords.append(keyword)
            if best is not None:
                scored.append((profile, best, tuple(sorted(keywords))))

        if not scored:
            return _review("needs_review")

        best_score = max(item[1] for item in scored)
        if best_score < self._threshold:
            return _review("needs_review")

        leaders = [item for item in scored if item[1] == best_score]
        top_priority = max(item[0].priority for item in leaders)
        winners = [item for item in leaders if item[0].priority == top_priority]
        if len(winners) > 1:
            return _review("ambiguous")

        profile, confidence, keywords = winners[0]
        return MatchResult(
            profile_id=profile.profile_id,
            profile_name=profile.name,
            confidence=confidence,
            method="keyword",
            matched_keywords=keywords,
            needs_review=False,
            reason=None,
        )


def _score(keyword: str, role: str) -> Decimal | None:
    if not keyword:
        return None
    if keyword == role:
        return _EXACT
    if f" {keyword} " in f" {role} ":
        bonus = Decimal(min(len(keyword), 40)) / _THOUSAND
        return (_PHRASE + bonus).quantize(Decimal("0.001"))
    return None


def _review(reason: str) -> MatchResult:
    return MatchResult(
        profile_id=None,
        profile_name=None,
        confidence=None,
        method="unmatched",
        matched_keywords=(),
        needs_review=True,
        reason=reason,
    )
