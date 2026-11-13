"""End-to-end HTTP tests: multipart upload, duplicate/conflict handling, versions."""
import os
os.environ["SEED_DEMO"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.config.database import Base, get_db
from src import models  # noqa: F401
from src.main import app
from src.utils.security import hash_password


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    # Seed users through a session bound to the test engine.
    with Session() as db:
        for role in ("admin", "analyst", "viewer"):
            db.add(models.User(email=f"{role}@lanqiao.demo", name=role, role=role,
                               password_hash=hash_password("pw123456")))
        db.commit()

    def override():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override

    # enqueue talks to Redis; replace with a recorder so the API test is offline.
    from src.routes import runs as runs_route
    monkeypatch.setattr(runs_route, "enqueue", lambda db, eid, user: {
        "id": 1, "experiment_id": eid, "status": "queued", "result": {}, "error": "",
        "created_at": "", "dataset_version_id": 1, "dataset_version": 1,
        "dataset_version_checksum": "", "experiment_name": "",
    }, raising=True)

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def login(client, role="analyst"):
    response = client.post("/auth/login",
                           json={"email": f"{role}@lanqiao.demo", "password": "pw123456"})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def make_dataset(client, headers):
    response = client.post("/datasets", headers=headers, json={
        "name": "导入测试集", "source": "ui.csv", "description": "从页面导入"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client, headers, dataset_id, content, filename="obs.csv"):
    return client.post(f"/datasets/{dataset_id}/import", headers=headers,
                       files={"file": (filename, content, "text/csv")},
                       data={"description": "页面导入 v"})


CSV = (b"subject,arm,pre_value,value\n"
       b"U-1,control,10,20\n"
       b"U-2,treatment,11,21\n"
       b"U-3,control,12,22\n")


def test_upload_publishes_version(client):
    headers = login(client, "admin")
    dataset_id = make_dataset(client, headers)
    response = upload(client, headers, dataset_id, CSV)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "published"
    assert body["version"]["version"] == 1
    versions = client.get(f"/datasets/{dataset_id}/versions", headers=headers).json()
    assert [v["version"] for v in versions] == [1]
    preview = client.get(f"/datasets/{dataset_id}/observations",
                         headers=headers).json()
    assert len(preview) == 3


def test_duplicate_upload_returns_200_and_no_new_version(client):
    headers = login(client, "admin")
    dataset_id = make_dataset(client, headers)
    upload(client, headers, dataset_id, CSV)
    response = upload(client, headers, dataset_id, CSV)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "duplicate"
    assert len(client.get(f"/datasets/{dataset_id}/versions", headers=headers).json()) == 1
    summary = client.get(f"/datasets/{dataset_id}", headers=headers).json()
    assert summary["versions"] == 1


def test_shuffled_upload_is_recognised_as_duplicate(client):
    headers = login(client, "admin")
    dataset_id = make_dataset(client, headers)
    upload(client, headers, dataset_id, CSV)
    shuffled = (b"subject,arm,pre_value,value\n"
                b"U-3,control,12,22\n"
                b"U-1,control,10,20\n"
                b"U-2,treatment,11,21\n")
    response = upload(client, headers, dataset_id, shuffled)
    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"
    assert len(client.get(f"/datasets/{dataset_id}/versions", headers=headers).json()) == 1


def test_conflict_returns_422_with_line_numbers_and_no_version(client):
    headers = login(client, "admin")
    dataset_id = make_dataset(client, headers)
    conflicting = (b"subject,arm,pre_value,value\n"
                   b"U-1,control,10,20\n"
                   b"U-2,treatment,11,21\n"
                   b"U-1,control,10,20\n"
                   b"U-2,treatment,11,99\n")   # conflict on file line 5
    response = upload(client, headers, dataset_id, conflicting)
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["status"] == "rejected"
    assert 5 in {error["line"] for error in body["errors"]}
    assert "不一致" in body["errors"][0]["reason"]
    assert client.get(f"/datasets/{dataset_id}/versions", headers=headers).json() == []
    journal = client.get(f"/datasets/{dataset_id}/imports", headers=headers).json()
    assert journal[0]["status"] == "rejected"
    assert journal[0]["errors"]


def test_mixed_batch_duplicates_and_conflict_rejects_everything(client):
    headers = login(client, "admin")
    dataset_id = make_dataset(client, headers)
    mixed = (b"subject,arm,pre_value,value\n"
             b"U-1,control,10,20\n"
             b"U-1,control,10,20\n"
             b"U-2,treatment,11,21\n"
             b"U-2,treatment,11,99\n"
             b"U-3,control,12,22\n")
    response = upload(client, headers, dataset_id, mixed)
    assert response.status_code == 422
    assert client.get(f"/datasets/{dataset_id}/observations",
                      headers=headers).status_code == 404


def test_import_permissions(client):
    admin = login(client, "admin")
    dataset_id = make_dataset(client, admin)
    viewer = login(client, "viewer")
    response = upload(client, viewer, dataset_id, CSV)
    assert response.status_code == 403


def test_undecodable_file_is_rejected_and_logged(client):
    headers = login(client, "admin")
    dataset_id = make_dataset(client, headers)
    bogus = b"\xff\xfe\x00not a csv"
    response = upload(client, headers, dataset_id, bogus)
    assert response.status_code == 422
    assert "UTF-8" in response.json()["message"]
    journal = client.get(f"/datasets/{dataset_id}/imports", headers=headers).json()
    assert journal[0]["status"] == "rejected"


def test_summary_reports_latest_version_and_source(client):
    headers = login(client, "admin")
    dataset_id = make_dataset(client, headers)
    upload(client, headers, dataset_id, CSV)
    changed = CSV.replace(b"U-3,control,12,22", b"U-3,control,12,23")
    second = upload(client, headers, dataset_id, changed)
    assert second.status_code == 201
    summary = client.get(f"/datasets/{dataset_id}", headers=headers).json()
    assert summary["versions"] == 2
    assert summary["latest_version"] == 2
    assert summary["observations"] == 3
