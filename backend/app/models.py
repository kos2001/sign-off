import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
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
    incomplete = "incomplete"
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
    evidence: Mapped["RunEvidence | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )

    @property
    def evidence_source(self) -> str:
        return self.evidence.source if self.evidence else "legacy"

    @property
    def result_locked(self) -> bool:
        return self.evidence_source in {"rtl_ladder", "opensta_report", "klayout_report"} or (
            self.evidence is None and self.tool == "rtl-signoff-ladder"
        )


class RunEvidence(Base):
    __tablename__ = "run_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("signoff_runs.id"), unique=True)
    source: Mapped[str] = mapped_column(String(40))
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    design_revision: Mapped[str | None] = mapped_column(String(160), nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run: Mapped[SignoffRun] = relationship(back_populates="evidence")


class ReportImport(Base):
    __tablename__ = 'report_imports'
    __table_args__ = (UniqueConstraint('project_id', 'import_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    import_key: Mapped[str] = mapped_column(String(36))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[int] = mapped_column(ForeignKey('signoff_runs.id'), unique=True)


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
    version: Mapped[int] = mapped_column(default=1, server_default="1")

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
    approved_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    violation: Mapped[Violation] = relationship(back_populates="waiver")


class ViolationEvent(Base):
    """Append-only through the API; retained even when a waiver is revoked."""

    __tablename__ = "violation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    violation_id: Mapped[int] = mapped_column(ForeignKey("violations.id"), index=True)
    from_status: Mapped[ViolationStatus] = mapped_column(Enum(ViolationStatus))
    to_status: Mapped[ViolationStatus] = mapped_column(Enum(ViolationStatus))
    actor: Mapped[str] = mapped_column(String(80))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(default=False)
    disabled: Mapped[bool] = mapped_column(default=False)


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    __table_args__ = (Index('ix_auth_sessions_expiry_id', 'expires_at', 'id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column()


class AccountSecurityEvent(Base):
    __tablename__ = 'account_security_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), index=True)
    subject_username: Mapped[str | None] = mapped_column(String(64))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    actor: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(40))
    revoked_sessions: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectMember(Base):
    __tablename__ = 'project_members'
    __table_args__ = (UniqueConstraint('project_id', 'user_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    role: Mapped[str] = mapped_column(String(16))


class LoginBucket(Base):
    __tablename__ = 'login_buckets'
    __table_args__ = (Index('ix_login_buckets_expiry_id', 'expires_at', 'id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    attempts: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[int] = mapped_column()


class ProjectAccessEvent(Base):
    """Append-only through service APIs; snapshots survive membership removal."""
    __tablename__ = 'project_access_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    subject_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    subject_username: Mapped[str] = mapped_column(String(64))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    actor: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(16))
    before_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    after_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunAgentReview(Base):
    __tablename__ = 'run_agent_reviews'
    __table_args__ = (UniqueConstraint('run_id', 'request_key'), Index('ix_run_agent_reviews_run_id_id', 'run_id', 'id'))
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('signoff_runs.id'))
    request_key: Mapped[str] = mapped_column(String(36))
    requester_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    requester: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default='running')
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    review_policy: Mapped[str] = mapped_column(Text)
    model_alias: Mapped[str] = mapped_column(String(200))
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
