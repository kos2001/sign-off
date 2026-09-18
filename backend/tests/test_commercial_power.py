import copy, hashlib, json, uuid
import pytest
from app.services.commercial_power import parse_commercial_power
from test_auth import accounts

def report(tool='Synopsys PrimePower'):
    return {'format':'signoff/commercial-power/v1','tool':tool,'tool_version':'T-2025.06','power_unit':'uW','glitch_share_limit':.2,
      'summary':{'total_power':1000,'internal_power':200,'switching_power':700,'leakage_power':100,'glitch_power':250},
      'hierarchy':[{'path':'TOP/u_cpu','total_power':600,'internal_power':100,'switching_power':450,'leakage_power':50,'glitch_power':150},
                   {'path':'TOP/u_mem','total_power':400,'internal_power':100,'switching_power':250,'leakage_power':50,'glitch_power':20}]}
def payload(doc=None):
    doc=report() if doc is None else doc
    return {'import_id':str(uuid.uuid4()),'stage':'synthesis','filename':'primepower.json','tool_version':doc.get('tool_version','T-2025.06'),'design_revision':'rev-power','scenario':'func-ss','source_text':json.dumps(doc)}

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
