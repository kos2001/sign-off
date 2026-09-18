import copy,hashlib,hmac,json,uuid
from datetime import datetime,timedelta,timezone
import pytest
from app.routers.imports import CoverageAttestationPayload
from app.services.commercial_dft import parse_commercial_dft
from app.services.coverage_attestation import REQUIRED_DFT_CLAIMS,canonical_payload
from test_auth import accounts

def report(tool='Synopsys TestMAX ATPG'):
 return{'format':'signoff/commercial-dft/v1','tool':tool,'tool_version':'T-2025.06','top':'CHIP','status':'failed','summary':{'scan_chains':32,'scan_cells':10000,'broken_chains':1,'dft_rule_violations':0},'fault_models':[{'name':'stuck_at','total_faults':1000,'detected_faults':850,'untestable_faults':100,'aborted_faults':0,'coverage_percent':850/900*100,'required_coverage_percent':99.0,'pattern_count':120}],'findings':[{'kind':'scan_chain','rule':'SCAN_CHAIN_BROKEN','name':'chain_7','severity':'critical','location':'scan_out[7]','message':'Scan chain continuity check failed.'}]}
def passed(tool='Synopsys TestMAX ATPG'):
 d=report(tool);d['status']='passed';d['summary']['broken_chains']=0;d['fault_models'][0].update(detected_faults=900,coverage_percent=100.0);d['findings']=[];return d
def payload(doc=None):
 doc=doc or report();return{'import_id':str(uuid.uuid4()),'stage':'synthesis','filename':'dft.json','tool_version':doc.get('tool_version','T-2025.06'),'design_revision':'rev-dft','scenario':'scan-atpg-signoff','source_text':json.dumps(doc)}
def attest(body,pid,secret):
 now=datetime.now(timezone.utc);doc=json.loads(body['source_text']);v={'format':'signoff/coverage-attestation/v1','attestation_id':body['import_id'],'key_id':'qa-dft','issued_at':now.isoformat(),'expires_at':(now+timedelta(hours=1)).isoformat(),'project_id':pid,'stage':body['stage'],'domain':'dft','design_revision':body['design_revision'],'source_sha256':hashlib.sha256(body['source_text'].encode()).hexdigest(),'tool':doc['tool'],'tool_version':body['tool_version'],'scenario':body['scenario'],'claims':{x:True for x in REQUIRED_DFT_CLAIMS},'signature':'0'*64};parsed=CoverageAttestationPayload.model_validate(v);v['signature']=hmac.new(secret.encode(),canonical_payload(parsed),hashlib.sha256).hexdigest();return v

def test_parser_recomputes_coverage_and_rejects_contradictions():
 r=parse_commercial_dft(json.dumps(report()));assert r['status']=='failed'and r['metrics']['violated_fault_models']==1
 assert parse_commercial_dft(json.dumps(passed('Siemens Tessent TestKompress')))['status']=='incomplete'
 d=passed();d['fault_models'][0]['coverage_percent']=99
 with pytest.raises(ValueError,match='does not match'):parse_commercial_dft(json.dumps(d))
 d=passed();d['summary']['broken_chains']=1
 with pytest.raises(ValueError,match='passed'):parse_commercial_dft(json.dumps(d))
@pytest.mark.parametrize('field,value',[('format','bad'),('tool','bad'),('status','bad'),('summary',{}),('fault_models',[]),('findings',[{}])])
def test_invalid(field,value):
 d=copy.deepcopy(report());d[field]=value
 with pytest.raises(ValueError):parse_commercial_dft(json.dumps(d))

def test_import_explorer_and_unsigned_gate(accounts):
 _,ids,login=accounts;editor=login('editor');viewer=login('viewer');body=payload();path=f"/projects/{ids['project']}/imports/commercial-dft"
 assert editor.post(path+'/preview',json=body).status_code==200
 response=editor.post(path,json=body);assert response.status_code==201,response.text;run=response.json();assert run['domain']=='dft'and run['result_locked']
 assert editor.post(path,json=body).json()['id']==run['id'];assert editor.post(path,json={**body,'scenario':'changed'}).status_code==409
 assert len(viewer.get(f"/runs/{run['id']}/violations").json())==3
 page=viewer.get(f"/runs/{run['id']}/dft-findings").json();assert page['reported_total']==1 and page['fault_models'][0]['violated']
 gate=viewer.get(f"/projects/{ids['project']}/signoff-status?stage=synthesis").json();dft=next(x for x in gate['domains']if x['domain']=='dft');assert not dft['ready']and'full scan and ATPG coverage'in dft['reason']

def test_trusted_pass_and_invalid_attestation(accounts,monkeypatch):
 secret='dft-collector-secret-with-at-least-32-bytes';monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS',json.dumps({'qa-dft':{'secret':secret,'domains':['dft']}}));_,ids,login=accounts;editor=login('editor');path=f"/projects/{ids['project']}/imports/commercial-dft"
 body=payload(passed('Cadence Modus ATPG'));body['coverage_attestation']=attest(body,ids['project'],secret);preview=editor.post(path+'/preview',json=body);assert preview.status_code==200 and preview.json()['status']=='passed';run=editor.post(path,json=body).json();assert run['status']=='passed'
 dft=next(x for x in editor.get(f"/projects/{ids['project']}/signoff-status?stage=synthesis").json()['domains']if x['domain']=='dft');assert dft['ready']
 bad=payload(passed());bad['coverage_attestation']=attest(bad,ids['project'],secret);bad['coverage_attestation']['claims'].pop('pattern_validation_complete');assert editor.post(path+'/preview',json=bad).status_code==422
