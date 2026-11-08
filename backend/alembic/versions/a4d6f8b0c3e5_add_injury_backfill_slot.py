"""add_injury_backfill_slot

Hand-written (D-69). Keep in sync with InjuryBackfillSlot and INJURY_BACKFILL_OUTCOMES in app/models.py.

Adds:
- injury_backfill_slot: ledger of historical injury report backfill attempts, one row per game date and
  slot with the latest outcome (stored / missing / parse_failed / http_error), the URL tried, the layout
  header of a parse failure and attempt timestamps, so resumed runs skip slots known to be missing or
  unparseable.

Revision ID: a4d6f8b0c3e5
Revises: f3c5e7a9b2d4
Create Date: 2026-11-07 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4d6f8b0c3e5'
down_revision: Union[str, Sequence[str], None] = 'f3c5e7a9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OUTCOMES = "outcome IN ('stored', 'missing', 'parse_failed', 'http_error')"


def upgrade() -> None:
    op.create_table(
        'injury_backfill_slot',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('game_date', sa.Date(), nullable=False),
        sa.Column('slot', sa.Text(), nullable=False),
        sa.Column('outcome', sa.Text(), nullable=False),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('urls_tried', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('http_status', sa.SmallInteger(), nullable=True),
        sa.Column('layout_header', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('snapshot_id', sa.BigInteger(), nullable=True),
        sa.Column('attempts', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('first_attempted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_attempted_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['snapshot_id'], ['injury_report_snapshot.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_date', 'slot', name='uq_injury_backfill_slot'),
        sa.CheckConstraint(OUTCOMES, name='ck_injury_backfill_slot_outcome'),
    )
    op.create_index('ix_injury_backfill_slot_outcome', 'injury_backfill_slot', ['outcome'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_injury_backfill_slot_outcome', table_name='injury_backfill_slot')
    op.drop_table('injury_backfill_slot')
