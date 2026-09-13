"""SQLAlchemy Declarative Base and metadata configuration.

This module defines the shared DeclarativeBase class and naming conventions
for database constraints and indexes across all persistent storage models.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Define explicit naming convention for database constraints to support
# predictable Alembic migrations across SQLite and PostgreSQL engines.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

METADATA: MetaData = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base class for all persistent SQLAlchemy ORM models."""

    metadata = METADATA


__all__ = [
    "METADATA",
    "NAMING_CONVENTION",
    "Base",
]
