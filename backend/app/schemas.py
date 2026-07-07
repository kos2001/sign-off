from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import Domain, RunStatus, Severity, Stage, ViolationStatus


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    process_node: str = Field(min_length=1, max_length=40, examples=["3nm"])
    foundry: str = Field(min_length=1, max_length=60, examples=["TSMC"])


class ProjectOut(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class RunCreate(BaseModel):
    domain: Domain
    stage: Stage
    tool: str = Field(min_length=1, max_length=80, examples=["PrimeTime"])
    metrics: dict = Field(default_factory=dict)


class RunUpdate(BaseModel):
    status: RunStatus
    metrics: dict | None = None


class RunOut(RunCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    status: RunStatus
    created_at: datetime


class ViolationCreate(BaseModel):
    check_name: str = Field(min_length=1, max_length=120)
    severity: Severity
    location: str | None = Field(default=None, max_length=200)
    description: str | None = None


class WaiverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    violation_id: int
    reason: str
    approved_by: str
    created_at: datetime


class ViolationOut(ViolationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    status: ViolationStatus
    waiver: WaiverOut | None = None


class WaiverCreate(BaseModel):
    reason: str = Field(min_length=1)
    approved_by: str = Field(min_length=1, max_length=80)


class IrDropRequest(BaseModel):
    cell_density: list[list[float]]
    switching_activity: list[list[float]]
    pdn_strength: list[list[float]]
    vdd: float = 0.75
    scale: float = 0.1
    hotspot_threshold_ratio: float = 0.05


class GlitchNet(BaseModel):
    name: str | None = None
    cap_ff: float
    functional_toggle_rate: float
    total_toggle_rate: float
    transport_fraction: float = 1.0


class GlitchPowerRequest(BaseModel):
    nets: list[GlitchNet] = Field(min_length=1)
    vdd: float = 0.75
    clock_period_ns: float = 1.0


class RtlSignoffRequest(BaseModel):
    code: str = Field(min_length=1, description="Single-file SystemVerilog source")
    project_id: int | None = Field(
        default=None,
        description="When set, record the result as a signoff run (domain=rtl, stage=rtl) "
        "and file failing checks as violations",
    )


class TimingCorner(BaseModel):
    name: str = Field(min_length=1, examples=["ss_0p675v_125c"])
    endpoint_slacks_ps: list[float] = Field(min_length=1)


class TimingSummaryRequest(BaseModel):
    corners: list[TimingCorner] = Field(min_length=1)
    pba_pessimism_credit_ps: float = Field(default=0.0, ge=0)
