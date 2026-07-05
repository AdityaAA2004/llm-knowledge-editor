"""add incident table

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-07-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS incident_number_seq START WITH 1000")

    op.create_table(
        'incident',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('number', sa.String(length=20), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='OPEN'),
        sa.Column('matched_api_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('matched_endpoint_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('route_to_team', sa.String(length=255), nullable=True),
        sa.Column('assigned_member', sa.String(length=255), nullable=True),
        sa.Column('request_body', sa.Text(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('stack_trace', sa.Text(), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('edit_job_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['matched_api_id'], ['api.id'], name='fk_incident_matched_api_id_api'),
        sa.ForeignKeyConstraint(['matched_endpoint_id'], ['endpoint.id'], name='fk_incident_matched_endpoint_id_endpoint'),
        sa.ForeignKeyConstraint(['edit_job_id'], ['edit_job.id'], name='fk_incident_edit_job_id_edit_job'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('number', name='uq_incident_number'),
        sa.UniqueConstraint('external_id', name='uq_incident_external_id'),
    )


def downgrade() -> None:
    op.drop_table('incident')
    op.execute("DROP SEQUENCE IF EXISTS incident_number_seq")
