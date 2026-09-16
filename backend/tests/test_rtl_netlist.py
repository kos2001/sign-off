import copy
import hashlib
import shutil
import subprocess

import pytest
from pydantic import ValidationError

from app.db import SessionLocal
from app.models import SignoffRun
from app.services.rtl import tools
from app.services.rtl.artifacts import NetlistArtifact, netlist_metadata_only
from app.services.rtl.worker_client import WorkerResult
from test_auth import accounts
from test_report_import import project
from test_rtl_worker_client import events


def artifact(text='module top; endmodule\n'):
    return {'format': 'yosys-generic-verilog/v1', 'text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest(), 'byte_length': len(text.encode())}


@pytest.mark.parametrize('field,value', [('text','corrupt'),('sha256','0'*64),('byte_length',False),('byte_length',0),('format','arbitrary')])
def test_netlist_integrity_rejected_by_worker(field, value):
    result=events()[-1]['result']
    result['netlist']={**artifact(),field:value}
    with pytest.raises(ValidationError): WorkerResult.model_validate(result)


def test_netlist_worker_requires_synthesis_pass_and_preserves_utf8():
    data=artifact('module top; // 한글\nendmodule\n')
    assert NetlistArtifact.model_validate(data).model_dump()==data
    result=events()[-1]['result']; result['netlist']=data
    assert WorkerResult.model_validate(result).netlist.text==data['text']
    result['stages'][2]['status']='fail'
    with pytest.raises(ValidationError): WorkerResult.model_validate(result)


@pytest.mark.skipif(not tools.yosys_available() or not shutil.which('iverilog'), reason='RTL tools required')
def test_real_netlist_recompiles_and_simulates(tmp_path):
    result=tools.synthesize('module top(input a,output y); assign y=~a; endmodule')
    assert result.ok and result.netlist
    netlist=NetlistArtifact.model_validate(result.netlist)
    (tmp_path/'netlist.v').write_bytes(netlist.text.encode())
    (tmp_path/'tb.v').write_text('module tb; reg a; wire y; top dut(a,y); initial begin a=0; #1; if(y!==1) $fatal(1); a=1; #1; if(y!==0) $fatal(1); $finish; end endmodule')
    subprocess.run(['iverilog','-g2012','-s','tb','-o','sim','netlist.v','tb.v'],cwd=tmp_path,check=True,capture_output=True,timeout=10)
    subprocess.run(['vvp','sim'],cwd=tmp_path,check=True,capture_output=True,timeout=10)


def saved(client, pid):
    response=client.post('/analysis/rtl-signoff',json={'project_id':pid,'code':'module top(input a,output y); assign y=~a; endmodule'})
    assert response.status_code==200
    return response.json()


@pytest.mark.skipif(not tools.yosys_available(), reason='Yosys required')
def test_netlist_export_exact_and_read_only(client):
    result=saved(client,project(client)); rid=result['run_id']
    before=client.get(f'/runs/{rid}/evidence').json()
    response=client.get(f'/runs/{rid}/evidence/netlist')
    assert response.status_code==200
    assert response.content==result['netlist']['text'].encode()
    assert response.headers['x-artifact-sha256']==result['netlist']['sha256']
    assert response.headers['content-disposition']==f'attachment; filename="run-{rid}-netlist.v"'
    assert response.headers['cache-control']=='no-store' and response.headers['x-content-type-options']=='nosniff'
    assert client.get(f'/runs/{rid}/evidence').json()==before
    summary=netlist_metadata_only(result)
    assert 'text' not in summary['netlist'] and 'text' in result['netlist']


@pytest.mark.skipif(not tools.yosys_available(), reason='Yosys required')
@pytest.mark.parametrize('damage',['text','hash','stage','missing','source','duplicate_stage'])
def test_netlist_export_fails_closed(client,damage):
    result=saved(client,project(client));rid=result['run_id']
    with SessionLocal() as db:
        evidence=db.get(SignoffRun,rid).evidence
        changed=copy.deepcopy(evidence.result)
        if damage=='missing': changed.pop('netlist')
        elif damage=='source': evidence.source_text+='changed'
        elif damage=='duplicate_stage': changed['stages'].append(copy.deepcopy(changed['stages'][2]))
        elif damage=='stage': changed['stages'][2]['status']='fail'
        elif damage=='hash': changed['netlist']['sha256']='0'*64
        else: changed['netlist']['text']+='bad'
        evidence.result=changed;db.commit()
    response=client.get(f'/runs/{rid}/evidence/netlist')
    assert response.status_code==409 and 'content-disposition' not in response.headers


@pytest.mark.skipif(not tools.yosys_available(), reason='Yosys required')
def test_netlist_export_project_permissions(accounts):
    _,ids,login=accounts
    editor,viewer,outsider=login('editor'),login('viewer'),login('outsider')
    result=saved(editor,ids['project']);rid=result['run_id']
    assert viewer.get(f'/runs/{rid}/evidence/netlist').status_code==200
    assert outsider.get(f'/runs/{rid}/evidence/netlist').status_code==404
    assert viewer.get(f"/runs/{ids['run']}/evidence/netlist").status_code==404


@pytest.mark.skipif(not tools.yosys_available(), reason='Yosys required')
def test_artifact_body_excluded_from_gate_and_ai_inputs(client, monkeypatch):
    from app.routers.run_reviews import snapshot
    pid=project(client); result=saved(client,pid); rid=result['run_id']
    bundle=client.get(f'/projects/{pid}/signoff-status/export?stage=rtl').json()
    exported=next(row for row in bundle['runs'] if row['id']==rid)['evidence']['result']['netlist']
    assert exported['sha256']==result['netlist']['sha256'] and 'text' not in exported
    with SessionLocal() as db:
        _,data=snapshot(db.get(SignoffRun,rid))
        assert 'text' not in data['analysis']['netlist']
    received=[]
    async def review(role,payload,**kwargs):
        received.append(payload)
        return {'available':True,'review':'QA','error':None}
    monkeypatch.setattr('app.routers.agents._run_role',review)
    result['rules']=[{'status':'violation'}]
    response=client.post('/agents/review/rtl',json={'rtl_signoff_result':result})
    assert response.status_code==200 and response.json()['triggered']
    assert len(received)==1 and 'text' not in received[0]['netlist']
    assert 'text' in client.get(f'/runs/{rid}/evidence').json()['result']['netlist']


@pytest.mark.parametrize('body', [
    'pass',
    "Path('netlist.v').write_bytes(b'')",
    "Path('netlist.v').write_bytes(b'\\xff')",
    "Path('netlist.v').write_bytes(b'x' * 1048577)",
    "Path('netlist.v').symlink_to('design.sv')",
    "os.mkfifo('netlist.v')",
])
def test_invalid_netlist_output_never_passes_synthesis(tmp_path,monkeypatch,body):
    from test_rtl_process import fake_tool
    fake_tool(tmp_path,monkeypatch,'yosys',"import os\nfrom pathlib import Path\nPath('stats.json').write_text('{\"design\":{\"num_cells\":0,\"num_cells_by_type\":{}}}')\n"+body)
    result=tools.synthesize('module top; endmodule')
    assert not result.ok and result.netlist is None and result.cells is None
    assert result.execution['exit_code']==0
