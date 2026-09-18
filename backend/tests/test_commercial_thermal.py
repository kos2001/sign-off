import copy,hashlib,json,uuid,pytest
from app.services.commercial_thermal import parse_commercial_thermal
from test_auth import accounts
def report(tool='Cadence Celsius'):
 return {'format':'signoff/commercial-thermal/v1','tool':tool,'tool_version':'23.1','temperature_unit':'K','coordinate_unit':'mm','top_cell':'CHIP','hotspots':[{'component':'CPU','layer':'die0','temperature':383.15,'limit':378.15,'severity':'critical','x':1.5,'y':2,'z':.1,'message':'CPU hotspot'},{'component':'SRAM','temperature':363.15,'limit':378.15,'severity':'warning','x':.5,'y':.6}]}
def payload(doc=None):
 doc=report()if doc is None else doc;return {'import_id':str(uuid.uuid4()),'stage':'final','filename':'celsius.json','tool_version':doc.get('tool_version','23.1'),'design_revision':'rev-thermal','scenario':'full-load-ambient-45c','source_text':json.dumps(doc)}
def test_parser_normalizes_temperature_coordinates_identity():
 r=parse_commercial_thermal(json.dumps(report()));assert r['status']=='failed' and r['metrics']=={'reported_hotspots':2,'violated_hotspots':1,'maximum_temperature_c':110.0};assert r['items'][0]['x_um']=='1500.0' and r['items'][0]['temperature_c']==110
 changed=report();changed['hotspots'][0]['temperature']=370;assert parse_commercial_thermal(json.dumps(changed))['items'][0]['fingerprint']==r['items'][0]['fingerprint']
 empty=report('Ansys Icepak');empty['hotspots']=[];assert parse_commercial_thermal(json.dumps(empty))['status']=='incomplete'
@pytest.mark.parametrize('k,v',[('format','bad'),('tool','bad'),('temperature_unit','F'),('coordinate_unit','m'),('hotspots',[{}])])
def test_invalid_reports(k,v):
 d=copy.deepcopy(report());d[k]=v
 with pytest.raises(ValueError):parse_commercial_thermal(json.dumps(d))
def test_import_explorer_violation_gate_auth(accounts):
 _,ids,login=accounts;path=f"/projects/{ids['project']}/imports/commercial-thermal";body=payload();viewer,editor,outsider=login('viewer'),login('editor'),login('outsider')
 assert viewer.post(path+'/preview',json=body).status_code==403 and outsider.post(path,json=body).status_code==404
 assert editor.post(path+'/preview',json=body).json()['metrics']['maximum_temperature_c']==110
 response=editor.post(path,json=body);assert response.status_code==201,response.text;run=response.json();assert run['domain']=='thermal' and run['evidence_source']=='commercial_thermal_report' and run['result_locked']
 assert editor.post(path,json=body).json()['id']==run['id'] and editor.post(path,json={**body,'scenario':'changed'}).status_code==409
 ev=viewer.get(f"/runs/{run['id']}/evidence").json();assert ev['source_sha256']==hashlib.sha256(body['source_text'].encode()).hexdigest()
 violations=viewer.get(f"/runs/{run['id']}/violations").json();assert len(violations)==1 and violations[0]['check_name'].startswith('celsius/')
 page=viewer.get(f"/runs/{run['id']}/thermal-hotspots").json();assert page['reported_total']==2 and page['violated_total']==1 and page['bounds_um']['zmax']==100
 assert viewer.get(f"/runs/{run['id']}/thermal-hotspots?status=met").json()['total']==1 and outsider.get(f"/runs/{run['id']}/thermal-hotspots").status_code==404
 gate=viewer.get(f"/projects/{ids['project']}/signoff-status?stage=final").json();thermal=next(x for x in gate['domains'] if x['domain']=='thermal');assert not thermal['ready'] and 'full thermal coverage' in thermal['reason']
