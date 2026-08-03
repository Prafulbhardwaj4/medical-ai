"""merge heads: MLC chain-of-custody branch + visit fee/OT charge branch"""
from alembic import op
import sqlalchemy as sa

revision = '267f1483d160'
down_revision = ('053ea2d31ded', 'a9b0c1d2e3f4')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass