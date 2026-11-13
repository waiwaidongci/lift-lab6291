from pydantic import BaseModel, Field


class ExperimentInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    dataset_id: int
    version: int | None = None
    hypothesis: str = Field(min_length=8, max_length=1000)
    alpha: float = Field(default=.05, gt=0, lt=.5)
    cuped: bool = True


class ExperimentOut(BaseModel):
    id: int
    name: str
    dataset_id: int
    dataset_version_id: int | None
    dataset_version: int | None = None
    hypothesis: str
    metric: str
    alpha: float
    cuped: bool
    owner: str
