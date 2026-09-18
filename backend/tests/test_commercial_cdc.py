import copy,hashlib,hmac,json,uuid
from datetime import datetime,timedelta,timezone
import pytest
from app.routers.imports import CoverageAttestationPayload
from app.services.commercial_cdc import parse_commercial_cdc
from app.services.coverage_attestation import REQUIRED_CDC_CLAIMS,canonical_payload
from test_auth import accounts

def report(tool='Synopsys VC SpyGlass CDC/RDC'):
 return{'format':'signoff/commercial-cdc-rdc/v1','tool':tool,'tool_version':'T-2025.06','top':'CHIP','status':'violations','summary':{'clock_domains':4,'reset_domains':2,'cdc_crossings':12,'rdc_crossings':3},'findings':[{'kind':'cdc','rule':'CDC_UNSYNC_DATA','name':'status crossing','severity':'critical','source_object':'u_src/status_q','destination_object':'u_dst/status_d','source_domain':'clk_a','destination_domain':'clk_b','message':'Unsynchronized data crossing.'},{'kind':'rdc','rule':'RDC_ASYNC_RESET','name':'reset release','severity':'error','source_object':'rst_a_n','destination_object':'u_dst/state_q','source_domain':'reset_a','destination_domain':'reset_b','message':'Reset domain crossing may metastabilize.'}]}
def clean(tool='Synopsys VC SpyGlass CDC/RDC'):
 d=report(tool);d['status']='clean';d['findings']=[];return d
def payload(doc=None):
 doc=doc or report();return{'import_id':str(uuid.uuid4()),'stage':'rtl','filename':'cdc.json','tool_version':doc.get('tool_version','T-2025.06'),'design_revision':'rev-cdc','scenario':'rtl-static-signoff','source_text':json.dumps(doc)}
def attest(body,pid,secret):
 now=datetime.now(timezone.utc);doc=json.loads(body['source_text']);v={'format':'signoff/coverage-attestation/v1','attestation_id':body['import_id'],'key_id':'qa-cdc','issued_at':now.isoformat(),'expires_at':(now+timedelta(hours=1)).isoformat(),'project_id':pid,'stage':body['stage'],'domain':'cdc','design_revision':body['design_revision'],'source_sha256':hashlib.sha256(body['source_text'].encode()).hexdigest(),'tool':doc['tool'],'tool_version':body['tool_version'],'scenario':body['scenario'],'claims':{x:True for x in REQUIRED_CDC_CLAIMS},'signature':'0'*64};parsed=CoverageAttestationPayload.model_validate(v);v['signature']=hmac.new(secret.encode(),canonical_payload(parsed),hashlib.sha256).hexdigest();return v

def test_parser_and_contradictions():
 r=parse_commercial_cdc(json.dumps(report()));assert r['status']=='failed'and r['metrics']['blocking_findings']==2 and r['metrics']['cdc_findings']==1
 assert parse_commercial_cdc(json.dumps(clean('Cadence Jasper CDC')))['status']=='incomplete'
 d=clean();d['findings']=report()['findings']
 with pytest.raises(ValueError,match='clean'):parse_commercial_cdc(json.dumps(d))
 d=report();d['findings']=[]
 with pytest.raises(ValueError,match='must contain'):parse_commercial_cdc(json.dumps(d))
@pytest.mark.parametrize('field,value',[('format','bad'),('tool','bad'),('status','bad'),('summary',{}),('findings',[{}])])
def test_invalid(field,value):
 d=copy.deepcopy(report());d[field]=value
 with pytest.raises(ValueError):parse_commercial_cdc(json.dumps(d))

def test_import_explorer_and_unsigned_gate(accounts):
 _,ids,login=accounts;editor=login('editor');viewer=login('viewer');body=payload();path=f"/projects/{ids['project']}/imports/commercial-cdc"
 assert editor.post(path+'/preview',json=body).status_code==200
 response=editor.post(path,json=body);assert response.status_code==201,response.text;run=response.json();assert run['domain']=='cdc'and run['result_locked']
 assert editor.post(path,json=body).json()['id']==run['id'];assert editor.post(path,json={**body,'scenario':'changed'}).status_code==409
 assert len(viewer.get(f"/runs/{run['id']}/violations").json())==2
 page=viewer.get(f"/runs/{run['id']}/cdc-findings").json();assert page['reported_total']==2 and page['cdc_status']=='violations'
 assert viewer.get(f"/runs/{run['id']}/cdc-findings?kind=rdc").json()['total']==1
 gate=viewer.get(f"/projects/{ids['project']}/signoff-status?stage=rtl").json();cdc=next(x for x in gate['domains']if x['domain']=='cdc');assert not cdc['ready']and'full crossing coverage'in cdc['reason']

def test_trusted_clean_and_invalid_attestation(accounts,monkeypatch):
 secret='cdc-collector-secret-with-at-least-32-bytes';monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS',json.dumps({'qa-cdc':{'secret':secret,'domains':['cdc']}}));_,ids,login=accounts;editor=login('editor');path=f"/projects/{ids['project']}/imports/commercial-cdc"
 body=payload(clean());body['coverage_attestation']=attest(body,ids['project'],secret);preview=editor.post(path+'/preview',json=body);assert preview.status_code==200 and preview.json()['status']=='passed';run=editor.post(path,json=body).json();assert run['status']=='passed'
 cdc=next(x for x in editor.get(f"/projects/{ids['project']}/signoff-status?stage=rtl").json()['domains']if x['domain']=='cdc');assert cdc['ready']
 bad=payload(clean());bad['coverage_attestation']=attest(bad,ids['project'],secret);bad['coverage_attestation']['claims'].pop('rdc_analysis_complete');assert editor.post(path+'/preview',json=bad).status_code==422
