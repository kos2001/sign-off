import copy
import hashlib
import json

import pytest
from pydantic import ValidationError
from app.db import SessionLocal
from app.models import SignoffRun
from app.services.rtl import tools
from app.services.rtl.artifacts import StructureArtifact, parse_structure, netlist_metadata_only
from app.services.rtl.worker_client import WorkerResult
from test_auth import accounts
from test_report_import import project
from test_rtl_top_module import MULTI_RTL
from test_rtl_worker_client import events


def artifact(text):
    return {'format':'yosys-json/v1','text':text,'sha256':hashlib.sha256(text.encode()).hexdigest(),'byte_length':len(text.encode())}


def sample():
    return {'modules':{'top':{'ports':{'a':{'direction':'input','bits':[2,'0','1','x','z']}},'cells':{},'netnames':{'a':{'bits':[2]}}}}}


@pytest.mark.parametrize('text', [
    '{}', '{', '{"modules":{},"modules":{}}',
    '{"modules":{"top":{"ports":{},"cells":{},"netnames":{},"extra":NaN}}}',
    '{"modules":{"top":{"ports":{},"cells":{},"netnames":{},"extra":1e400}}}',
    '{"modules":{"\\ud800":{"ports":{},"cells":{},"netnames":{}}}}',
])
def test_invalid_structure_json_rejected(text):
    with pytest.raises((ValidationError,ValueError)): StructureArtifact.model_validate(artifact(text))


@pytest.mark.parametrize('bit',[True,-1,1.5,2**53,'unknown',None,[]])
def test_invalid_connection_bits_rejected(bit):
    data=sample();data['modules']['top']['ports']['a']['bits']=[bit]
    with pytest.raises(ValidationError): StructureArtifact.model_validate(artifact(json.dumps(data)))


def test_structure_worker_checks_hash_top_and_status():
    data=artifact(json.dumps(sample()))
    result=events()[-1]['result'];result['structure']=data
    assert WorkerResult.model_validate(result).structure.sha256==data['sha256']
    for corrupt in [{**data,'sha256':'0'*64},{**data,'byte_length':False}]:
        with pytest.raises(ValidationError): WorkerResult.model_validate({**result,'structure':corrupt})
    for changed in [{'module':'absent'},{'structure_error':'capture failed'}]:
        with pytest.raises(ValidationError): WorkerResult.model_validate({**result,**changed})
    result['stages'][2]['status']='fail'
    with pytest.raises(ValidationError): WorkerResult.model_validate(result)
    summary=netlist_metadata_only({'structure':data})
    assert 'text' not in summary['structure'] and 'text' in data


@pytest.mark.skipif(not tools.yosys_available(),reason='Yosys required')
def test_actual_hierarchy_connections():
    result=tools.synthesize(MULTI_RTL,top_module='chip_top')
    assert result.ok and result.structure and result.structure_error is None
    modules=parse_structure(result.structure['text'])['modules']
    top=modules['chip_top'];cell=top['cells']['u_helper']
    assert cell['type']=='helper'
    assert cell['connections']['a']==top['ports']['a']['bits']
    assert cell['connections']['y']==top['ports']['y']['bits']
    assert len(modules['helper']['cells'])==1


@pytest.mark.skipif(not tools.yosys_available(),reason='Yosys required')
def test_structure_capture_failure_preserves_existing_synthesis_result(monkeypatch):
    read=tools.read_regular_output
    def missing(path,limit):
        if path.name=='structure.json': raise OSError('missing structure')
        return read(path,limit)
    monkeypatch.setattr(tools,'read_regular_output',missing)
    result=tools.synthesize(MULTI_RTL,top_module='chip_top')
    assert result.ok and result.netlist and result.structure is None and result.structure_error


def saved(client,pid):
    response=client.post('/analysis/rtl-signoff',json={'project_id':pid,'code':MULTI_RTL,'top_module':'chip_top'})
    assert response.status_code==200
    return response.json()


@pytest.mark.skipif(not tools.yosys_available(),reason='Yosys required')
def test_structure_endpoint_integrity_and_immutability(client):
    pid=project(client);result=saved(client,pid);rid=result['run_id']
    before=client.get(f'/runs/{rid}/evidence').json()
    response=client.get(f'/runs/{rid}/evidence/structure')
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert response.json()['design']==json.loads(result['structure']['text'])
    assert response.json()['structure_sha256']==result['structure']['sha256']
    assert client.get(f'/runs/{rid}/evidence').json()==before
    bundle=client.get(f'/projects/{pid}/signoff-status/export?stage=rtl').json()
    assert 'text' not in next(row for row in bundle['runs'] if row['id']==rid)['evidence']['result']['structure']


@pytest.mark.skipif(not tools.yosys_available(),reason='Yosys required')
@pytest.mark.parametrize('damage',['source','hash','top','stage','missing'])
def test_structure_endpoint_rejects_corruption(client,damage):
    rid=saved(client,project(client))['run_id']
    with SessionLocal() as db:
        evidence=db.get(SignoffRun,rid).evidence;data=copy.deepcopy(evidence.result)
        if damage=='source': evidence.source_text+='bad'
        elif damage=='hash': data['structure']['sha256']='0'*64
        elif damage=='top': data['module']='absent'
        elif damage=='stage': data['stages'][2]['status']='fail'
        else: data.pop('structure')
        evidence.result=data;db.commit()
    response=client.get(f'/runs/{rid}/evidence/structure')
    assert response.status_code==409 and 'design' not in response.json()


@pytest.mark.skipif(not tools.yosys_available(),reason='Yosys required')
def test_structure_project_permissions(accounts):
    _,ids,login=accounts
    rid=saved(login('editor'),ids['project'])['run_id']
    assert login('viewer').get(f'/runs/{rid}/evidence/structure').status_code==200
    assert login('outsider').get(f'/runs/{rid}/evidence/structure').status_code==404
