"""add_simulated_bet_unique_strategy

Hand-written: one paper bet per prediction and staking strategy. Keep in sync with SimulatedBet in
app/models.py.

Revision ID: c4e8a1d63f27
Revises: b7d41e9a2c85
Create Date: 2026-10-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4e8a1d63f27'
down_revision: Union[str, Sequence[str], None] = 'b7d41e9a2c85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('uq_simulated_bet_prediction_strategy', 'simulated_bet', ['prediction_id', 'strategy'],
                    unique=True)


def downgrade() -> None:
    op.drop_index('uq_simulated_bet_prediction_strategy', table_name='simulated_bet')
