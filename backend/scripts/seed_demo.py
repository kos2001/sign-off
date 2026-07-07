"""Seed the DB with a realistic sign-off scenario: lowRISC Ibex RISC-V core
hardened on the open SkyWater SKY130 PDK (the OpenROAD/OpenLane reference flow).

Real-world anchors: SKY130 liberty corners (tt_025C_1v80 / ss_100C_1v60 /
ff_n40C_1v95, VDD 1.8 V), SKY130 DRC rule names from the periphery rule deck
(met1/met2 spacing, li1, poly), and Ibex module/net naming. Numbers are
representative of a ~100 MHz Ibex build, not tool output.

Usage: .venv/bin/python scripts/seed_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Base, SessionLocal, engine
from app.models import (
    Domain,
    Project,
    RunStatus,
    Severity,
    SignoffRun,
    Stage,
    Violation,
    ViolationStatus,
    Waiver,
)


def seed() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()

    if db.query(Project).filter_by(name="ibex-riscv-sky130").first():
        print("already seeded — skipping")
        return

    ibex = Project(
        name="ibex-riscv-sky130",
        process_node="SKY130 (130nm)",
        foundry="SkyWater",
    )
    db.add(ibex)
    db.flush()

    def run(domain, stage, tool, status, metrics=None):
        r = SignoffRun(
            project_id=ibex.id,
            domain=domain,
            stage=stage,
            tool=tool,
            status=status,
            metrics=metrics or {},
        )
        db.add(r)
        db.flush()
        return r

    # RTL: early timing prediction (shift-left)
    run(
        Domain.sta,
        Stage.rtl,
        "OpenSTA (early)",
        RunStatus.passed,
        {"clock": "clk_i 10ns (100MHz)", "est_wns_ps": 410},
    )

    # Synthesis: STA + vectorless glitch estimate
    run(
        Domain.sta,
        Stage.synthesis,
        "OpenSTA",
        RunStatus.passed,
        {"wns_ps": 260, "tns_ps": 0, "corner": "tt_025C_1v80"},
    )
    run(
        Domain.glitch_power,
        Stage.synthesis,
        "vectorless-glitch",
        RunStatus.passed,
        {"glitch_share": 0.21, "hot_module": "ibex_multdiv_fast"},
    )

    # Placement: STA + EM/IR + PV — PV has a blocking spacing violation, waived
    run(
        Domain.sta,
        Stage.placement,
        "OpenSTA",
        RunStatus.passed,
        {"wns_ps": 120, "corner": "ss_100C_1v60"},
    )
    run(
        Domain.emir,
        Stage.placement,
        "IR-screen (U-Net surrogate)",
        RunStatus.passed,
        {"worst_drop_mv": 62, "threshold_mv": 90, "vdd": 1.8},
    )
    pv_run = run(
        Domain.pv,
        Stage.placement,
        "Magic/netgen DRC",
        RunStatus.passed,
        {"deck": "sky130A periphery rules"},
    )
    v1 = Violation(
        run_id=pv_run.id,
        check_name="met2.2 (min spacing 0.14um)",
        severity=Severity.error,
        location="ibex_id_stage/decoder x=112.4 y=88.1",
        description="met2 spacing under fill transition region",
        status=ViolationStatus.waived,
    )
    db.add(v1)
    db.flush()
    db.add(
        Waiver(
            violation_id=v1.id,
            reason="Fill-transition artifact; cleared by foundry app-note FT-130-07",
            approved_by="pv-lead",
        )
    )
    db.add(
        Violation(
            run_id=pv_run.id,
            check_name="li1.pd.3 (density info)",
            severity=Severity.info,
            location="core_area",
            status=ViolationStatus.open,
        )
    )

    # Routing: STA failing at ss corner + open critical IR violation -> gate blocked
    sta_route = run(
        Domain.sta,
        Stage.routing,
        "OpenSTA",
        RunStatus.failed,
        {"wns_ps": -320, "tns_ps": -1240, "corner": "ss_100C_1v60"},
    )
    db.add(
        Violation(
            run_id=sta_route.id,
            check_name="setup: ibex_ex_block/alu_adder_result_ex_o[31]",
            severity=Severity.critical,
            location="path: id_stage -> ex_block (logic depth 34)",
            description="worst setup path through multdiv bypass mux",
        )
    )
    emir_route = run(
        Domain.emir,
        Stage.routing,
        "IR-screen (U-Net surrogate)",
        RunStatus.failed,
        {"worst_drop_mv": 118, "threshold_mv": 90, "vdd": 1.8},
    )
    db.add(
        Violation(
            run_id=emir_route.id,
            check_name="dynamic IR > 5% VDD",
            severity=Severity.error,
            location="tile (2,7) — multdiv cluster",
            description="118mV worst drop vs 90mV limit; strap M4 power grid",
        )
    )
    run(Domain.pv, Stage.routing, "Magic/netgen DRC+LVS", RunStatus.running)

    db.commit()
    print(f"seeded project #{ibex.id}: ibex-riscv-sky130")


if __name__ == "__main__":
    seed()
