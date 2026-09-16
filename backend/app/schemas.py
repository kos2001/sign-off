from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
    evidence_source: str
    result_locked: bool


class RunEvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: int
    source: str
    source_text: str | None
    source_sha256: str | None
    design_revision: str | None
    result: dict
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
    approved_user_id: int | None = None
    created_at: datetime


class ViolationOut(ViolationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    status: ViolationStatus
    version: int
    waiver: WaiverOut | None = None


class ProjectViolationOut(ViolationOut):
    run: RunOut


class ViolationPage(BaseModel):
    items: list[ProjectViolationOut]
    total: int
    open_blocking: int
    offset: int
    limit: int


class MetricComparisonOut(BaseModel):
    name: str
    baseline: Any
    candidate: Any
    baseline_present: bool
    candidate_present: bool
    changed: bool
    delta: int | float | None


class ViolationComparisonOut(BaseModel):
    kind: Literal["new", "changed", "removed", "unchanged"]
    baseline: ViolationOut | None
    candidate: ViolationOut | None
    changed_fields: list[str]
    ambiguous_match: bool


class RunProvenanceOut(BaseModel):
    source: str
    design_revision: str | None
    source_sha256: str | None
    scenario: str | None
    tool_version: str | None
    coverage: str | None


class RunComparisonOut(BaseModel):
    baseline_run: RunOut
    candidate_run: RunOut
    baseline_provenance: RunProvenanceOut
    candidate_provenance: RunProvenanceOut
    partial: bool
    different_tools: bool
    summary: dict[str, int]
    metrics: list[MetricComparisonOut]
    items: list[ViolationComparisonOut]
    total: int
    offset: int
    limit: int


class WaiverCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=4000)
    approved_by: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1, le=2_147_483_646, strict=True)


class ViolationTransition(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    expected_status: ViolationStatus
    expected_version: int = Field(ge=1, le=2_147_483_646, strict=True)
    status: ViolationStatus
    actor: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=4000)


class ViolationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    violation_id: int
    from_status: ViolationStatus
    to_status: ViolationStatus
    actor: str
    actor_user_id: int | None = None
    reason: str
    created_at: datetime


FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]
PositiveNumber = Annotated[FiniteNumber, Field(gt=0)]
NonnegativeNumber = Annotated[FiniteNumber, Field(ge=0)]
Ratio = Annotated[FiniteNumber, Field(ge=0, le=1)]
RatioRow = Annotated[list[Ratio], Field(min_length=1, max_length=256)]
StrengthRow = Annotated[list[PositiveNumber], Field(min_length=1, max_length=256)]


class IrDropRequest(BaseModel):
    cell_density: list[RatioRow] = Field(min_length=1, max_length=256)
    switching_activity: list[RatioRow] = Field(min_length=1, max_length=256)
    pdn_strength: list[StrengthRow] = Field(min_length=1, max_length=256)
    vdd: PositiveNumber = 0.75
    scale: NonnegativeNumber = 0.1
    hotspot_threshold_ratio: Ratio = 0.05

    @model_validator(mode='after')
    def matching_grids(self):
        shape = (len(self.cell_density), len(self.cell_density[0]))
        for name in ['cell_density', 'switching_activity', 'pdn_strength']:
            grid = getattr(self, name)
            if len(grid) != shape[0] or any(len(row) != shape[1] for row in grid):
                raise ValueError('all grids must be rectangular and have the same shape')
        return self


class GlitchNet(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    cap_ff: PositiveNumber
    functional_toggle_rate: NonnegativeNumber
    total_toggle_rate: NonnegativeNumber
    transport_fraction: Ratio = 1.0

    @model_validator(mode='after')
    def consistent_toggles(self):
        if self.total_toggle_rate < self.functional_toggle_rate:
            raise ValueError('total_toggle_rate must be at least functional_toggle_rate')
        return self


class GlitchPowerRequest(BaseModel):
    nets: list[GlitchNet] = Field(min_length=1, max_length=10000)
    vdd: PositiveNumber = 0.75
    clock_period_ns: PositiveNumber = 1.0


class RtlSignoffRequest(BaseModel):
    testbench: str | None = Field(default=None, min_length=1, max_length=500_000)
    testbench_top: str | None = Field(default=None, max_length=120, pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$")

    @model_validator(mode="after")
    def validate_testbench(self):
        if (self.testbench is None) != (self.testbench_top is None):
            raise ValueError("testbench and testbench_top must be supplied together")
        if self.testbench is not None and not self.testbench.strip():
            raise ValueError("testbench must not be blank")
        return self

    code: str = Field(min_length=1, max_length=500_000, description="Single-file SystemVerilog source")
    design_revision: str | None = Field(default=None, max_length=160)
    project_id: int | None = Field(
        default=None, strict=True, ge=1, le=2**63 - 1,
        description="When set, record the result as a signoff run (domain=rtl, stage=rtl) "
        "and file failing checks as violations",
    )


class TimingCorner(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160, examples=["ss_0p675v_125c"])
    endpoint_slacks_ps: list[FiniteNumber] = Field(min_length=1, max_length=10000)
    endpoint_ids: list[Annotated[str, StringConstraints(strip_whitespace=False, min_length=1, max_length=200)]] | None = Field(default=None, min_length=1, max_length=10000)

    @model_validator(mode='after')
    def endpoint_identity(self):
        if self.endpoint_ids is not None:
            if any(not identifier.strip() or any(ord(c) < 32 for c in identifier) for identifier in self.endpoint_ids):
                raise ValueError('endpoint_ids must not be blank or contain control characters')
            if len(self.endpoint_ids) != len(self.endpoint_slacks_ps):
                raise ValueError('endpoint_ids and endpoint_slacks_ps must have the same length')
            if len(set(self.endpoint_ids)) != len(self.endpoint_ids):
                raise ValueError('endpoint_ids must be unique within each corner')
        return self


class TimingSummaryRequest(BaseModel):
    corners: list[TimingCorner] = Field(min_length=1, max_length=64)
    pba_pessimism_credit_ps: NonnegativeNumber = 0.0

    @model_validator(mode='after')
    def matching_endpoints(self):
        if len({corner.name for corner in self.corners}) != len(self.corners):
            raise ValueError('corner names must be unique')
        if len({len(corner.endpoint_slacks_ps) for corner in self.corners}) != 1:
            raise ValueError('all corners must report the same number of endpoints')
        if sum(len(corner.endpoint_slacks_ps) for corner in self.corners) > 100000:
            raise ValueError('total corner endpoint values must not exceed 100000')
        return self
