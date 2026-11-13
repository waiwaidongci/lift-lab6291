from .constants.status import RunStatus
import json, time, traceback
from pathlib import Path
from .config.database import SessionLocal,engine,Base
from .models import AnalysisRun,Experiment,Observation
from .services.run_service import queue
from .services.statistics_service import analyze
from .services.audit_service import log


def process_run(db, run_id):
    """Recompute one queued run against the dataset version pinned on the run."""
    run=db.get(AnalysisRun,run_id)
    if not run or run.status!=RunStatus.QUEUED: return False
    run.status=RunStatus.RUNNING; db.commit()
    try:
        exp=db.get(Experiment,run.experiment_id)
        version_id=run.dataset_version_id or exp.dataset_version_id
        if not version_id: raise ValueError("实验没有固定观测版本")
        obs=db.query(Observation).filter_by(dataset_version_id=version_id).all()
        run.result=analyze(obs,exp.alpha,exp.cuped)
        run.status=RunStatus.COMPLETED
        Path("/artifacts").mkdir(exist_ok=True)
        Path(f"/artifacts/run-{run.id}.json").write_text(json.dumps(run.result,ensure_ascii=False))
        log(db,"worker","analysis.completed",run.id)
    except Exception as error:
        run.status=RunStatus.FAILED; run.error=str(error); traceback.print_exc()
    db.commit()
    return True


def main():
    Base.metadata.create_all(engine)
    Path("/artifacts").mkdir(exist_ok=True)
    while True:
        Path("/artifacts/heartbeat").write_text(str(time.time()))
        job=queue.blpop("lift:jobs",timeout=2)
        if not job: continue
        with SessionLocal() as db:
            process_run(db,int(job[1]))


if __name__=="__main__": main()
