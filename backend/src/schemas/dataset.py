from pydantic import BaseModel, Field


class DatasetSummary(BaseModel):
    id: int
    name: str
    source: str
    description: str
    checksum: str
    observations: int
    versions: int = 0
    latest_version: int = 0
    latest_version_id: int | None = None
    created_at: str | None = None


class ObservationRow(BaseModel):
    subject: str
    arm: str
    pre_value: float
    value: float


class DatasetVersionOut(BaseModel):
    id: int
    dataset_id: int
    version: int
    checksum: str
    source: str
    description: str
    rows_received: int
    rows_unique: int
    duplicates_removed: int
    created_by: str
    created_at: str


class ImportOut(BaseModel):
    id: int
    dataset_id: int
    version_id: int | None
    status: str
    filename: str
    checksum: str
    rows_received: int
    rows_unique: int
    duplicates_removed: int
    errors: list[dict] | list = []
    reason: str
    actor: str
    created_at: str


class DatasetCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    source: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=1000)


class ImportResult(BaseModel):
    status: str
    version: DatasetVersionOut
    import_id: int
    message: str
    rows_received: int
    rows_unique: int
    duplicates_removed: int
