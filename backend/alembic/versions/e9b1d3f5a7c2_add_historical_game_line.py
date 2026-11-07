"""add_historical_game_line

Hand-written: creates historical_game_line (pre-game lines from free historical archives).
Keep in sync with HistoricalGameLine in app/models.py.

Revision ID: e9b1d3f5a7c2
Revises: a8c2e4f6b0d1
Create Date: 2026-11-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9b1d3f5a7c2'
down_revision: Union[str, Sequence[str], None] = 'a8c2e4f6b0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'historical_game_line',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('source_row_key', sa.Text(), nullable=False),
        sa.Column('season_label', sa.Text(), nullable=False),
        sa.Column('game_date', sa.Date(), nullable=False),
        sa.Column('home_team_id', sa.Integer(), nullable=False),
        sa.Column('away_team_id', sa.Integer(), nullable=False),
        sa.Column('neutral_site', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('game_id', sa.BigInteger(), nullable=True),
        sa.Column('nba_game_id', sa.Text(), nullable=True),
        sa.Column('open_spread_home', sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column('close_spread_home', sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column('open_total', sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column('close_total', sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column('open_moneyline_home', sa.Integer(), nullable=True),
        sa.Column('open_moneyline_away', sa.Integer(), nullable=True),
        sa.Column('close_moneyline_home', sa.Integer(), nullable=True),
        sa.Column('close_moneyline_away', sa.Integer(), nullable=True),
        sa.Column('home_score', sa.SmallInteger(), nullable=True),
        sa.Column('away_score', sa.SmallInteger(), nullable=True),
        sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['home_team_id'], ['team.id']),
        sa.ForeignKeyConstraint(['away_team_id'], ['team.id']),
        sa.ForeignKeyConstraint(['game_id'], ['game.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'source',
            'game_date',
            'home_team_id',
            'away_team_id',
            name='uq_historical_game_line_source_date_teams',
        ),
        sa.CheckConstraint(
            'home_team_id <> away_team_id',
            name='ck_historical_game_line_distinct_teams',
        ),
        sa.CheckConstraint(
            'close_moneyline_home IS NULL OR close_moneyline_home <= -100 OR close_moneyline_home >= 100',
            name='ck_historical_game_line_close_ml_home',
        ),
        sa.CheckConstraint(
            'close_moneyline_away IS NULL OR close_moneyline_away <= -100 OR close_moneyline_away >= 100',
            name='ck_historical_game_line_close_ml_away',
        ),
    )
    op.create_index(
        'ix_historical_game_line_game_date',
        'historical_game_line',
        ['game_date'],
        unique=False,
    )
    op.create_index(
        'ix_historical_game_line_season_label',
        'historical_game_line',
        ['season_label'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_historical_game_line_season_label', table_name='historical_game_line')
    op.drop_index('ix_historical_game_line_game_date', table_name='historical_game_line')
    op.drop_table('historical_game_line')
