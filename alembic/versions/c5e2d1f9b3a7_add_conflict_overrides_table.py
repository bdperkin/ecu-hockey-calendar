"""add_conflict_overrides_table

Revision ID: c5e2d1f9b3a7
Revises: 37631a1998f7
Create Date: 2026-09-19 02:40:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5e2d1f9b3a7"  # pragma: allowlist secret
down_revision: str | None = "37631a1998f7"  # pragma: allowlist secret
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
    """Apply schema modifications."""
    op.create_table(
        "conflict_overrides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conflict_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_game_id", sa.String(length=128), nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("override_value", sa.String(length=512), nullable=False),
        sa.Column("accepted_source", sa.String(length=64), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), nullable=False),
        sa.Column("notes", sa.String(length=512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conflict_overrides")),
    )
    with op.batch_alter_table("conflict_overrides", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_conflict_overrides_conflict_id"),
            ["conflict_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_conflict_overrides_canonical_game_id"),
            ["canonical_game_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_conflict_overrides_field_name"),
            ["field_name"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_conflict_overrides_is_active"),
            ["is_active"],
            unique=False,
        )


def downgrade() -> None:
    """Revert schema modifications."""
    with op.batch_alter_table("conflict_overrides", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_conflict_overrides_is_active"))
        batch_op.drop_index(batch_op.f("ix_conflict_overrides_field_name"))
        batch_op.drop_index(batch_op.f("ix_conflict_overrides_canonical_game_id"))
        batch_op.drop_index(batch_op.f("ix_conflict_overrides_conflict_id"))

    op.drop_table("conflict_overrides")
