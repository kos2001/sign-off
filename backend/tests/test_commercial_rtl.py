import copy,hashlib,json,uuid,pytest
from app.services.commercial_rtl import parse_commercial_rtl
from test_auth import accounts
def report(tool='Synopsys VCS'):
 return {'format':'signoff/commercial-rtl-regression/v1','tool':tool,'tool_version':'V-2025.06','compile_status':'passed','compile_log_excerpt':'compile ok','tests':[{'name':'smoke_boot','status':'passed','duration_ms':12.5,'seed':42,'assertions':{'passed':20,'failed':0,'disabled':1},'log_excerpt':'PASS'},{'name':'cache_random','status':'failed','duration_ms':30,'seed':99,'assertions':{'passed':10,'failed':2,'disabled':0},'log_excerpt':'assertion failed'}]}
def payload(d=None):
 d=report()if d is None else d;return {'import_id':str(uuid.uuid4()),'stage':'rtl','filename':'vcs-regression.json','tool_version':d.get('tool_version','V-2025.06'),'design_revision':'rev-rtl','scenario':'nightly-seed-set','source_text':json.dumps(d)}
def test_parser_metrics_identity_and_clean_state():
 r=parse_commercial_rtl(json.dumps(report()));assert r['status']=='failed'and r['metrics']=={'reported_tests':2,'passed_tests':1,'failed_tests':1,'skipped_tests':0,'failed_assertions':2,'duration_ms':42.5}
 changed=report();changed['tests'][0]['duration_ms']=99;assert parse_commercial_rtl(json.dumps(changed))['items'][0]['fingerprint']==r['items'][0]['fingerprint']
 clean=report('Cadence Xcelium');clean['tests']=clean['tests'][:1];assert parse_commercial_rtl(json.dumps(clean))['status']=='incomplete'
@pytest.mark.parametrize('k,v',[('format','bad'),('tool','bad'),('compile_status','unknown'),('tests',[{}])])
def test_invalid_reports(k,v):
 d=copy.deepcopy(report());d[k]=v
 with pytest.raises(ValueError):parse_commercial_rtl(json.dumps(d))
def test_rejects_duplicate_and_inconsistent_assertions():
 for d in [lambda x:x['tests'].append(copy.deepcopy(x['tests'][0])),lambda x:x['tests'][0]['assertions'].__setitem__('failed',1)]:
  doc=report();d(doc)
  with pytest.raises(ValueError):parse_commercial_rtl(json.dumps(doc))
def test_import_regression_evidence_violation_auth_gate(accounts):
 _,ids,login=accounts;path=f"/projects/{ids['project']}/imports/commercial-rtl";body=payload();viewer,editor,outsider=login('viewer'),login('editor'),login('outsider')
 assert viewer.post(path+'/preview',json=body).status_code==403 and outsider.post(path,json=body).status_code==404
 assert editor.post(path+'/preview',json=body).json()['metrics']['failed_tests']==1
 response=editor.post(path,json=body);assert response.status_code==201,response.text;run=response.json();assert run['domain']=='rtl'and run['evidence_source']=='commercial_rtl_report'and run['result_locked']
 assert editor.post(path,json=body).json()['id']==run['id']and editor.post(path,json={**body,'scenario':'changed'}).status_code==409
 ev=viewer.get(f"/runs/{run['id']}/evidence").json();assert ev['source_sha256']==hashlib.sha256(body['source_text'].encode()).hexdigest()
 violations=viewer.get(f"/runs/{run['id']}/violations").json();assert len(violations)==1 and violations[0]['check_name'].startswith('vcs/test/')
 page=viewer.get(f"/runs/{run['id']}/rtl-regression").json();assert page['reported_total']==2 and page['summary']['failed_assertions']==2
 assert viewer.get(f"/runs/{run['id']}/rtl-regression?status=failed").json()['total']==1 and outsider.get(f"/runs/{run['id']}/rtl-regression").status_code==404
 gate=viewer.get(f"/projects/{ids['project']}/signoff-status?stage=rtl").json();rtl=next(x for x in gate['domains']if x['domain']=='rtl');assert not rtl['ready']and'captured ladder evidence'in rtl['reason']
