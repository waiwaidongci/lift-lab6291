from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from ..models import Experiment, Dataset, DatasetVersion
from ..utils.serialize import record
from .audit_service import log


def _present(db, row):
    data = record(row)
    snapshot = db.get(DatasetVersion, row.dataset_version_id) if row.dataset_version_id else None
    data["dataset_version"] = snapshot.version if snapshot else None
    data["dataset_version_checksum"] = snapshot.checksum if snapshot else ""
    return data


def list_experiments(db):
    return [_present(db, x) for x in db.query(Experiment).order_by(Experiment.id.desc())]


def create_experiment(db, data, user):
    if not db.get(Dataset, data.dataset_id): raise HTTPException(404, "数据集不存在")
    query = db.query(DatasetVersion).filter_by(dataset_id=data.dataset_id)
    snapshot = (query.filter_by(version=data.version).first() if data.version
                else query.order_by(DatasetVersion.version.desc()).first())
    if not snapshot:
        raise HTTPException(409, "该数据集还没有已发布的观测版本，请先导入观测文件")
    if db.query(Experiment).filter_by(name=data.name).first():
        raise HTTPException(409, "实验名称已存在")
    row = Experiment(**data.model_dump(exclude={"version"}),
                     dataset_version_id=snapshot.id, owner=user.name)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "实验名称已存在")
    log(db, user.email, "experiment.create", f"{row.id}:v{snapshot.version}")
    db.commit()
    return _present(db, row)
