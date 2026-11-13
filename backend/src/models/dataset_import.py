from sqlalchemy import ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..config.database import Base
from ..utils.clock import now


class DatasetImport(Base):
    """Every upload attempt, including rejected and de-duplicated ones."""

    __tablename__ = "dataset_imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    version_id: Mapped[int | None] = mapped_column(ForeignKey("dataset_versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(default="rejected")
    filename: Mapped[str] = mapped_column(default="")
    checksum: Mapped[str] = mapped_column(default="")
    rows_received: Mapped[int] = mapped_column(default=0)
    rows_unique: Mapped[int] = mapped_column(default=0)
    duplicates_removed: Mapped[int] = mapped_column(default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(default="")
    actor: Mapped[str] = mapped_column(default="")
    created_at: Mapped[str] = mapped_column(default=now)
