"""add_shadow_model_role

Hand-written: PostgreSQL only. Adds 'shadow' to the model_version role check constraint (ck_model_version_role).

Keep in sync with MODEL_ROLES in app/models.py.

Downgrade note: Downgrade first verifies that no model_version rows with role='shadow'
exist. If any exist, it raises a clear error without deleting data. If none exist,
it restores the 4-role check constraint.

Revision ID: b3d5f7a9c1e4
Revises: a2c4e6f8b1d3
Create Date: 2026-10-28 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d5f7a9c1e4'
down_revision: Union[str, Sequence[str], None] = 'a2c4e6f8b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLES_5 = ('champion', 'challenger', 'retired', 'benchmark', 'shadow')
ROLES_4 = ('champion', 'challenger', 'retired', 'benchmark')


def _in_list(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.drop_constraint('ck_model_version_role', 'model_version', type_='check')
    op.create_check_constraint('ck_model_version_role', 'model_version', _in_list('role', ROLES_5))


def downgrade() -> None:
    conn = op.get_bind()
    count = conn.execute(sa.text("SELECT count(*) FROM model_version WHERE role = 'shadow'")).scalar()
    if count and count > 0:
        raise RuntimeError(f"Cannot downgrade: {count} model_version row(s) with role='shadow' exist.")
    op.drop_constraint('ck_model_version_role', 'model_version', type_='check')
    op.create_check_constraint('ck_model_version_role', 'model_version', _in_list('role', ROLES_4))
