"""add_game_changes_table

Revision ID: 37631a1998f7
Revises: 77bff60de574
Create Date: 2026-09-08 04:11:44.979158+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "37631a1998f7"  # pragma: allowlist secret
down_revision: str | None = "77bff60de574"  # pragma: allowlist secret
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
        "game_changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sync_cycle_id", sa.String(length=64), nullable=False),
        sa.Column("sync_audit_id", sa.Integer(), nullable=True),
        sa.Column("canonical_game_id", sa.String(length=128), nullable=False),
        sa.Column("change_type", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("field_diffs", sa.JSON(), nullable=True),
        sa.Column("snapshot_before", sa.JSON(), nullable=True),
        sa.Column("snapshot_after", sa.JSON(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["sync_audit_id"],
            ["sync_audits.id"],
            name=op.f("fk_game_changes_sync_audit_id_sync_audits"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_game_changes")),
    )
    with op.batch_alter_table("game_changes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_game_changes_canonical_game_id"),
            ["canonical_game_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_game_changes_change_type"),
            ["change_type"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_game_changes_recorded_at"),
            ["recorded_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_game_changes_sync_audit_id"),
            ["sync_audit_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_game_changes_sync_cycle_id"),
            ["sync_cycle_id"],
            unique=False,
        )


def downgrade() -> None:
    """Revert schema modifications."""
    with op.batch_alter_table("game_changes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_game_changes_sync_cycle_id"))
        batch_op.drop_index(batch_op.f("ix_game_changes_sync_audit_id"))
        batch_op.drop_index(batch_op.f("ix_game_changes_recorded_at"))
        batch_op.drop_index(batch_op.f("ix_game_changes_change_type"))
        batch_op.drop_index(batch_op.f("ix_game_changes_canonical_game_id"))

    op.drop_table("game_changes")
