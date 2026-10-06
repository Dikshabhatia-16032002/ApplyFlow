"""Turn a role into a profile, resume, and template."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AppSettings, EmailTemplate, Profile, Resume
from app.services.profile_matcher import KeywordProfileMatcher, MatchProfile, MatchResult

_DEFAULT_THRESHOLD = Decimal("0.800")


@dataclass(frozen=True)
class ResolvedRow:
    profile_id: UUID | None
    profile_name: str
    confidence: Decimal | None
    method: str
    matched_keywords: tuple[str, ...]
    resume_id: UUID | None
    resume_name: str
    template_id: UUID | None
    template_name: str
    status: str
    reason: str | None


@dataclass
class MatchContext:
    matcher: KeywordProfileMatcher
    profiles: dict[UUID, Profile]
    resumes: dict[UUID, Resume]
    templates: dict[UUID, EmailTemplate]
    default_resume_id: UUID | None
    default_template_id: UUID | None


def load_match_context(session: Session) -> MatchContext:
    profiles = list(
        session.scalars(select(Profile).where(Profile.is_active.is_(True)).options(selectinload(Profile.keywords))).all()
    )
    resumes = list(session.scalars(select(Resume)).all())
    templates = list(session.scalars(select(EmailTemplate)).all())
    settings = session.get(AppSettings, 1)
    threshold = settings.match_confidence_threshold if settings is not None else _DEFAULT_THRESHOLD
    matcher = KeywordProfileMatcher(
        [
            MatchProfile(
                profile_id=profile.id,
                name=profile.name,
                priority=profile.priority,
                keywords=tuple(keyword.keyword for keyword in profile.keywords),
            )
            for profile in profiles
        ],
        threshold,
    )
    default_resume = next((row.id for row in resumes if row.is_active and row.is_default), None)
    default_template = next((row.id for row in templates if row.is_active and row.is_default), None)
    return MatchContext(
        matcher=matcher,
        profiles={profile.id: profile for profile in profiles},
        resumes={row.id: row for row in resumes},
        templates={row.id: row for row in templates},
        default_resume_id=default_resume,
        default_template_id=default_template,
    )


def match_role(context: MatchContext, role: str, job_description: str | None) -> ResolvedRow:
    return _from_result(context, context.matcher.match(role, job_description), resume_overridden=False, template_overridden=False)


def resolve_manual(
    context: MatchContext,
    profile_id: UUID,
    *,
    resume_overridden: bool,
    template_overridden: bool,
    resume_id: UUID | None,
    template_id: UUID | None,
) -> ResolvedRow:
    profile = context.profiles.get(profile_id)
    name = profile.name if profile is not None else ""
    result = MatchResult(
        profile_id=profile_id,
        profile_name=name or None,
        confidence=Decimal("1.000"),
        method="manual",
        matched_keywords=(),
        needs_review=False,
        reason=None,
    )
    return _from_result(
        context,
        result,
        resume_overridden=resume_overridden,
        template_overridden=template_overridden,
        resume_id=resume_id,
        template_id=template_id,
    )


def _from_result(
    context: MatchContext,
    result: MatchResult,
    *,
    resume_overridden: bool,
    template_overridden: bool,
    resume_id: UUID | None = None,
    template_id: UUID | None = None,
) -> ResolvedRow:
    if result.needs_review or result.profile_id is None:
        return ResolvedRow(
            profile_id=None,
            profile_name="",
            confidence=None,
            method="unmatched",
            matched_keywords=(),
            resume_id=None,
            resume_name="",
            template_id=None,
            template_name="",
            status="NEEDS_REVIEW",
            reason=result.reason or "needs_review",
        )

    profile = context.profiles.get(result.profile_id)
    if resume_overridden:
        resume = _active(context.resumes.get(resume_id) if resume_id is not None else None)
    else:
        preferred = profile.resume_id if profile is not None else None
        resume = _pick(context.resumes, preferred, context.default_resume_id)
    if template_overridden:
        template = _active(context.templates.get(template_id) if template_id is not None else None)
    else:
        preferred = profile.email_template_id if profile is not None else None
        template = _pick(context.templates, preferred, context.default_template_id)

    if resume is None:
        status, reason = "NEEDS_REVIEW", "missing_resume"
    elif template is None:
        status, reason = "NEEDS_REVIEW", "missing_template"
    else:
        status, reason = "PENDING", None

    return ResolvedRow(
        profile_id=result.profile_id,
        profile_name=result.profile_name or "",
        confidence=result.confidence,
        method=result.method,
        matched_keywords=result.matched_keywords,
        resume_id=resume.id if resume is not None else None,
        resume_name=resume.name if resume is not None else "",
        template_id=template.id if template is not None else None,
        template_name=template.name if template is not None else "",
        status=status,
        reason=reason,
    )


def _pick(rows: dict[UUID, Resume] | dict[UUID, EmailTemplate], preferred_id: UUID | None, default_id: UUID | None):
    if preferred_id is not None:
        chosen = _active(rows.get(preferred_id))
        if chosen is not None:
            return chosen
    if default_id is None:
        return None
    return _active(rows.get(default_id))


def _active(row: Resume | EmailTemplate | None) -> Resume | EmailTemplate | None:
    if row is None or not row.is_active:
        return None
    return row
