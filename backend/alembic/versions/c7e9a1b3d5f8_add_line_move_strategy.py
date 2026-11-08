"""add_line_move_strategy

Hand-written (D-71): PostgreSQL only. Adds 'line_move' to the staking_strategy enum type (outside a transaction
block) and two nullable simulated_bet columns set only for 'line_move' bets, so every bet stays attributable:
predicted_move (the predicted close-minus-current move in points) and pinnacle_price_at_bet (Pinnacle's own decimal
price of the side when the bet was placed).

Keep in sync with StakingStrategy and SimulatedBet in app/models.py.

Chain note: this revision follows a4d6f8b0c3e5 (injury_backfill_slot, branch fix/injury-backfill-v2), which is
merged to main first.

Downgrade note: PostgreSQL cannot drop an enum value, so 'line_move' stays (harmless). The columns are dropped;
downgrading while 'line_move' bets exist is the operator's call (delete or keep them first).

Revision ID: c7e9a1b3d5f8
Revises: a4d6f8b0c3e5
Create Date: 2026-11-07 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c7e9a1b3d5f8'
down_revision: Union[str, Sequence[str], None] = 'a4d6f8b0c3e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE staking_strategy ADD VALUE IF NOT EXISTS 'line_move'")
    op.add_column('simulated_bet', sa.Column('predicted_move', sa.Numeric(5, 2), nullable=True))
    op.add_column('simulated_bet', sa.Column('pinnacle_price_at_bet', sa.Numeric(8, 4), nullable=True))


def downgrade() -> None:
    # The enum value cannot be removed from PostgreSQL's enum type; it is left in place (harmless).
    op.drop_column('simulated_bet', 'pinnacle_price_at_bet')
    op.drop_column('simulated_bet', 'predicted_move')
