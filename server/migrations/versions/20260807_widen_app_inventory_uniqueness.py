"""widen app_inventory uniqueness to include version and install_location (feature 037, FR-019)

Uniqueness was (agent_id, name). That de-duplicated repeated inventory reports
correctly — FR-018 — but it also collapsed two genuinely distinct installations
of the same application into a single row: two versions side by side, or the
same version installed both per-machine and per-user. FR-019 requires those to
stay distinguishable.

Widening a unique constraint cannot be violated by existing data: any row set
that satisfied (agent_id, name) also satisfies the wider key. So no data
migration or de-duplication pass is needed here.

install_location is nullable and PostgreSQL treats NULLs as distinct in a unique
constraint, which would let identical NULL-location rows repeat. Ingestion
normalises a missing location to NULL and de-duplicates in Python before insert
(server_api.inventory_dedup_key), so the batch never presents such repeats. The
constraint is the backstop, not the only guard.

Must stay in step with:
  - server_models.AppInventory.__table_args__
  - server_api.inventory_dedup_key()

Revision ID: 20260807_widen_app_inv_uniq
Revises: 20260807_create_tab_session
Create Date: 2026-08-07
"""
from alembic import op

revision = '20260807_widen_app_inv_uniq'
down_revision = '20260807_create_tab_session'
branch_labels = None
depends_on = None

OLD_NAME = 'uq_app_inventory_agent_name'
NEW_NAME = 'uq_app_inventory_agent_name_version_location'


def upgrade():
    # Guarded, in the style of the other app_inventory migrations in this repo.
    # The narrow constraint is not reliably named uq_app_inventory_agent_name: on
    # a database built by the consolidated bootstrap migration it may carry a
    # different name, or not exist at all. Dropping by name alone fails there
    # (UndefinedObject), which is what a fresh-database upgrade hit.
    #
    # So: drop ANY unique constraint whose columns are exactly (agent_id, name),
    # whatever it is called, then add the wide one only if it is not present.
    op.execute(
        f"""
        DO $$
        DECLARE
            con_name text;
        BEGIN
            FOR con_name IN
                SELECT c.conname
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'app_inventory'
                  AND c.contype = 'u'
                  AND (
                      -- attname is of type "name"; cast so the comparison is
                      -- text[] = text[] rather than name[] = text[].
                      SELECT array_agg(a.attname::text ORDER BY a.attname::text)
                      FROM unnest(c.conkey) k
                      JOIN pg_attribute a
                        ON a.attrelid = c.conrelid AND a.attnum = k
                  ) = ARRAY['agent_id', 'name']::text[]
            LOOP
                EXECUTE format(
                    'ALTER TABLE app_inventory DROP CONSTRAINT %I', con_name
                );
            END LOOP;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'app_inventory' AND c.conname = '{NEW_NAME}'
            ) THEN
                ALTER TABLE app_inventory
                    ADD CONSTRAINT {NEW_NAME}
                    UNIQUE (agent_id, name, version, install_location);
            END IF;
        END $$;
        """
    )


def downgrade():
    # Narrowing back CAN be violated by data inserted while the wider key was
    # active — two versions of one application on one agent is exactly what the
    # wider key permits. Collapse those to the most recently seen row first, or
    # the constraint cannot be recreated.
    op.execute(
        f"""
        DO $$
        BEGIN
            DELETE FROM app_inventory a
            USING app_inventory b
            WHERE a.agent_id = b.agent_id
              AND a.name = b.name
              AND a.id < b.id;

            ALTER TABLE app_inventory DROP CONSTRAINT IF EXISTS {NEW_NAME};

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'app_inventory' AND c.conname = '{OLD_NAME}'
            ) THEN
                ALTER TABLE app_inventory
                    ADD CONSTRAINT {OLD_NAME} UNIQUE (agent_id, name);
            END IF;
        END $$;
        """
    )
