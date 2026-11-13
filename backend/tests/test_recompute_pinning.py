"""Version pinning for recomputation: a new upload must not change old runs."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.config.database import Base
from src import models  # noqa: F401
from src.models import AnalysisRun
from src.services.dataset_service import create_dataset, publish_import
from src.services.experiment_service import create_experiment
from src.services.run_service import _present
from src.schemas.experiment import ExperimentInput
from src.worker import process_run
from .helpers import csv_bytes


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    user = models.User(email="a@b.c", name="分析", role="analyst", password_hash="x")
    db.add(user); db.commit()
    yield db, user
    db.close()


def _publish(db, user, dataset_id, lines):
    return publish_import(db, dataset_id, "f.csv", csv_bytes(lines), "", user)


def test_old_run_result_unchanged_after_new_version(session, monkeypatch):
    db, user = session
    monkeypatch.setattr("src.worker.Path.write_text", lambda *a, **k: 0)
    monkeypatch.setattr("src.worker.Path.mkdir", lambda *a, **k: None)

    dataset = create_dataset(db, "复算数据集", "src.csv", "", user)
    import random
    rng = random.Random(7)
    extra = [f"U-{i},{'control' if i % 2 else 'treatment'},{10+rng.gauss(0,2):.4f},{20+rng.gauss(0,4):.4f}"
             for i in range(1, 41)]
    v1 = _publish(db, user, dataset["id"], extra)
    assert v1["version"]["version"] == 1

    experiment = create_experiment(db, ExperimentInput(
        name="复算实验", dataset_id=dataset["id"], hypothesis="旧实验使用原始观测复算"), user)
    run = AnalysisRun(experiment_id=experiment["id"],
                      dataset_version_id=experiment["dataset_version_id"], status="queued")
    db.add(run); db.commit()
    assert process_run(db, run.id)
    original = dict(db.get(AnalysisRun, run.id).result["raw"])

    # New upload changes treated users' revenue substantially.
    treated = [line for line in extra if "treatment" in line]
    changed = extra + [f"U-9{i},treatment,11,{60+i}" for i in range(1, 30)]
    v2 = _publish(db, user, dataset["id"], changed)
    assert v2["version"]["version"] == 2

    # Re-running the same experiment still reads v1 and yields the same numbers.
    rerun = AnalysisRun(experiment_id=experiment["id"],
                        dataset_version_id=experiment["dataset_version_id"], status="queued")
    db.add(rerun); db.commit()
    assert process_run(db, rerun.id)
    again = db.get(AnalysisRun, rerun.id).result["raw"]
    assert again["n_control"] == original["n_control"]
    assert again["n_treatment"] == original["n_treatment"]
    assert again["difference"] == pytest.approx(original["difference"], rel=0, abs=1e-12)

    # Comparing against v2 actually produced a different result, proving the pin matters.
    new_exp = create_experiment(db, ExperimentInput(
        name="新版本实验", dataset_id=dataset["id"], version=2, hypothesis="新版本观测收入不同"), user)
    new_run = AnalysisRun(experiment_id=new_exp["id"],
                          dataset_version_id=new_exp["dataset_version_id"], status="queued")
    db.add(new_run); db.commit()
    assert process_run(db, new_run.id)
    assert db.get(AnalysisRun, new_run.id).result["raw"]["difference"] != pytest.approx(
        original["difference"], abs=1e-6)

    presented = _present(db, db.get(AnalysisRun, run.id))
    assert presented["dataset_version"] == 1


def test_worker_rejects_experiment_without_version(session, monkeypatch):
    db, user = session
    monkeypatch.setattr("src.worker.Path.write_text", lambda *a, **k: 0)
    dataset = create_dataset(db, "空集", "", "", user)
    from src.models import Experiment
    exp = Experiment(name="无版本", dataset_id=dataset["id"], dataset_version_id=None,
                     hypothesis="没有版本时必须失败", owner="x")
    db.add(exp); db.commit()
    run = AnalysisRun(experiment_id=exp.id, status="queued")
    db.add(run); db.commit()
    assert process_run(db, run.id)
    row = db.get(AnalysisRun, run.id)
    assert row.status == "failed"
    assert "版本" in row.error
