"""add_model_roles_and_per_model_elo

Hand-written: PostgreSQL only. Introduces the champion/challenger registry and per-model Elo state:

* model_version gets a role (champion / challenger / retired) with at most one champion, promotion and
  retirement timestamps, a parent link and free notes. The existing elo_538 1.1 row becomes the champion.
* model_evaluation is the audit trail of every champion-vs-challenger evaluation.
* team_elo_rating gets model_version_id: the existing rows (one rating line, the champion's) are assigned to
  elo_538 1.1 and the unique key becomes (model_version_id, team_id, season_id, game_id).

Keep in sync with ModelVersion, ModelEvaluation and TeamEloRating in app/models.py.

Downgrade note: the old schema holds a single rating line per team, so the downgrade first deletes every
team_elo_rating row that does not belong to elo_538 1.1 (or, without that row, to the champion); model
predictions and evaluations of other models are untouched or dropped with their table respectively.

Revision ID: d7a2f5b81c39
Revises: c4e8a1d63f27
Create Date: 2026-10-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd7a2f5b81c39'
down_revision: Union[str, Sequence[str], None] = 'c4e8a1d63f27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLES = ('champion', 'challenger', 'retired')
DECISIONS = ('insufficient_data', 'keep', 'promote', 'retire', 'rollback', 'proposal', 'dry_run')

_LEGACY_MODEL = "SELECT id FROM model_version WHERE name = 'elo_538' AND version = '1.1'"


def _in_list(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    # --- model_version: roles --------------------------------------------------------------------
    op.add_column('model_version', sa.Column('role', sa.Text(), server_default=sa.text("'challenger'"), nullable=False))
    op.add_column('model_version', sa.Column('promoted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('model_version', sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('model_version', sa.Column('parent_id', sa.Integer(), nullable=True))
    op.add_column('model_version', sa.Column('notes', sa.Text(), nullable=True))
    op.create_foreign_key('fk_model_version_parent', 'model_version', 'model_version', ['parent_id'], ['id'])
    op.create_check_constraint('ck_model_version_role', 'model_version', _in_list('role', ROLES))

    # A database that has rating rows but never registered the model would fail the NOT NULL below: register it.
    op.execute(f"""
        INSERT INTO model_version (name, version, params)
        SELECT 'elo_538', '1.1', '{{}}'::jsonb
        WHERE NOT EXISTS ({_LEGACY_MODEL}) AND EXISTS (SELECT 1 FROM team_elo_rating)
    """)
    op.execute("""
        UPDATE model_version
        SET role = 'champion', promoted_at = COALESCE(trained_at, now())
        WHERE name = 'elo_538' AND version = '1.1'
    """)
    op.create_index('uq_model_version_single_champion', 'model_version', ['role'], unique=True,
                    postgresql_where=sa.text("role = 'champion'"))

    # --- model_evaluation ------------------------------------------------------------------------
    op.create_table('model_evaluation',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('evaluated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('champion_id', sa.Integer(), nullable=False),
    sa.Column('challenger_id', sa.Integer(), nullable=False),
    sa.Column('n_games', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('n_market_games', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('decision', sa.Text(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['champion_id'], ['model_version.id'], ),
    sa.ForeignKeyConstraint(['challenger_id'], ['model_version.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.CheckConstraint(_in_list('decision', DECISIONS), name='ck_model_evaluation_decision')
    )
    op.create_index('ix_model_evaluation_challenger', 'model_evaluation', ['challenger_id', 'evaluated_at'], unique=False)

    # --- team_elo_rating: one rating line per model ------------------------------------------------
    op.add_column('team_elo_rating', sa.Column('model_version_id', sa.Integer(), nullable=True))
    op.execute(f"UPDATE team_elo_rating SET model_version_id = ({_LEGACY_MODEL})")
    op.alter_column('team_elo_rating', 'model_version_id', nullable=False)
    op.create_foreign_key('fk_team_elo_rating_model_version', 'team_elo_rating', 'model_version',
                          ['model_version_id'], ['id'])
    op.drop_constraint('uq_team_season_game_elo', 'team_elo_rating', type_='unique')
    op.create_unique_constraint('uq_model_team_season_game_elo', 'team_elo_rating',
                                ['model_version_id', 'team_id', 'season_id', 'game_id'])


def downgrade() -> None:
    # The old schema has a single rating line: keep the legacy model's rows (else the champion's).
    op.execute(f"""
        DELETE FROM team_elo_rating
        WHERE model_version_id IS DISTINCT FROM
              COALESCE(({_LEGACY_MODEL}), (SELECT id FROM model_version WHERE role = 'champion'))
    """)
    op.drop_constraint('uq_model_team_season_game_elo', 'team_elo_rating', type_='unique')
    op.drop_constraint('fk_team_elo_rating_model_version', 'team_elo_rating', type_='foreignkey')
    op.drop_column('team_elo_rating', 'model_version_id')
    op.create_unique_constraint('uq_team_season_game_elo', 'team_elo_rating', ['team_id', 'season_id', 'game_id'])

    op.drop_index('ix_model_evaluation_challenger', table_name='model_evaluation')
    op.drop_table('model_evaluation')

    op.drop_index('uq_model_version_single_champion', table_name='model_version',
                  postgresql_where=sa.text("role = 'champion'"))
    op.drop_constraint('ck_model_version_role', 'model_version', type_='check')
    op.drop_constraint('fk_model_version_parent', 'model_version', type_='foreignkey')
    for column in ('notes', 'parent_id', 'retired_at', 'promoted_at', 'role'):
        op.drop_column('model_version', column)
