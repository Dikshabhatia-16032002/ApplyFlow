from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_db)]


def pagination(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> tuple[int, int]:
    return limit, offset


Pagination = Annotated[tuple[int, int], Depends(pagination)]
