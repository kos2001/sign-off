import copy, hashlib, hmac, json, uuid
from datetime import datetime, timedelta, timezone
import pytest
from app.services.commercial_power import parse_commercial_power
from app.services.coverage_attestation import REQUIRED_POWER_CLAIMS, canonical_payload
from app.routers.imports import CoverageAttestationPayload
from test_auth import accounts

def report(tool='Synopsys PrimePower'):
    return {'format':'signoff/commercial-power/v1','tool':tool,'tool_version':'T-2025.06','power_unit':'uW','glitch_share_limit':.2,
      'summary':{'total_power':1000,'internal_power':200,'switching_power':700,'leakage_power':100,'glitch_power':250},
      'hierarchy':[{'path':'TOP/u_cpu','total_power':600,'internal_power':100,'switching_power':450,'leakage_power':50,'glitch_power':150},
                   {'path':'TOP/u_mem','total_power':400,'internal_power':100,'switching_power':250,'leakage_power':50,'glitch_power':20}]}
def payload(doc=None):
    doc=report() if doc is None else doc
    return {'import_id':str(uuid.uuid4()),'stage':'synthesis','filename':'primepower.json','tool_version':doc.get('tool_version','T-2025.06'),'design_revision':'rev-power','scenario':'func-ss','source_text':json.dumps(doc)}

def attest_power(body, project_id, secret='power-collector-secret-with-at-least-32-bytes'):
    now=datetime.now(timezone.utc);document=json.loads(body['source_text'])
    value={'format':'signoff/coverage-attestation/v1','attestation_id':body['import_id'],'key_id':'qa-power-collector',
      'issued_at':now.isoformat(),'expires_at':(now+timedelta(hours=1)).isoformat(),'project_id':project_id,
      'stage':body['stage'],'domain':'glitch_power','design_revision':body['design_revision'],
      'source_sha256':hashlib.sha256(body['source_text'].encode()).hexdigest(),'tool':document['tool'],
      'tool_version':body['tool_version'],'scenario':body['scenario'],'claims':{claim:True for claim in REQUIRED_POWER_CLAIMS},'signature':'0'*64}
    parsed=CoverageAttestationPayload.model_validate(value);value['signature']=hmac.new(secret.encode(),canonical_payload(parsed),hashlib.sha256).hexdigest();return value

def test_parser_normalizes_and_checks_components():
    result=parse_commercial_power(json.dumps(report()))
    assert result['status']=='failed' and result['metrics']['total_power_mw']==1
    assert result['metrics']['glitch_power_mw']==.25 and result['metrics']['glitch_share']==.25
    assert result['metrics']['violating_hierarchy_rows']==1
    changed=report(); changed['hierarchy'][0]['glitch_power']=100
    assert parse_commercial_power(json.dumps(changed))['items'][0]['fingerprint']==result['items'][0]['fingerprint']
    clean=report('Cadence Joules'); clean['summary']['glitch_power']=100; clean['hierarchy'][0]['glitch_power']=50
    assert parse_commercial_power(json.dumps(clean))['status']=='incomplete'

@pytest.mark.parametrize('field,value',[('format','bad'),('tool','bad'),('power_unit','kW'),('glitch_share_limit',2),('hierarchy',[{}])])
def test_invalid_reports(field,value):
    doc=copy.deepcopy(report());doc[field]=value
    with pytest.raises(ValueError):parse_commercial_power(json.dumps(doc))

def test_rejects_inconsistent_totals_glitch_and_duplicates():
    for mutate in ['total','glitch','duplicate']:
        doc=copy.deepcopy(report())
        if mutate=='total':doc['summary']['total_power']=999
        elif mutate=='glitch':doc['summary']['glitch_power']=800
        else:doc['hierarchy'].append(copy.deepcopy(doc['hierarchy'][0]))
        with pytest.raises(ValueError):parse_commercial_power(json.dumps(doc))

def test_import_evidence_breakdown_violation_retry_auth(accounts):
    _,ids,login=accounts; path=f"/projects/{ids['project']}/imports/commercial-power"; body=payload()
    viewer,editor,outsider=login('viewer'),login('editor'),login('outsider')
    assert viewer.post(path+'/preview',json=body).status_code==403 and outsider.post(path,json=body).status_code==404
    assert editor.post(path+'/preview',json=body).json()['metrics']['glitch_share']==.25
    response=editor.post(path,json=body);assert response.status_code==201,response.text;run=response.json()
    assert run['domain']=='glitch_power' and run['evidence_source']=='commercial_power_report' and run['result_locked']
    assert editor.post(path,json=body).json()['id']==run['id']
    assert editor.post(path,json={**body,'scenario':'changed'}).status_code==409
    evidence=viewer.get(f"/runs/{run['id']}/evidence").json();assert evidence['source_sha256']==hashlib.sha256(body['source_text'].encode()).hexdigest()
    violations=viewer.get(f"/runs/{run['id']}/violations").json();assert len(violations)==2 and all(v['check_name'].startswith('primepower/') for v in violations)
    page=viewer.get(f"/runs/{run['id']}/power-breakdown").json();assert page['reported_total']==2 and page['violated_total']==1
    assert page['items'][0]['path']=='TOP/u_cpu'
    assert viewer.get(f"/runs/{run['id']}/power-breakdown?status=met").json()['total']==1
    assert outsider.get(f"/runs/{run['id']}/power-breakdown").status_code==404
    assert editor.patch(f"/runs/{run['id']}",json={'status':'passed'}).status_code==409
    gate=viewer.get(f"/projects/{ids['project']}/signoff-status?stage=synthesis").json();power=next(x for x in gate['domains'] if x['domain']=='glitch_power')
    assert not power['ready'] and 'activity and mode coverage' in power['reason']

def test_trusted_power_attestation_establishes_coverage(accounts,monkeypatch):
    secret='power-collector-secret-with-at-least-32-bytes';monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS',json.dumps({'qa-power-collector':{'secret':secret,'domains':['glitch_power']}}))
    _,ids,login=accounts;doc=report();doc['summary']['glitch_power']=100;doc['hierarchy'][0]['glitch_power']=50
    body=payload(doc);body['coverage_attestation']=attest_power(body,ids['project'],secret);path=f"/projects/{ids['project']}/imports/commercial-power";editor=login('editor')
    preview=editor.post(path+'/preview',json=body);assert preview.status_code==200,preview.text;assert preview.json()['status']=='passed'
    run=editor.post(path,json=body).json();assert run['status']=='passed'
    power=next(x for x in editor.get(f"/projects/{ids['project']}/signoff-status?stage=synthesis").json()['domains'] if x['domain']=='glitch_power');assert power['ready']
    candidate=payload(doc);candidate['coverage_attestation']=attest_power(candidate,ids['project'],secret);candidate_run=editor.post(path,json=candidate).json()
    comparison=editor.get(f"/projects/{ids['project']}/run-comparison",params={'baseline_run_id':run['id'],'candidate_run_id':candidate_run['id']}).json();assert comparison['partial'] is False
    monkeypatch.delenv('SIGNOFF_COVERAGE_HMAC_KEYS');assert editor.post(path,json=body).json()['id']==run['id']

def test_invalid_or_failing_power_attestation_stays_blocked(accounts,monkeypatch):
    secret='power-collector-secret-with-at-least-32-bytes';monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS',json.dumps({'qa-power-collector':{'secret':secret,'domains':['glitch_power']}}))
    _,ids,login=accounts;editor=login('editor');path=f"/projects/{ids['project']}/imports/commercial-power"
    bad=payload();bad['coverage_attestation']=attest_power(bad,ids['project'],secret);bad['coverage_attestation']['claims'].pop('power_models_complete');assert editor.post(path+'/preview',json=bad).status_code==422
    failing=payload();failing['coverage_attestation']=attest_power(failing,ids['project'],secret);preview=editor.post(path+'/preview',json=failing);assert preview.status_code==200 and preview.json()['status']=='failed'
