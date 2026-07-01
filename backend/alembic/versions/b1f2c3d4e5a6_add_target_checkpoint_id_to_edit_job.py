"""add target_checkpoint_id to edit_job

Revision ID: b1f2c3d4e5a6
Revises: a0acb9591546
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b1f2c3d4e5a6'
down_revision: Union[str, None] = 'a0acb9591546'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('edit_job', sa.Column('target_checkpoint_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_edit_job_target_checkpoint_id_model_checkpoint',
        'edit_job',
        'model_checkpoint',
        ['target_checkpoint_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_edit_job_target_checkpoint_id_model_checkpoint',
        'edit_job',
        type_='foreignkey',
    )
    op.drop_column('edit_job', 'target_checkpoint_id')
