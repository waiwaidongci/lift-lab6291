from src.services.dataset_service import (
    create_dataset, publish_import, list_versions, observations, list_imports,
    dataset_usage,
)
from src.models import DatasetVersion, Observation, Experiment
from src.services.experiment_service import list_experiments, create_experiment
from src.schemas.experiment import ExperimentInput
from .helpers import csv_bytes


def setup_dataset(db, user):
    dataset = create_dataset(db, "付费入口 · 测试", "test.csv", "测试数据", user)
    return dataset


def publish(db, user, dataset_id, lines, description=""):
    return publish_import(db, dataset_id, "upload.csv", csv_bytes(lines), description, user)


def test_first_import_publishes_version_one(db, user):
    dataset = setup_dataset(db, user)
    result = publish(db, user, dataset["id"], ["U-1,control,10,20", "U-2,treatment,11,21"])
    assert result["status"] == "published"
    assert result["version"]["version"] == 1
    assert result["rows_unique"] == 2
    versions = list_versions(db, dataset["id"])
    assert [v["version"] for v in versions] == [1]
    assert observations(db, dataset["id"]) != []


def test_reimport_identical_content_does_not_add_version(db, user):
    dataset = setup_dataset(db, user)
    lines = ["U-1,control,10,20", "U-2,treatment,11,21", "U-3,control,12,22"]
    first = publish(db, user, dataset["id"], lines)
    again = publish(db, user, dataset["id"], lines)
    assert first["status"] == "published"
    assert again["status"] == "duplicate"
    assert again["version"]["id"] == first["version"]["id"]
    assert len(list_versions(db, dataset["id"])) == 1
    assert db.query(Observation).count() == 3


def test_reimport_shuffled_content_does_not_add_version(db, user):
    dataset = setup_dataset(db, user)
    lines = ["U-1,control,10,20", "U-2,treatment,11,21", "U-3,control,12,22"]
    shuffle = [lines[2], lines[0], lines[1]]
    publish(db, user, dataset["id"], lines)
    again = publish(db, user, dataset["id"], shuffle)
    assert again["status"] == "duplicate"
    assert len(list_versions(db, dataset["id"])) == 1


def test_mixed_duplicates_and_conflicts_rejects_whole_batch(db, user):
    dataset = setup_dataset(db, user)
    lines = [
        "U-1,control,10,20",
        "U-1,control,10,20",     # duplicate
        "U-2,treatment,11,21",
        "U-2,treatment,11,99",   # conflict
        "U-3,treatment,12,22",
    ]
    result = publish(db, user, dataset["id"], lines)
    assert result["status"] == "rejected"
    assert len(list_versions(db, dataset["id"])) == 0
    # No observations from the rejected batch leaked or were partially imported.
    assert db.query(Observation).count() == 0
    # Header is file line 1, so the conflicting row is file line 5.
    assert 5 in {e["line"] for e in result["errors"]}
    imports = list_imports(db, dataset["id"])
    assert imports[0]["status"] == "rejected"
    assert imports[0]["errors"]


def test_conflict_detected_across_versions_as_duplicate_rule_is_per_version(db, user):
    dataset = setup_dataset(db, user)
    first = publish(db, user, dataset["id"], ["U-1,control,10,20", "U-2,treatment,11,21"])
    # A newer upload that changes a value yields a *new* version, not a conflict.
    second = publish(db, user, dataset["id"], ["U-1,control,10,20", "U-2,treatment,11,99"])
    assert first["version"]["version"] == 1
    assert second["version"]["version"] == 2
    assert len(list_versions(db, dataset["id"])) == 2
    old = observations(db, dataset["id"], version=1)
    new = observations(db, dataset["id"], version=2)
    assert {o["subject"]: o["value"] for o in old}["U-2"] == 21
    assert {o["subject"]: o["value"] for o in new}["U-2"] == 99


def test_deduplicated_version_counts_rows(db, user):
    dataset = setup_dataset(db, user)
    lines = ["U-1,control,10,20", "U-2,treatment,11,21", "U-1,control,10,20"]
    result = publish(db, user, dataset["id"], lines)
    assert result["status"] == "published"
    assert result["rows_received"] == 3
    assert result["rows_unique"] == 2
    assert result["duplicates_removed"] == 1
    assert result["version"]["rows_unique"] == 2


def test_experiment_pins_version_and_old_results_keep_original_observations(db, user):
    dataset = setup_dataset(db, user)
    first = publish(db, user, dataset["id"], ["U-1,control,10,20", "U-2,treatment,11,21"])
    experiment = create_experiment(db, ExperimentInput(
        name="实验A", dataset_id=dataset["id"], version=1, hypothesis="提高每用户收入假设"), user)
    assert experiment["dataset_version"] == 1
    pinned = db.get(DatasetVersion, experiment["dataset_version_id"])
    assert pinned.version == 1

    second = publish(db, user, dataset["id"], ["U-1,control,10,20", "U-2,treatment,11,99"])
    assert second["version"]["version"] == 2

    # The old experiment still points at v1; its observations are unchanged.
    exp = [e for e in list_experiments(db) if e["id"] == experiment["id"]][0]
    assert exp["dataset_version"] == 1
    v1 = observations(db, dataset["id"], version=1)
    assert {o["subject"]: o["value"] for o in v1}["U-2"] == 21

    # A new experiment can be registered on the new version.
    newer = create_experiment(db, ExperimentInput(
        name="实验B", dataset_id=dataset["id"], version=2, hypothesis="在新版本上验证同一假设"), user)
    assert newer["dataset_version"] == 2

    usage = dataset_usage(db, dataset["id"])
    assert {e["name"]: e["version"] for e in usage} == {"实验A": 1, "实验B": 2}


def test_experiment_registration_defaults_to_latest_version(db, user):
    dataset = setup_dataset(db, user)
    publish(db, user, dataset["id"], ["U-1,control,10,20", "U-2,treatment,11,21"])
    publish(db, user, dataset["id"], ["U-1,control,10,20", "U-2,treatment,11,99"])
    experiment = create_experiment(db, ExperimentInput(
        name="实验C", dataset_id=dataset["id"], hypothesis="默认落在最新观测版本"), user)
    assert experiment["dataset_version"] == 2


def test_experiment_on_dataset_without_version_is_rejected(db, user):
    from fastapi import HTTPException
    import pytest
    dataset = setup_dataset(db, user)
    with pytest.raises(HTTPException) as error:
        create_experiment(db, ExperimentInput(
            name="实验D", dataset_id=dataset["id"], hypothesis="没有观测版本时不能登记"), user)
    assert error.value.status_code == 409


def test_imports_journal_keeps_rejection_reasons(db, user):
    dataset = setup_dataset(db, user)
    publish(db, user, dataset["id"], ["U-1,control,10,20"])
    publish(db, user, dataset["id"], ["U-1,control,10,20"])
    publish(db, user, dataset["id"], ["U-1,control,10,20", "U-1,control,10,99"])
    statuses = [row["status"] for row in list_imports(db, dataset["id"])]
    assert statuses == ["rejected", "duplicate", "published"][::-1] or statuses[0] == "rejected"
    assert set(statuses) == {"published", "duplicate", "rejected"}
