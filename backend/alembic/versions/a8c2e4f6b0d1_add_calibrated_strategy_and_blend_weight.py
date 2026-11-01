"""add_calibrated_strategy_and_blend_weight

Hand-written: PostgreSQL only. Adds 'calibrated' to the staking_strategy enum type (outside a transaction block)
and the nullable simulated_bet.blend_weight column (the fitted weight of the model in the logit blend, set only
for 'calibrated' bets so every bet stays attributable).

Keep in sync with StakingStrategy and SimulatedBet in app/models.py.

Downgrade note: PostgreSQL does not support removing values from an enum type (ALTER TYPE ... DROP VALUE does not
exist), so the enum value stays. The column is dropped; downgrading while 'calibrated' bets exist is the operator's
call (delete or keep them first).

Revision ID: a8c2e4f6b0d1
Revises: d6f8b0c2e4a7
Create Date: 2026-11-01 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a8c2e4f6b0d1'
down_revision: Union[str, Sequence[str], None] = 'd6f8b0c2e4a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE staking_strategy ADD VALUE IF NOT EXISTS 'calibrated'")
    op.add_column('simulated_bet', sa.Column('blend_weight', sa.Numeric(4, 3), nullable=True))


def downgrade() -> None:
    # The enum value cannot be removed from PostgreSQL's enum type; it is left in place (harmless).
    op.drop_column('simulated_bet', 'blend_weight')
