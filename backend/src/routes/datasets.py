from ..constants.roles import Role
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from ..config.database import get_db
from ..controllers.dependencies import current_user, roles
from ..schemas.dataset import DatasetCreate, DatasetSummary
from ..services.dataset_service import (
    create_dataset, dataset_usage, get_dataset, list_datasets, list_imports, list_versions,
    observations, publish_import,
)

router = APIRouter(prefix="/datasets", dependencies=[Depends(current_user)], tags=["datasets"])


@router.get("", response_model=list[DatasetSummary])
def index(db: Session = Depends(get_db)):
    return list_datasets(db)


@router.post("", status_code=201)
def create(data: DatasetCreate, db: Session = Depends(get_db),
           user=Depends(roles(Role.ADMIN, Role.ANALYST))):
    return create_dataset(db, data.name, data.source, data.description, user)


@router.get("/{did}")
def show(did: int, db: Session = Depends(get_db)):
    return get_dataset(db, did)


@router.get("/{did}/versions")
def versions(did: int, db: Session = Depends(get_db)):
    return list_versions(db, did)


@router.get("/{did}/observations")
def preview(did: int, version: int | None = None, db: Session = Depends(get_db)):
    return observations(db, did, version)


@router.get("/{did}/imports")
def imports(did: int, db: Session = Depends(get_db)):
    return list_imports(db, did)


@router.get("/{did}/usage")
def usage(did: int, db: Session = Depends(get_db)):
    return dataset_usage(db, did)


@router.post(
    "/{did}/import",
    status_code=201,
    responses={
        200: {"description": "相同内容，未新增版本"},
        422: {"description": "校验失败，整批拒绝，返回行号与原因"},
    },
)
def upload(did: int, file: UploadFile = File(...),
           description: str = Form(default=""),
           db: Session = Depends(get_db),
           user=Depends(roles(Role.ADMIN, Role.ANALYST))):
    """Import a CSV and publish an immutable dataset version.

    Returns 201 when a version is published, 200 with status=duplicate when the
    same content already exists, 422 with line-level errors when rejected.
    """
    content = file.file.read()
    result = publish_import(db, did, file.filename or "upload.csv", content,
                            description, user)
    status = 201 if result["status"] == "published" else (
        200 if result["status"] == "duplicate" else 422)
    return JSONResponse(result, status_code=status)
