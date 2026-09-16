"""Conservative completion checks for the built-in RTL ladder."""

from ..models import RunStatus

REQUIRED_RTL_STAGES = {"lint", "design", "synthesize", "simulate"}


def rtl_result_status(result: dict) -> RunStatus:
    stages = result.get("stages")
    if result.get("verdict") == "REJECTED":
        return RunStatus.failed
    if not isinstance(stages, list) or any(
        not isinstance(stage, dict) or not isinstance(stage.get("name"), str) for stage in stages
    ):
        return RunStatus.incomplete
    relevant = [s for s in stages if s.get("gating") is True or s.get("name") in REQUIRED_RTL_STAGES]
    if any(s.get("status") == "fail" for s in relevant):
        return RunStatus.failed
    names = [s.get("name") for s in relevant]
    if any(not isinstance(name, str) for name in names):
        return RunStatus.incomplete
    if (
        result.get("verdict") != "SIGNED_OFF"
        or not REQUIRED_RTL_STAGES.issubset(names)
        or len(names) != len(set(names))
        or any(s.get("gating") is not True or s.get("status") != "pass" for s in relevant)
    ):
        return RunStatus.incomplete
    return RunStatus.passed
