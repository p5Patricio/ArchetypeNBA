"""add_sgo_daily_capture_and_market_consensus

Revision ID: d6f8b0c2e4a7
Revises: c5e7a9b1d3f6
Create Date: 2026-10-31 17:00:00.000000

Adds:
- 'sgo_daily' to ck_odds_snapshot_capture_kind check constraint.
- table market_consensus_snapshot for SportsGameOdds consensus quotes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6f8b0c2e4a7'
down_revision: Union[str, Sequence[str], None] = 'c5e7a9b1d3f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MARKET_TYPES = (
    'h2h', 'spreads', 'totals', 'player_points', 'player_rebounds', 'player_assists', 'player_pra'
)
BET_SIDES = ('home', 'away', 'over', 'under')


def _enum(name: str, values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name=name, create_type=False)


def upgrade() -> None:
    # 1. Update check constraint on odds_snapshot_capture.kind to allow 'sgo_daily'
    op.drop_constraint('ck_odds_snapshot_capture_kind', 'odds_snapshot_capture', type_='check')
    op.create_check_constraint(
        'ck_odds_snapshot_capture_kind',
        'odds_snapshot_capture',
        "kind IN ('opening', 'closing', 'closing_props', 'sgo_daily')",
    )

    # 2. Create market_consensus_snapshot table
    op.create_table(
        'market_consensus_snapshot',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('game_id', sa.BigInteger(), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('source', sa.Text(), server_default=sa.text("'sgo_fair'"), nullable=False),
        sa.Column('market', _enum('market_type', MARKET_TYPES), nullable=False),
        sa.Column('side', _enum('bet_side', BET_SIDES), nullable=False),
        sa.Column('line', sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column('fair_price_american', sa.Integer(), nullable=False),
        sa.Column('book_price_american', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['game_id'], ['game.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "fair_price_american <= -100 OR fair_price_american >= 100",
            name='ck_market_consensus_fair_price',
        ),
        sa.CheckConstraint(
            "book_price_american IS NULL OR book_price_american <= -100 OR book_price_american >= 100",
            name='ck_market_consensus_book_price',
        ),
    )
    op.create_index('ix_market_consensus_game_id', 'market_consensus_snapshot', ['game_id'], unique=False)
    op.create_index(
        'ix_market_consensus_lookup',
        'market_consensus_snapshot',
        ['game_id', 'market', 'side', 'captured_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_market_consensus_lookup', table_name='market_consensus_snapshot')
    op.drop_index('ix_market_consensus_game_id', table_name='market_consensus_snapshot')
    op.drop_table('market_consensus_snapshot')

    op.drop_constraint('ck_odds_snapshot_capture_kind', 'odds_snapshot_capture', type_='check')
    op.create_check_constraint(
        'ck_odds_snapshot_capture_kind',
        'odds_snapshot_capture',
        "kind IN ('opening', 'closing', 'closing_props')",
    )
