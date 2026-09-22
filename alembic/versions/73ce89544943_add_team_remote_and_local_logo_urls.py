"""add_team_remote_and_local_logo_urls

Revision ID: 73ce89544943
Revises: 51749f8e2462
Create Date: 2026-09-22 14:13:14.539620+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "73ce89544943"  # pragma: allowlist secret
down_revision: str | None = "51749f8e2462"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = [
    "branch_labels",
    "depends_on",
    "down_revision",
    "downgrade",
    "revision",
    "upgrade",
]


def upgrade() -> None:
    """Apply schema modifications adding team remote and local logo URLs."""
    with op.batch_alter_table("teams", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("remote_logo_url", sa.String(length=512), nullable=True),
        )
        batch_op.add_column(
            sa.Column("local_logo_url", sa.String(length=512), nullable=True),
        )


def downgrade() -> None:
    """Revert schema modifications removing team remote and local logo URLs."""
    with op.batch_alter_table("teams", schema=None) as batch_op:
        batch_op.drop_column("local_logo_url")
        batch_op.drop_column("remote_logo_url")
