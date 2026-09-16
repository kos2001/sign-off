from datetime import datetime, timezone, timedelta

import pytest

from app.models import Domain, RunEvidence, RunStatus, SignoffRun, Stage
from app.services.stages import evaluate_gate


def run(id, domain, revision, *, stage=Stage.placement, source='manual'):
    return SignoffRun(id=id, project_id=1, domain=domain, stage=stage, status=RunStatus.passed,
                      tool='test', created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                      evidence=RunEvidence(source=source, design_revision=revision, result={}), violations=[])


def test_manual_passes_with_matching_revision_do_not_establish_coverage():
    runs = [run(i, d, 'rev-A') for i, d in enumerate([Domain.sta, Domain.emir, Domain.pv], 1)]
    gate = evaluate_gate(runs, Stage.placement)
    assert gate['revision_check'] == {'status': 'consistent', 'revisions': ['rev-A'], 'missing_domains': [], 'common_revision': 'rev-A'}
    assert not gate['ready']
    assert all(not d['ready'] and 'manual status' in d['reason'] for d in gate['domains'])


@pytest.mark.parametrize('revision', [None, '', '   '])
def test_missing_revision_is_not_treated_as_matching(revision):
    runs = [run(1, Domain.sta, 'rev-A'), run(2, Domain.emir, revision), run(3, Domain.pv, 'rev-A')]
    gate = evaluate_gate(runs, Stage.placement)
    assert gate['revision_check'] == {'status': 'missing', 'revisions': ['rev-A'], 'missing_domains': ['emir'], 'common_revision': None}
    assert not gate['ready']


def test_mismatch_preserves_missing_domains_and_latest_run_selection():
    old = run(1, Domain.sta, 'rev-A')
    newer = run(4, Domain.sta, 'rev-B')  # Same timestamp: highest ID wins.
    unrelated = run(9, Domain.pv, 'unrelated', stage=Stage.final)
    gate = evaluate_gate([old, run(2, Domain.emir, 'rev-A'), newer, unrelated], Stage.placement)
    assert gate['revision_check'] == {'status': 'mismatch', 'revisions': ['rev-A', 'rev-B'], 'missing_domains': ['pv'], 'common_revision': None}
    assert gate['domains'][0]['run_id'] == 4
    assert not gate['ready']
    # Creation time wins over ID, including a failed/running newer run.
    old.created_at = newer.created_at + timedelta(seconds=1)
    old.status = RunStatus.running
    gate = evaluate_gate([newer, old], Stage.placement)
    assert gate['domains'][0]['run_id'] == 1
    assert gate['domains'][0]['reason'] == "latest run status is 'running'"


def test_same_revision_does_not_promote_partial_sta_report():
    gate = evaluate_gate([run(1, Domain.sta, 'rev-A', source='opensta_report'), run(2, Domain.emir, 'rev-A'), run(3, Domain.pv, 'rev-A')], Stage.placement)
    assert gate['revision_check']['status'] == 'consistent'
    assert not gate['domains'][0]['ready'] and 'full STA coverage' in gate['domains'][0]['reason']
    assert not gate['ready']


def test_empty_stage_has_explicit_missing_revision_report():
    gate = evaluate_gate([], Stage.rtl)
    assert gate['revision_check'] == {'status': 'missing', 'revisions': [], 'missing_domains': ['rtl', 'sta'], 'common_revision': None}
    assert not gate['ready']
