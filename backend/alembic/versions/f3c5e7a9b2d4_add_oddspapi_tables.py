"""add_oddspapi_tables

Hand-written (D-70). Keep in sync with OddsPapiRequest, OddsPapiFixture, OddsPapiQuote and the capture kinds in
app/models.py.

Adds:
- 'closing_oddspapi' to ck_odds_snapshot_capture_kind and to the per-game unique index of closing markers.
- oddspapi_request: ledger of every OddsPapi request (monthly budget across runs).
- oddspapi_fixture: OddsPapi NBA fixtures and their mapping to `game` / `nba_game_id`, path status and ETag.
- oddspapi_quote: main-line pre-match quotes of fixtures without a `game` row (seasons before the live pipeline).

Revision ID: f3c5e7a9b2d4
Revises: e9b1d3f5a7c2
Create Date: 2026-11-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3c5e7a9b2d4'
down_revision: Union[str, Sequence[str], None] = 'e9b1d3f5a7c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MARKET_TYPES = (
    'h2h', 'spreads', 'totals', 'player_points', 'player_rebounds', 'player_assists', 'player_pra'
)
BET_SIDES = ('home', 'away', 'over', 'under')
OLD_KINDS = "kind IN ('opening', 'closing', 'closing_props', 'sgo_daily')"
NEW_KINDS = "kind IN ('opening', 'closing', 'closing_props', 'sgo_daily', 'closing_oddspapi')"
OLD_UNIQUE = "kind IN ('closing', 'closing_props')"
NEW_UNIQUE = "kind IN ('closing', 'closing_props', 'closing_oddspapi')"


def _enum(name: str, values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name=name, create_type=False)


def upgrade() -> None:
    op.drop_constraint('ck_odds_snapshot_capture_kind', 'odds_snapshot_capture', type_='check')
    op.create_check_constraint('ck_odds_snapshot_capture_kind', 'odds_snapshot_capture', NEW_KINDS)
    op.drop_index('uq_odds_snapshot_capture_closing', table_name='odds_snapshot_capture',
                  postgresql_where=sa.text(OLD_UNIQUE))
    op.create_index('uq_odds_snapshot_capture_closing', 'odds_snapshot_capture', ['game_id', 'kind'],
                    unique=True, postgresql_where=sa.text(NEW_UNIQUE))

    op.create_table(
        'oddspapi_request',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('billable', sa.Boolean(), nullable=False),
        sa.Column('status_code', sa.SmallInteger(), nullable=True),
        sa.Column('fixture_id', sa.Text(), nullable=True),
        sa.Column('label', sa.Text(), nullable=True),
        sa.Column('response_bytes', sa.Integer(), nullable=True),
        sa.Column('vendor_request_count', sa.Integer(), nullable=True),
        sa.Column('vendor_request_limit', sa.Integer(), nullable=True),
        sa.Column('source', sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_oddspapi_request_requested_at', 'oddspapi_request', ['requested_at'], unique=False)

    op.create_table(
        'oddspapi_fixture',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('fixture_id', sa.Text(), nullable=False),
        sa.Column('tournament_id', sa.Integer(), nullable=False),
        sa.Column('status_id', sa.SmallInteger(), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('true_start_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('home_name', sa.Text(), nullable=False),
        sa.Column('away_name', sa.Text(), nullable=False),
        sa.Column('home_team_id', sa.Integer(), nullable=True),
        sa.Column('away_team_id', sa.Integer(), nullable=True),
        sa.Column('game_id', sa.BigInteger(), nullable=True),
        sa.Column('nba_game_id', sa.Text(), nullable=True),
        sa.Column('unmatched_reason', sa.Text(), nullable=True),
        sa.Column('listed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('path_status', sa.Text(), nullable=True),
        sa.Column('path_fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('path_etag', sa.Text(), nullable=True),
        sa.Column('path_bookmakers', sa.Text(), nullable=True),
        sa.Column('prematch_entries', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('quotes_stored', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.ForeignKeyConstraint(['home_team_id'], ['team.id']),
        sa.ForeignKeyConstraint(['away_team_id'], ['team.id']),
        sa.ForeignKeyConstraint(['game_id'], ['game.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fixture_id', name='uq_oddspapi_fixture_fixture_id'),
        sa.CheckConstraint(
            "path_status IN ('stored', 'no_prematch', 'not_found', 'error') OR path_status IS NULL",
            name='ck_oddspapi_fixture_path_status',
        ),
    )
    op.create_index('ix_oddspapi_fixture_start_time', 'oddspapi_fixture', ['start_time'], unique=False)
    op.create_index('ix_oddspapi_fixture_game_id', 'oddspapi_fixture', ['game_id'], unique=False)

    op.create_table(
        'oddspapi_quote',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('fixture_row_id', sa.BigInteger(), nullable=False),
        sa.Column('bookmaker', sa.Text(), nullable=False),
        sa.Column('market', _enum('market_type', MARKET_TYPES), nullable=False),
        sa.Column('side', _enum('bet_side', BET_SIDES), nullable=False),
        sa.Column('line', sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column('price_decimal', sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['fixture_row_id'], ['oddspapi_fixture.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fixture_row_id', 'bookmaker', 'market', 'side', 'line', 'created_at',
                            name='uq_oddspapi_quote', postgresql_nulls_not_distinct=True),
        sa.CheckConstraint('price_decimal > 1', name='ck_oddspapi_quote_price'),
    )
    op.create_index('ix_oddspapi_quote_fixture', 'oddspapi_quote',
                    ['fixture_row_id', 'bookmaker', 'market', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_oddspapi_quote_fixture', table_name='oddspapi_quote')
    op.drop_table('oddspapi_quote')
    op.drop_index('ix_oddspapi_fixture_game_id', table_name='oddspapi_fixture')
    op.drop_index('ix_oddspapi_fixture_start_time', table_name='oddspapi_fixture')
    op.drop_table('oddspapi_fixture')
    op.drop_index('ix_oddspapi_request_requested_at', table_name='oddspapi_request')
    op.drop_table('oddspapi_request')

    # A closing_oddspapi marker would violate the old constraint: remove them first (their quotes stay in
    # odds_history under op_pinnacle and can be re-marked after a re-upgrade).
    op.execute("DELETE FROM odds_snapshot_capture WHERE kind = 'closing_oddspapi'")
    op.drop_index('uq_odds_snapshot_capture_closing', table_name='odds_snapshot_capture',
                  postgresql_where=sa.text(NEW_UNIQUE))
    op.create_index('uq_odds_snapshot_capture_closing', 'odds_snapshot_capture', ['game_id', 'kind'],
                    unique=True, postgresql_where=sa.text(OLD_UNIQUE))
    op.drop_constraint('ck_odds_snapshot_capture_kind', 'odds_snapshot_capture', type_='check')
    op.create_check_constraint('ck_odds_snapshot_capture_kind', 'odds_snapshot_capture', OLD_KINDS)
