"""add referral random delay and duration

Revision ID: 002_add_referral_random_delay
Revises: 001_initial_schema
Create Date: 2026-10-13 16:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '002_add_referral_random_delay'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('referral_join_jobs', sa.Column('delay_min', sa.Integer(), server_default='30', nullable=False))
    op.add_column('referral_join_jobs', sa.Column('delay_max', sa.Integer(), server_default='90', nullable=False))
    op.add_column('referral_join_jobs', sa.Column('target_duration_minutes', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('referral_join_jobs', 'target_duration_minutes')
    op.drop_column('referral_join_jobs', 'delay_max')
    op.drop_column('referral_join_jobs', 'delay_min')
