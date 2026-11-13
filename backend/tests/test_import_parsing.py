import math
from src.services.dataset_import_service import parse_csv, canonical_checksum
from .helpers import csv_bytes


def test_parse_rejects_conflicting_values_and_reports_lines():
    content = csv_bytes([
        "U-1,control,10,20",
        "U-2,treatment,11,21",
        "U-1,control,10,20",       # identical repeat, line 4
        "U-2,treatment,11,99",     # conflicting value, line 5
    ])
    batch, checksum = parse_csv(content)
    assert batch.errors, "conflict must reject the whole batch"
    assert any("line" in error for error in batch.errors)
    assert [e["line"] for e in batch.errors if e["line"]] == [5]
    assert "不一致" in batch.errors[0]["reason"]
    assert checksum, "checksum still computed for diagnostics"


def test_parse_rejects_conflicting_arm():
    content = csv_bytes([
        "U-1,control,1,2",
        "U-1,treatment,1,2",
    ])
    batch, _ = parse_csv(content)
    assert [e["line"] for e in batch.errors] == [3]


def test_parse_collapses_identical_duplicates_within_batch():
    content = csv_bytes([
        "U-1,control,10,20",
        "U-2,treatment,11,21",
        "U-1,control,10.0,20.0",   # numerically identical
    ])
    batch, checksum = parse_csv(content)
    assert batch.errors == []
    assert len(batch.rows) == 2
    assert batch.duplicate_count == 1
    assert batch.row_count == 3


def test_checksum_is_line_order_independent():
    forward = csv_bytes(["U-1,control,10,20", "U-2,treatment,11,21", "U-3,control,12,22"])
    shuffled = csv_bytes(["U-3,control,12,22", "U-1,control,10,20", "U-2,treatment,11,21"])
    _, first = parse_csv(forward)
    _, second = parse_csv(shuffled)
    assert first == second


def test_checksum_detects_value_change():
    _, first = parse_csv(csv_bytes(["U-1,control,10,20"]))
    _, second = parse_csv(csv_bytes(["U-1,control,10,20.0001"]))
    assert first != second


def test_header_aliases_and_arm_aliases():
    content = "用户,分组,前置收入,后置收入\nU-1,对照组,10,20\nU-2,候选组,11,21\n".encode()
    batch, _ = parse_csv(content)
    assert batch.errors == []
    assert {row["arm"] for row in batch.rows} == {"control", "treatment"}


def test_missing_column_is_reported_not_crashed():
    batch, _ = parse_csv(b"subject,arm,value\nU-1,control,2\n")
    assert batch.errors and "缺少必需列" in batch.errors[0]["reason"]


def test_invalid_numbers_rejected():
    batch, _ = parse_csv(csv_bytes(["U-1,control,NaN,2", "U-2,treatment,3,inf"]))
    assert len(batch.errors) == 2
    assert {e["line"] for e in batch.errors} == {2, 3}


def test_empty_file():
    batch, _ = parse_csv(b"subject,arm,pre_value,value\n")
    assert batch.errors


def test_canonical_checksum_stable_for_floats():
    rows = [{"subject": "A", "arm": "control", "pre_value": 1, "value": 2.5}]
    assert canonical_checksum(rows) == canonical_checksum(rows)
    assert math.isclose(1, 1.0)
