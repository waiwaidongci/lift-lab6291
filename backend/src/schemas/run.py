from pydantic import BaseModel


class RunOutput(BaseModel):
    id: int
    experiment_id: int
    dataset_version_id: int | None = None
    dataset_version: int | None = None
    dataset_version_checksum: str = ""
    status: str
    result: dict
    error: str
    created_at: str
