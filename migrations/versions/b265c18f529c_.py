"""Add a guest user for devel installations.

Revision ID: b265c18f529c
Revises: b68a8193acad
Create Date: 2022-06-07 22:12:45.049536

"""
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'b265c18f529c'
down_revision = '4ab18b9516c9'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(text(
        "INSERT INTO users(id, first_name, last_name) values "
        "(-1, 'Guest', 'Guest')"
    ))


def downgrade():
    conn = op.get_bind()
    conn.execute("DELETE FROM users where id = -1")
