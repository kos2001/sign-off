from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Query
from sqlalchemy.orm import Session
from ..db import get_db
from ..schemas import RunOut
from .runs import get_run_or_404
router=APIRouter(tags=['dft']);Kind=Literal['all','scan_chain','dft_rule','coverage','aborted_fault','pattern_validation']
@router.get('/runs/{run_id}/dft-findings')
def findings(run_id:int,kind:Kind='all',q:str=Query('',max_length=200),offset:int=Query(0,ge=0,le=5000),limit:int=Query(25,ge=1,le=100),db:Session=Depends(get_db)):
 run=get_run_or_404(run_id,db)
 if run.evidence_source!='commercial_dft_report':raise HTTPException(409,'this run has no imported DFT result')
 result=run.evidence.result;query=q.casefold();items=[x for x in result['items']if(kind=='all'or x['kind']==kind)and(not query or any(query in(x.get(f)or'').casefold()for f in('rule','name','location','message')))]
 return{'run':RunOut.model_validate(run),'metadata':result.get('metadata',{}),'source_sha256':run.evidence.source_sha256,'design_revision':run.evidence.design_revision,'dft_status':result['dft_status'],'top':result['top'],'error_message':result.get('error_message'),'summary':result['summary'],'fault_models':result['fault_models'],'reported_total':len(result['items']),'total':len(items),'offset':offset,'limit':limit,'items':items[offset:offset+limit]}
