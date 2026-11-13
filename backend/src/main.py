import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text, inspect
from .config.database import Base,engine
from .config.settings import SEED_DEMO
from . import models
from .routes import auth,datasets,experiments,runs,decisions,audits
from .middlewares.errors import ErrorMiddleware
from .middlewares.rate_limit import RateLimitMiddleware
from .services.run_service import queue

_UPGRADES = {
    "datasets": ["created_at"],
    "observations": ["dataset_version_id"],
    "experiments": ["dataset_version_id"],
    "analysis_runs": ["dataset_version_id"],
}


def _ensure_columns():
    """Additive upgrade for pre-existing demo databases (no destructive ops)."""
    existing_tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for table, columns in _UPGRADES.items():
            if table not in existing_tables:
                continue
            present = {c["name"] for c in inspect(engine).get_columns(table)}
            for column in columns:
                if column in present:
                    continue
                if column == "created_at":
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN created_at VARCHAR NOT NULL DEFAULT ''"
                    ))
                elif column == "dataset_version_id":
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN dataset_version_id INTEGER "
                        "REFERENCES dataset_versions(id)"
                    ))


def _ensure_constraints():
    """Replace the pre-versioning (dataset_id, subject) uniqueness with per-version.

    Old demo databases enforced one row per subject for the whole dataset, which
    would block publishing a second version with the same subjects.
    """
    inspector = inspect(engine)
    if engine.dialect.name != "postgresql":
        return
    if "observations" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        for constraint in inspector.get_unique_constraints("observations"):
            if constraint.get("column_names") == ["dataset_id", "subject"]:
                conn.execute(text(
                    f'ALTER TABLE observations DROP CONSTRAINT "{constraint["name"]}"'
                ))
                logging.info("dropped legacy observation constraint %s", constraint["name"])
        existing = {index["name"] for index in inspector.get_indexes("observations")}
        if "observations_version_subject_key" not in existing:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS observations_version_subject_key "
                "ON observations (dataset_version_id, subject)"
            ))


def _backfill_versions():
    """Wrap legacy flat observations into a v1 snapshot for old deployments."""
    from .config.database import SessionLocal
    from .models import Dataset, DatasetVersion, Observation
    from .services.dataset_import_service import canonical_checksum
    with SessionLocal() as db:
        for dataset in db.query(Dataset).all():
            if db.query(DatasetVersion).filter_by(dataset_id=dataset.id).first():
                continue
            orphans = db.query(Observation).filter(
                Observation.dataset_id == dataset.id,
                Observation.dataset_version_id.is_(None)).all()
            if not orphans:
                continue
            rows = [dict(subject=o.subject, arm=o.arm, pre_value=o.pre_value, value=o.value)
                    for o in orphans]
            checksum = dataset.checksum or canonical_checksum(rows)
            snapshot = DatasetVersion(dataset_id=dataset.id, version=1, checksum=checksum,
                                      source=dataset.source, description=dataset.description,
                                      rows_received=len(rows), rows_unique=len(rows),
                                      created_by="migration")
            db.add(snapshot); db.flush()
            for row in orphans:
                row.dataset_version_id = snapshot.id
            dataset.checksum = checksum
        db.commit()


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    try:
        _ensure_columns()
        _ensure_constraints()
        _backfill_versions()
    except Exception:
        logging.exception("schema upgrade failed")
    if SEED_DEMO:
        try:
            from scripts.seed_demo import seed
            seed()
        except Exception: logging.exception("demo seed failed")
    yield
app=FastAPI(title="岚桥实验放量台",lifespan=lifespan)
app.add_middleware(ErrorMiddleware)
app.add_middleware(RateLimitMiddleware)
for route in [auth,datasets,experiments,runs,decisions,audits]: app.include_router(route.router)
@app.get("/health")
def health():
    with engine.connect() as conn: conn.execute(text("select 1"))
    queue.ping()
    return {"status":"healthy","service":"lift-lab"}
