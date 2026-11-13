from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..config.database import Base
from ..utils.clock import now


class Dataset(Base):
    """Logical dataset family. Published snapshots live in DatasetVersion."""

    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    source: Mapped[str]
    description: Mapped[str]
    checksum: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=now)


class DatasetVersion(Base):
    """An immutable, published snapshot of a dataset."""

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version"),
        UniqueConstraint("dataset_id", "checksum"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    version: Mapped[int]
    checksum: Mapped[str]
    source: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
    rows_received: Mapped[int] = mapped_column(default=0)
    rows_unique: Mapped[int] = mapped_column(default=0)
    duplicates_removed: Mapped[int] = mapped_column(default=0)
    created_by: Mapped[str] = mapped_column(default="")
    created_at: Mapped[str] = mapped_column(default=now)
