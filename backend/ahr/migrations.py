"""Versioned additive migration. Never discard existing investigation records."""
from sqlalchemy import inspect, text
from .db import Base, engine, now


ADDITIONS = {
    "images": {"provenance": "JSON DEFAULT '{}'"},
    "diseases": {"centerline": "JSON"},
    "records": {"clinical_data": "JSON DEFAULT '{}'", "evidence_ids": "JSON DEFAULT '[]'"},
    "cases": {"org": "VARCHAR", "record_id": "VARCHAR REFERENCES records(id)",
              "version": "INTEGER NOT NULL DEFAULT 1", "created_at": "VARCHAR", "updated_at": "VARCHAR"},
    "plans": {"evidence_snapshot": "JSON DEFAULT '[]'"},
}


def migrate():
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(20630235)"))
        for table, columns in ADDITIONS.items():
            current = {c["name"] for c in inspect(connection).get_columns(table)}
            for name, ddl in columns.items():
                if name not in current:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'))
        for version in ("ahr-1.1-evidence", "ahr-1.2-provenance"):
            connection.execute(text("INSERT INTO schema_migrations (version, applied_at) VALUES (:version, :date) ON CONFLICT (version) DO NOTHING"), {"version": version, "date": now()})
