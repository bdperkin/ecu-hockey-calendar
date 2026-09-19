"""prune_superseded_synthetic_fixtures

Revision ID: 51749f8e2462
Revises: c5e2d1f9b3a7
Create Date: 2026-09-19 21:08:30.253550+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "51749f8e2462"  # pragma: allowlist secret
down_revision: str | None = "c5e2d1f9b3a7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = [
    "SUPERSEDED_SYNTHETIC_GAME_IDS",
    "branch_labels",
    "depends_on",
    "down_revision",
    "downgrade",
    "revision",
    "upgrade",
]

SUPERSEDED_SYNTHETIC_GAME_IDS: tuple[str, ...] = (
    "ecu-away-university-of-north-carolina-wilmington-20221002",
    "ecu-away-university-of-north-carolina-wilmington-20221022",
    "ecu-away-university-of-north-carolina-charlotte-20230924",
    "ecu-away-university-of-north-carolina-wilmington-20231028",
    "ecu-away-university-of-north-carolina-charlotte-20231104",
    "ecu-away-university-of-north-carolina-wilmington-20240907",
    "ecu-away-university-of-north-carolina-wilmington-20240908",
    "ecu-away-university-of-north-carolina-wilmington-20250920",
    "ecu-away-university-of-north-carolina-charlotte-20251019",
    "ecu-home-university-of-north-carolina-charlotte-20260124",
    "ecu-away-university-of-north-carolina-charlotte-20260920",
    "ecu-away-university-of-north-carolina-charlotte-20261010",
)


def upgrade() -> None:
    """Prune superseded synthetic duplicate fixtures."""
    games_table = sa.table("games", sa.column("game_id", sa.String))
    op.execute(
        games_table.delete().where(
            games_table.c.game_id.in_(SUPERSEDED_SYNTHETIC_GAME_IDS),
        ),
    )


def downgrade() -> None:
    """Revert schema modifications."""
