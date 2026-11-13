from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from ..models import Dataset, DatasetVersion, Observation, DatasetImport, Experiment
from ..utils.serialize import record
from .audit_service import log
from .dataset_import_service import parse_csv


def _version_or_latest(db, dataset_id, version=None):
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(404, "数据集不存在")
    query = db.query(DatasetVersion).filter_by(dataset_id=dataset_id)
    row = query.filter_by(version=version).first() if version else query.order_by(DatasetVersion.version.desc()).first()
    if not row:
        raise HTTPException(404, "数据集还没有已发布的版本" if version is None else f"数据集版本 v{version} 不存在")
    return dataset, row


def _summary(db, dataset):
    versions = (db.query(DatasetVersion)
                .filter_by(dataset_id=dataset.id)
                .order_by(DatasetVersion.version.desc()).all())
    latest = versions[0] if versions else None
    return {
        **record(dataset),
        "checksum": latest.checksum if latest else dataset.checksum,
        "source": latest.source if latest else dataset.source,
        "description": latest.description if latest else dataset.description,
        "observations": (db.query(Observation)
                         .filter_by(dataset_version_id=latest.id).count()) if latest else 0,
        "versions": len(versions),
        "latest_version": latest.version if latest else 0,
        "latest_version_id": latest.id if latest else None,
    }


def list_datasets(db):
    return [_summary(db, d) for d in db.query(Dataset).order_by(Dataset.id)]


def get_dataset(db, dataset_id):
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(404, "数据集不存在")
    return _summary(db, dataset)


def list_versions(db, dataset_id):
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(404, "数据集不存在")
    return [record(v) for v in db.query(DatasetVersion)
            .filter_by(dataset_id=dataset_id)
            .order_by(DatasetVersion.version.desc())]


def observations(db, dataset_id, version=None):
    _, snapshot = _version_or_latest(db, dataset_id, version)
    rows = (db.query(Observation)
            .filter_by(dataset_version_id=snapshot.id)
            .order_by(Observation.id).limit(100))
    return [record(x) for x in rows]


def list_imports(db, dataset_id):
    if not db.get(Dataset, dataset_id):
        raise HTTPException(404, "数据集不存在")
    return [record(x) for x in db.query(DatasetImport)
            .filter_by(dataset_id=dataset_id)
            .order_by(DatasetImport.id.desc()).limit(50)]


def create_dataset(db, name, source, description, user):
    name = (name or "").strip()
    source = (source or "").strip()
    if len(name) < 2:
        raise HTTPException(422, "数据集名称至少 2 个字符")
    if db.query(Dataset).filter_by(name=name).first():
        raise HTTPException(409, "数据集名称已存在")
    row = Dataset(name=name, source=source, description=description or "", checksum="")
    db.add(row)
    db.flush()
    log(db, user.email, "dataset.create", row.id)
    db.commit()
    return _summary(db, row)


def _result(status, snapshot, entry, message, errors=None):
    return {
        "status": status,
        "version": record(snapshot) if snapshot else None,
        "import_id": entry.id,
        "message": message,
        "filename": entry.filename,
        "rows_received": entry.rows_received,
        "rows_unique": entry.rows_unique,
        "duplicates_removed": entry.duplicates_removed,
        "errors": errors or [],
    }


def publish_import(db, dataset_id, filename, content, description, user, source=None):
    """Validate an uploaded CSV and publish it as a new immutable version.

    Re-importing identical content (same subjects/values, any line order) does
    not create a version; it is recorded as a duplicate import instead.
    """
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(404, "数据集不存在")

    try:
        batch, checksum = parse_csv(content)
    except ValueError as error:
        entry = DatasetImport(dataset_id=dataset_id, status="rejected", filename=filename,
                              errors=[{"line": 1, "subject": "", "reason": str(error)}],
                              reason=str(error), actor=user.email)
        db.add(entry)
        db.flush()
        log(db, user.email, "dataset.import.rejected", f"{dataset_id}:{filename}")
        db.commit()
        return _result("rejected", None, entry, str(error), entry.errors)

    if batch.errors:
        reason = "观测文件校验失败，整批未导入"
        entry = DatasetImport(
            dataset_id=dataset_id, status="rejected", filename=filename,
            checksum=checksum, rows_received=batch.row_count,
            rows_unique=len(batch.rows), duplicates_removed=batch.duplicate_count,
            errors=batch.errors, reason=reason, actor=user.email)
        db.add(entry)
        db.flush()
        log(db, user.email, "dataset.import.rejected", f"{dataset_id}:{filename}")
        db.commit()
        return _result("rejected", None, entry,
                       reason + "：" + batch.errors[0]["reason"], batch.errors)

    existing = (db.query(DatasetVersion)
                .filter_by(dataset_id=dataset_id, checksum=checksum).first())
    if existing:
        entry = DatasetImport(
            dataset_id=dataset_id, version_id=existing.id, status="duplicate",
            filename=filename, checksum=checksum, rows_received=batch.row_count,
            rows_unique=len(batch.rows), duplicates_removed=batch.duplicate_count,
            reason=f"内容与已发布 v{existing.version} 相同，未新增版本",
            actor=user.email)
        db.add(entry)
        db.flush()
        log(db, user.email, "dataset.import.duplicate", f"{dataset_id}:v{existing.version}")
        db.commit()
        return _result("duplicate", existing, entry,
                       f"内容与 v{existing.version} 相同（忽略行序），未新增版本")

    latest_version = (db.query(func.max(DatasetVersion.version))
                      .filter(DatasetVersion.dataset_id == dataset_id).scalar() or 0)
    snapshot = DatasetVersion(
        dataset_id=dataset_id,
        version=latest_version + 1,
        checksum=checksum,
        source=source or dataset.source or filename,
        description=description or dataset.description or "",
        rows_received=batch.row_count,
        rows_unique=len(batch.rows),
        duplicates_removed=batch.duplicate_count,
        created_by=user.email,
    )
    db.add(snapshot)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "并发导入导致版本冲突，请重试")

    db.add_all([
        Observation(dataset_id=dataset_id, dataset_version_id=snapshot.id, **row)
        for row in batch.rows
    ])
    entry = DatasetImport(
        dataset_id=dataset_id, version_id=snapshot.id, status="published",
        filename=filename, checksum=checksum, rows_received=batch.row_count,
        rows_unique=len(batch.rows), duplicates_removed=batch.duplicate_count,
        reason=f"已发布 v{snapshot.version}", actor=user.email)
    db.add(entry)
    if not dataset.checksum:
        # Keep the legacy summary fields pointing at the first publication.
        dataset.checksum = checksum
        dataset.source = snapshot.source
    log(db, user.email, "dataset.publish", f"{dataset_id}:v{snapshot.version}")
    db.commit()
    return _result("published", snapshot, entry,
                   f"已发布 v{snapshot.version}：{len(batch.rows)} 条唯一观测"
                   + (f"，合并 {batch.duplicate_count} 条重复" if batch.duplicate_count else ""))


def dataset_usage(db, dataset_id):
    rows = (db.query(Experiment)
            .filter_by(dataset_id=dataset_id)
            .order_by(Experiment.id).all())
    versions = {v.id: v.version for v in db.query(DatasetVersion).filter_by(dataset_id=dataset_id)}
    return [{**record(e), "version": versions.get(e.dataset_version_id)} for e in rows]
