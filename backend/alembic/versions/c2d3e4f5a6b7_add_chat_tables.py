"""add chat tables

Revision ID: c2d3e4f5a6b7
Revises: b1f2c3d4e5a6
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1f2c3d4e5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_session',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False, server_default='New chat'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'chat_message',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('gen_params', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('checkpoint_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='complete'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['chat_session.id'], name='fk_chat_message_session_id_chat_session'),
        sa.ForeignKeyConstraint(['checkpoint_id'], ['model_checkpoint.id'], name='fk_chat_message_checkpoint_id_model_checkpoint'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_chat_message_session_id', 'chat_message', ['session_id'])


def downgrade() -> None:
    op.drop_index('ix_chat_message_session_id', table_name='chat_message')
    op.drop_table('chat_message')
    op.drop_table('chat_session')
