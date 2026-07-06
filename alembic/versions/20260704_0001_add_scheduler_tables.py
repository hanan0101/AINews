"""Add production scheduler tables.

Revision ID: 20260704_0001
Revises: None
Create Date: 2026-07-04

Purpose:
    Adds scheduler state, checkpoints, in-app notifications, and system-wide
    key-value state for resilient newsletter runs.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260704_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("run_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("attempts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("run_type IN ('full', 'incremental', 'final')", name="ck_scheduled_runs_run_type"),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'partial')", name="ck_scheduled_runs_status"),
    )
    op.create_index(
        "ix_scheduled_runs_run_date_status",
        "scheduled_runs",
        ["run_date", "status"],
    )

    op.create_table(
        "run_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("scheduled_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_name", sa.String(length=100), nullable=False),
        sa.Column("step_status", sa.String(length=20), nullable=False),
        sa.Column("progress_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("step_status IN ('pending', 'running', 'completed', 'failed')", name="ck_run_checkpoints_step_status"),
    )
    op.create_index(
        "ix_run_checkpoints_run_id_step_name",
        "run_checkpoints",
        ["run_id", "step_name"],
    )

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="info"),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("related_url", sa.String(length=500), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("priority IN ('info', 'warning', 'urgent')", name="ck_notifications_priority"),
    )
    op.execute("CREATE INDEX ix_notifications_is_read_created_at ON notifications (is_read, created_at DESC)")

    op.create_table(
        "system_state",
        sa.Column("key", sa.String(length=100), primary_key=True, nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("system_state")
    op.drop_index("ix_notifications_is_read_created_at", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_run_checkpoints_run_id_step_name", table_name="run_checkpoints")
    op.drop_table("run_checkpoints")
    op.drop_index("ix_scheduled_runs_run_date_status", table_name="scheduled_runs")
    op.drop_table("scheduled_runs")
