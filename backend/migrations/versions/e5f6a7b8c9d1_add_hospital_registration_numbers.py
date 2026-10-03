"""hospitals.clinical_establishment_reg_no / drug_licence_no"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d1'
down_revision = 'd4e5f6a7b8c0'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('hospitals')}
    if 'clinical_establishment_reg_no' not in cols:
        op.add_column('hospitals', sa.Column('clinical_establishment_reg_no', sa.String(), nullable=True))
    if 'drug_licence_no' not in cols:
        op.add_column('hospitals', sa.Column('drug_licence_no', sa.String(), nullable=True))


def downgrade():
    op.drop_column('hospitals', 'drug_licence_no')
    op.drop_column('hospitals', 'clinical_establishment_reg_no')