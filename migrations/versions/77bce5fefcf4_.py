"""Add more Datman config settings to the database.

Revision ID: 77bce5fefcf4
Revises: 5dc31b2f9fb4
Create Date: 2021-12-10 19:25:50.213883

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '77bce5fefcf4'
down_revision = '5dc31b2f9fb4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'scantypes',
        sa.Column('qc_type', sa.String(length=64), nullable=True)
    )
    op.add_column(
        'scantypes',
        sa.Column('pha_type', sa.String(length=64), nullable=True)
    )
    op.alter_column(
        'studies',
        'is_open',
        existing_type=sa.BOOLEAN(),
        nullable=False,
        existing_server_default=sa.text('true')
    )
    op.add_column(
        'study_sites',
        sa.Column('uses_tech_notes', sa.Boolean(), nullable=True)
    )

    # Reorganize existing data into 'ExpectedScans' table
    expected_scans = op.create_table(
        'expected_scans',
        sa.Column('study', sa.String(length=32), nullable=False),
        sa.Column('site', sa.String(length=32), nullable=False),
        sa.Column('scantype', sa.String(length=64), nullable=False),
        sa.Column(
            'num_expected', sa.Integer(), nullable=True, server_default='0'
        ),
        sa.Column(
            'pha_num_expected', sa.Integer(), nullable=True, server_default='0'
        ),
        sa.ForeignKeyConstraint(
            ['study'], ['studies.id'], name='expected_scans_study_fkey'
        ),
        sa.ForeignKeyConstraint(
            ['site'], ['sites.name'], name='expected_scans_site_fkey'
        ),
        sa.ForeignKeyConstraint(
            ['scantype'], ['scantypes.tag'],
            name='expected_scans_scantype_fkey'
        ),
        sa.ForeignKeyConstraint(
            ['study', 'site'],
            ['study_sites.study', 'study_sites.site'],
            name='expected_scans_allowed_sites_fkey'
        ),
        sa.PrimaryKeyConstraint('study', 'site', 'scantype')
    )

    conn = op.get_bind()
    records = conn.execute(text(
        'select study_sites.study, study_sites.site, study_scantypes.scantype '
        '  from study_sites, study_scantypes '
        '  where study_sites.study = study_scantypes.study;'
    ))
    op.bulk_insert(
        expected_scans,
        [{'study': record[0],
          'site': record[1],
          'scantype': record[2]}
         for record in records]
    )

    op.create_foreign_key(
        'gold_standards_expected_scans_fkey',
        'gold_standards',
        'expected_scans',
        ['study', 'site', 'scantype'],
        ['study', 'site', 'scantype'],
    )
    op.drop_constraint(
        'gold_standards_study_scantype_fkey', 'gold_standards',
        type_='foreignkey'
    )
    op.drop_table('study_scantypes')


def downgrade():
    op.drop_column('study_sites', 'uses_tech_notes')
    op.alter_column(
        'studies',
        'is_open',
        existing_type=sa.BOOLEAN(),
        nullable=True,
        existing_server_default=sa.text('true')
    )
    op.drop_column('scantypes', 'pha_type')
    op.drop_column('scantypes', 'qc_type')

    study_scantypes = op.create_table(
        'study_scantypes',
        sa.Column('study', sa.String(length=32), nullable=False),
        sa.Column('scantype', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ['scantype'],
            ['scantypes.tag'],
            name='study_scantypes_scantype_fkey'
        ),
        sa.ForeignKeyConstraint(
            ['study'],
            ['studies.id'],
            name='study_scantypes_study_fkey'
        ),
        sa.PrimaryKeyConstraint('study', 'scantype')
    )

    conn = op.get_bind()
    records = conn.execute(
        'select study, scantype'
        '  from expected_scans '
        '  group by study, scantype '
        '  order by study, scantype;'
    )
    op.bulk_insert(
        study_scantypes,
        [{'study': record[0],
          'scantype': record[1]}
         for record in records]
    )

    op.drop_constraint(
        'gold_standards_expected_scans_fkey',
        'gold_standards',
        type_='foreignkey'
    )
    op.create_foreign_key(
        'gold_standards_study_scantype_fkey',
        'gold_standards',
        'study_scantypes',
        ['study', 'scantype'],
        ['study', 'scantype']
    )
    op.drop_table('expected_scans')
