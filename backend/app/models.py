import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Domain(str, enum.Enum):
    rtl = "rtl"
    sta = "sta"
    emir = "emir"
    pv = "pv"
    glitch_power = "glitch_power"
    thermal = "thermal"


class Stage(str, enum.Enum):
    rtl = "rtl"
    synthesis = "synthesis"
    placement = "placement"
    routing = "routing"
    final = "final"


class RunStatus(str, enum.Enum):
    running = "running"
    passed = "passed"
    failed = "failed"


class Severity(str, enum.Enum):
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"


class ViolationStatus(str, enum.Enum):
    open = "open"
    fixed = "fixed"
    waived = "waived"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    process_node: Mapped[str] = mapped_column(String(40))
    foundry: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    runs: Mapped[list["SignoffRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class SignoffRun(Base):
    __tablename__ = "signoff_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    domain: Mapped[Domain] = mapped_column(Enum(Domain))
    stage: Mapped[Stage] = mapped_column(Enum(Stage))
    tool: Mapped[str] = mapped_column(String(80))
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.running)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="runs")
    violations: Mapped[list["Violation"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Violation(Base):
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("signoff_runs.id"), index=True)
    check_name: Mapped[str] = mapped_column(String(120))
    severity: Mapped[Severity] = mapped_column(Enum(Severity))
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ViolationStatus] = mapped_column(
        Enum(ViolationStatus), default=ViolationStatus.open
    )

    run: Mapped[SignoffRun] = relationship(back_populates="violations")
    waiver: Mapped["Waiver | None"] = relationship(
        back_populates="violation", cascade="all, delete-orphan", uselist=False
    )


class Waiver(Base):
    __tablename__ = "waivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    violation_id: Mapped[int] = mapped_column(ForeignKey("violations.id"), unique=True)
    reason: Mapped[str] = mapped_column(Text)
    approved_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    violation: Mapped[Violation] = relationship(back_populates="waiver")
