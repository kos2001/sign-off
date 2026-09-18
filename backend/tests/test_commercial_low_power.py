import copy,hashlib,hmac,json,uuid
from datetime import datetime,timedelta,timezone
import pytest
from app.routers.imports import CoverageAttestationPayload
from app.services.commercial_low_power import parse_commercial_low_power
from app.services.coverage_attestation import REQUIRED_LOW_POWER_CLAIMS,canonical_payload
from test_auth import accounts

def report(tool='Synopsys VC LP'):
 return {'format':'signoff/commercial-low-power/v1','tool':tool,'tool_version':'T-2025.06','top':'CHIP','status':'violations','summary':{'power_domains':4,'power_states':8,'domain_crossings':19,'checked_rules':650},'findings':[{'kind':'isolation','severity':'critical','rule':'LP_ISO_MISSING','name':'missing isolation on PD_GPU to PD_AON','source_domain':'PD_GPU','destination_domain':'PD_AON','object':'u_gpu/status_o','message':'Isolation cell is missing on a switchable-to-always-on crossing.'}]}
def clean(tool='Synopsys VC LP'):
 d=report(tool);d['status']='clean';d['findings']=[];return d
def payload(doc=None):
 doc=doc or report();return {'import_id':str(uuid.uuid4()),'stage':'final','filename':'low-power.json','tool_version':doc.get('tool_version','T-2025.06'),'design_revision':'rev-lp','scenario':'upf-full-chip','source_text':json.dumps(doc)}
def attest(body,pid,secret):
 now=datetime.now(timezone.utc);doc=json.loads(body['source_text']);v={'format':'signoff/coverage-attestation/v1','attestation_id':body['import_id'],'key_id':'qa-low-power','issued_at':now.isoformat(),'expires_at':(now+timedelta(hours=1)).isoformat(),'project_id':pid,'stage':body['stage'],'domain':'low_power','design_revision':body['design_revision'],'source_sha256':hashlib.sha256(body['source_text'].encode()).hexdigest(),'tool':doc['tool'],'tool_version':body['tool_version'],'scenario':body['scenario'],'claims':{x:True for x in REQUIRED_LOW_POWER_CLAIMS},'signature':'0'*64};parsed=CoverageAttestationPayload.model_validate(v);v['signature']=hmac.new(secret.encode(),canonical_payload(parsed),hashlib.sha256).hexdigest();return v

def test_parser_rejects_contradictory_status_and_shape():
 parsed=parse_commercial_low_power(json.dumps(report()));assert parsed['status']=='failed'and parsed['metrics']['blocking_findings']==1
 assert parse_commercial_low_power(json.dumps(clean('Cadence Conformal Low Power')))['status']=='incomplete'
 d=clean();d['findings']=report()['findings']
 with pytest.raises(ValueError,match='clean'):parse_commercial_low_power(json.dumps(d))
 d=report();d['findings'][0]['severity']='warning'
 with pytest.raises(ValueError,match='violations'):parse_commercial_low_power(json.dumps(d))
@pytest.mark.parametrize('field,value',[('format','bad'),('tool','bad'),('status','bad'),('summary',{}),('findings',[{}])])
def test_invalid_report(field,value):
 d=copy.deepcopy(report());d[field]=value
 with pytest.raises(ValueError):parse_commercial_low_power(json.dumps(d))
def test_import_explorer_idempotency_and_unsigned_scope(accounts):
 _,ids,login=accounts;editor,viewer=login('editor'),login('viewer');body=payload();path=f"/projects/{ids['project']}/imports/commercial-low-power"
 assert editor.post(path+'/preview',json=body).status_code==200
 response=editor.post(path,json=body);assert response.status_code==201,response.text;run=response.json();assert run['domain']=='low_power'and run['result_locked']
 assert editor.post(path,json=body).json()['id']==run['id'];assert editor.post(path,json={**body,'scenario':'changed'}).status_code==409
 assert len(viewer.get(f"/runs/{run['id']}/violations").json())==1
 page=viewer.get(f"/runs/{run['id']}/low-power-findings?kind=isolation&q=PD_GPU").json();assert page['reported_total']==1 and page['total']==1
def test_trusted_clean_and_invalid_attestation(accounts,monkeypatch):
 secret='low-power-collector-secret-at-least-32-bytes';monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS',json.dumps({'qa-low-power':{'secret':secret,'domains':['low_power']}}));_,ids,login=accounts;editor=login('editor');path=f"/projects/{ids['project']}/imports/commercial-low-power"
 body=payload(clean('Cadence Conformal Low Power'));body['coverage_attestation']=attest(body,ids['project'],secret);preview=editor.post(path+'/preview',json=body);assert preview.status_code==200 and preview.json()['status']=='passed';run=editor.post(path,json=body).json();assert run['status']=='passed'
 bad=payload(clean());bad['coverage_attestation']=attest(bad,ids['project'],secret);bad['coverage_attestation']['claims'].pop('pg_checks_complete');assert editor.post(path+'/preview',json=bad).status_code==422
