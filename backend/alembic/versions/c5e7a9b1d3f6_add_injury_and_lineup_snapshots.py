"""add_injury_and_lineup_snapshots

Hand-written: creates injury_report_snapshot, injury_entry, and lineup_snapshot.
Keep in sync with models.py (InjuryReportSnapshot, InjuryEntry, LineupSnapshot).

Revision ID: c5e7a9b1d3f6
Revises: b3d5f7a9c1e4
Create Date: 2026-10-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c5e7a9b1d3f6'
down_revision: Union[str, Sequence[str], None] = 'b3d5f7a9c1e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # 1. injury_report_snapshot
    op.create_table(
        'injury_report_snapshot',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('source', sa.Text(), nullable=False, server_default=sa.text("'nba_official_pdf'")),
        sa.Column('report_url', sa.Text(), nullable=False),
        sa.Column('report_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('sha256', sa.Text(), nullable=False),
        sa.Column('entries_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sha256', name='uq_injury_report_snapshot_sha256'),
    )
    op.create_index(
        'ix_injury_report_snapshot_report_timestamp',
        'injury_report_snapshot',
        ['report_timestamp'],
        unique=False,
    )

    # 2. injury_entry
    op.create_table(
        'injury_entry',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('snapshot_id', sa.BigInteger(), nullable=False),
        sa.Column('game_date', sa.Text(), nullable=False),
        sa.Column('game_time_et', sa.Text(), nullable=True),
        sa.Column('matchup', sa.Text(), nullable=True),
        sa.Column('team_name', sa.Text(), nullable=True),
        sa.Column('player_name_raw', sa.Text(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('availability_prob', sa.Numeric(precision=3, scale=2), nullable=True),
        sa.ForeignKeyConstraint(['snapshot_id'], ['injury_report_snapshot.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['player_id'], ['player.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_injury_entry_snapshot_id', 'injury_entry', ['snapshot_id'], unique=False)
    op.create_index('ix_injury_entry_player_id', 'injury_entry', ['player_id'], unique=False)

    # 3. lineup_snapshot
    op.create_table(
        'lineup_snapshot',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('game_id', sa.BigInteger(), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('minutes_to_tipoff', sa.Numeric(precision=6, scale=1), nullable=True),
        sa.Column('side', sa.Text(), nullable=False),
        sa.Column('starters_count', sa.SmallInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('not_playing_count', sa.SmallInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('payload', _JSON, nullable=False),
        sa.ForeignKeyConstraint(['game_id'], ['game.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('game_id', 'captured_at', 'side', name='uq_lineup_snapshot_game_captured_side'),
        sa.CheckConstraint("side IN ('home', 'away')", name='ck_lineup_snapshot_side'),
    )
    op.create_index('ix_lineup_snapshot_game_id', 'lineup_snapshot', ['game_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_lineup_snapshot_game_id', table_name='lineup_snapshot')
    op.drop_table('lineup_snapshot')
    op.drop_index('ix_injury_entry_player_id', table_name='injury_entry')
    op.drop_index('ix_injury_entry_snapshot_id', table_name='injury_entry')
    op.drop_table('injury_entry')
    op.drop_index('ix_injury_report_snapshot_report_timestamp', table_name='injury_report_snapshot')
    op.drop_table('injury_report_snapshot')
