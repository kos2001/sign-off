import copy,hashlib,hmac,json,uuid
from datetime import datetime,timedelta,timezone
import pytest
from app.routers.imports import CoverageAttestationPayload
from app.services.commercial_lec import parse_commercial_lec
from app.services.coverage_attestation import REQUIRED_LEC_CLAIMS,canonical_payload
from test_auth import accounts

def report(tool='Synopsys Formality'):
 return{'format':'signoff/commercial-lec/v1','tool':tool,'tool_version':'T-2025.06','reference_top':'CHIP','implementation_top':'CHIP','status':'non_equivalent','summary':{'reference_compare_points':100,'implementation_compare_points':100,'matched_points':98,'failing_points':1,'aborted_points':1,'unreachable_points':0},'failures':[{'kind':'non_equivalent','name':'compare/M42','severity':'critical','reference_object':'r:/WORK/CHIP/M42','implementation_object':'i:/WORK/CHIP/M42','message':'Logic cone differs.'},{'kind':'aborted','name':'compare/state_q','severity':'error','implementation_object':'i:/WORK/CHIP/state_q','message':'Compare point aborted.'}]}
def equivalent(tool='Synopsys Formality'):
 d=report(tool);d['status']='equivalent';d['failures']=[];d['summary'].update(matched_points=100,failing_points=0,aborted_points=0);return d
def payload(doc=None):
 doc=doc or report();return{'import_id':str(uuid.uuid4()),'stage':'synthesis','filename':'lec.json','tool_version':doc.get('tool_version','T-2025.06'),'design_revision':'rev-lec','scenario':'rtl-vs-netlist','source_text':json.dumps(doc)}
def attest(body,pid,secret):
 now=datetime.now(timezone.utc);doc=json.loads(body['source_text']);v={'format':'signoff/coverage-attestation/v1','attestation_id':body['import_id'],'key_id':'qa-lec','issued_at':now.isoformat(),'expires_at':(now+timedelta(hours=1)).isoformat(),'project_id':pid,'stage':body['stage'],'domain':'lec','design_revision':body['design_revision'],'source_sha256':hashlib.sha256(body['source_text'].encode()).hexdigest(),'tool':doc['tool'],'tool_version':body['tool_version'],'scenario':body['scenario'],'claims':{x:True for x in REQUIRED_LEC_CLAIMS},'signature':'0'*64};parsed=CoverageAttestationPayload.model_validate(v);v['signature']=hmac.new(secret.encode(),canonical_payload(parsed),hashlib.sha256).hexdigest();return v

def test_parser_and_contradictions():
 r=parse_commercial_lec(json.dumps(report()));assert r['status']=='failed'and r['metrics']['reported_failures']==2
 assert parse_commercial_lec(json.dumps(equivalent('Cadence Conformal')))['status']=='incomplete'
 d=equivalent();d['failures']=report()['failures']
 with pytest.raises(ValueError,match='equivalent'):parse_commercial_lec(json.dumps(d))
 d=report();d['failures']=[]
 with pytest.raises(ValueError,match='requires'):parse_commercial_lec(json.dumps(d))
@pytest.mark.parametrize('field,value',[('format','bad'),('tool','bad'),('status','bad'),('summary',{}),('failures',[{}])])
def test_invalid(field,value):
 d=copy.deepcopy(report());d[field]=value
 with pytest.raises(ValueError):parse_commercial_lec(json.dumps(d))

def test_import_explorer_and_unsigned_gate(accounts):
 _,ids,login=accounts;editor=login('editor');viewer=login('viewer');body=payload();path=f"/projects/{ids['project']}/imports/commercial-lec"
 assert editor.post(path+'/preview',json=body).status_code==200
 response=editor.post(path,json=body);assert response.status_code==201,response.text;run=response.json();assert run['domain']=='lec'and run['result_locked']
 assert editor.post(path,json=body).json()['id']==run['id'];assert editor.post(path,json={**body,'scenario':'changed'}).status_code==409
 assert len(viewer.get(f"/runs/{run['id']}/violations").json())==2
 page=viewer.get(f"/runs/{run['id']}/lec-failures").json();assert page['reported_total']==2 and page['lec_status']=='non_equivalent'
 assert viewer.get(f"/runs/{run['id']}/lec-failures?kind=aborted").json()['total']==1
 gate=viewer.get(f"/projects/{ids['project']}/signoff-status?stage=synthesis").json();lec=next(x for x in gate['domains']if x['domain']=='lec');assert not lec['ready']and'full equivalence coverage'in lec['reason']

def test_trusted_equivalent_and_invalid_attestation(accounts,monkeypatch):
 secret='lec-collector-secret-with-at-least-32-bytes';monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS',json.dumps({'qa-lec':{'secret':secret,'domains':['lec']}}));_,ids,login=accounts;editor=login('editor');path=f"/projects/{ids['project']}/imports/commercial-lec"
 body=payload(equivalent());body['coverage_attestation']=attest(body,ids['project'],secret);preview=editor.post(path+'/preview',json=body);assert preview.status_code==200 and preview.json()['status']=='passed';run=editor.post(path,json=body).json();assert run['status']=='passed'
 lec=next(x for x in editor.get(f"/projects/{ids['project']}/signoff-status?stage=synthesis").json()['domains']if x['domain']=='lec');assert lec['ready']
 bad=payload(equivalent());bad['coverage_attestation']=attest(bad,ids['project'],secret);bad['coverage_attestation']['claims'].pop('comparison_complete');assert editor.post(path+'/preview',json=bad).status_code==422
