"""CSV observation ingestion: validation, de-duplication, version publishing.

Rules:
- One row per anonymous subject per published version.
- Rows whose subject repeats with identical arm/pre/value are treated as the
  same observation and collapsed to one (the first line wins for provenance).
- A subject that repeats with a conflicting arm or numeric value makes the
  whole batch invalid; every offending line number is reported.
- The content checksum is computed over rows sorted by subject, so a re-export
  with shuffled line order is recognised as the same version.
"""
import csv
import hashlib
import io
import math
from dataclasses import dataclass, field

MAX_BYTES = 20 * 1024 * 1024
MAX_ERRORS = 200
ARMS = {"control", "treatment"}
ARM_ALIASES = {
    "control": "control",
    "treatment": "treatment",
    "对照组": "control",
    "候选组": "treatment",
}
HEADER_ALIASES = {
    "subject": ("subject", "user", "user_id", "用户", "匿名用户", "样本"),
    "arm": ("arm", "group", "分组", "实验分组"),
    "pre_value": ("pre_value", "pre", "pre_revenue", "前置", "前置7日收入", "前置收入"),
    "value": ("value", "y", "revenue", "后置", "后置7日收入", "后置收入"),
}


@dataclass
class ParsedBatch:
    rows: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    row_count: int = 0
    duplicate_count: int = 0


def _normalise_header(name):
    return (name or "").strip().lower().replace(" ", "")


def _resolve_columns(fieldnames):
    mapping = {}
    normalised = {_normalise_header(f): f for f in (fieldnames or [])}
    for key, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if _normalise_header(alias) in normalised:
                mapping[key] = normalised[_normalise_header(alias)]
                break
    return mapping


def _number(raw):
    value = float(str(raw).strip())
    if not math.isfinite(value):
        raise ValueError("数值不是有限值")
    return value


def parse_csv(content: bytes) -> tuple[ParsedBatch, str]:
    """Parse raw bytes into unique rows, rejecting the batch on any conflict."""
    if len(content) > MAX_BYTES:
        raise ValueError("文件过大，最多 20MB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("gb18030")
        except UnicodeDecodeError as error:
            raise ValueError("文件必须为 UTF-8 编码的 CSV") from error

    reader = csv.DictReader(io.StringIO(text, newline=""))
    columns = _resolve_columns(reader.fieldnames)
    missing = [key for key in HEADER_ALIASES if key not in columns]
    if missing:
        batch = ParsedBatch()
        batch.errors.append({
            "line": 1,
            "subject": "",
            "reason": "缺少必需列：" + "、".join(missing)
                      + "（需要 subject, arm, pre_value, value）",
        })
        return batch, ""

    batch = ParsedBatch()
    first_seen = {}
    total_errors = 0
    # DictReader starts consuming data lines at file line 2.
    for line, raw in enumerate(reader, start=2):
        if raw is None or all((v or "").strip() == "" for v in raw.values()):
            continue
        if None in raw:
            total_errors += 1
            if len(batch.errors) < MAX_ERRORS:
                batch.errors.append({
                    "line": line,
                    "subject": "",
                    "reason": f"列数多于表头：{len(raw) - 1} 个字段",
                })
            continue

        subject = (raw.get(columns["subject"]) or "").strip()
        arm_raw = (raw.get(columns["arm"]) or "").strip()
        pre_raw = (raw.get(columns["pre_value"]) or "").strip()
        value_raw = (raw.get(columns["value"]) or "").strip()
        problems = []
        if not subject:
            problems.append("用户标识为空")
        arm = ARM_ALIASES.get(arm_raw.lower()) or ARM_ALIASES.get(arm_raw)
        if arm not in ARMS:
            problems.append(f"未知分组「{arm_raw}」，只接受 control / treatment")
        try:
            pre_value = _number(pre_raw)
        except ValueError:
            pre_value = None
            problems.append(f"前置收入不是有限数值「{pre_raw}」")
        try:
            value = _number(value_raw)
        except ValueError:
            value = None
            problems.append(f"后置收入不是有限数值「{value_raw}」")

        if problems:
            total_errors += 1
            if len(batch.errors) < MAX_ERRORS:
                batch.errors.append({
                    "line": line,
                    "subject": subject,
                    "reason": "；".join(problems),
                })
            continue

        batch.row_count += 1
        row = {"subject": subject, "arm": arm, "pre_value": pre_value, "value": value}
        key = (subject, arm, pre_value, value)
        if subject in first_seen:
            previous_line, previous_key = first_seen[subject]
            if previous_key == key:
                batch.duplicate_count += 1
            else:
                total_errors += 1
                if len(batch.errors) < MAX_ERRORS:
                    batch.errors.append({
                        "line": line,
                        "subject": subject,
                        "reason": (f"同一匿名样本的分组或数值与前次出现（第 {previous_line} 行）"
                                   "不一致，整批拒绝"),
                    })
            continue
        first_seen[subject] = (line, key)
        batch.rows.append(row)

    if total_errors > len(batch.errors):
        batch.errors.append({
            "line": 0,
            "subject": "",
            "reason": f"另有 {total_errors - len(batch.errors)} 行错误未逐条列出",
        })
    if not batch.rows and not batch.errors:
        batch.errors.append({"line": 1, "subject": "", "reason": "文件没有可导入的观测"})
    return batch, canonical_checksum(batch.rows) if batch.rows else ""


def canonical_checksum(rows) -> str:
    """Order-independent checksum over the de-duplicated content."""
    lines = []
    for row in sorted(rows, key=lambda r: r["subject"]):
        lines.append("\t".join([
            row["subject"],
            row["arm"],
            repr(float(row["pre_value"])),
            repr(float(row["value"])),
        ]))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
