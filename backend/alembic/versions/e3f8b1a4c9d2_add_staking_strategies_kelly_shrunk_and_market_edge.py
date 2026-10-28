"""add_staking_strategies_kelly_shrunk_and_market_edge

Hand-written: PostgreSQL only. Adds 'kelly_shrunk' and 'market_edge' to the
staking_strategy enum type outside a transaction block.

Keep in sync with StakingStrategy in app/models.py.

Downgrade note: PostgreSQL does not support removing values from an enum type
(ALTER TYPE ... DROP VALUE does not exist). The downgrade is a documented no-op.

Revision ID: e3f8b1a4c9d2
Revises: d7a2f5b81c39
Create Date: 2026-10-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e3f8b1a4c9d2'
down_revision: Union[str, Sequence[str], None] = 'd7a2f5b81c39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE staking_strategy ADD VALUE IF NOT EXISTS 'kelly_shrunk'")
        op.execute("ALTER TYPE staking_strategy ADD VALUE IF NOT EXISTS 'market_edge'")


def downgrade() -> None:
    # PostgreSQL cannot remove values from an existing enum type (no ALTER TYPE ... DROP VALUE).
    # Leaving existing values in place is safe and backwards compatible.
    pass
