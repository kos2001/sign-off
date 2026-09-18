from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Query
from sqlalchemy.orm import Session
from ..db import get_db
from ..schemas import RunOut
from .runs import get_run_or_404
router=APIRouter(tags=['rtl-regressions'])
@router.get('/runs/{run_id}/rtl-regression')
def regression(run_id:int,status:Literal['all','passed','failed','skipped']='all',q:str=Query('',max_length=200),offset:int=Query(0,ge=0,le=5000),limit:int=Query(25,ge=1,le=100),db:Session=Depends(get_db)):
 run=get_run_or_404(run_id,db)
 if run.evidence_source!='commercial_rtl_report':raise HTTPException(409,'this run has no imported RTL regression')
 result=run.evidence.result;query=q.casefold();items=[x for x in result['items']if(status=='all'or x['status']==status)and(not query or query in x['name'].casefold()or query in x['log_excerpt'].casefold())]
 return {'run':RunOut.model_validate(run),'metadata':result.get('metadata',{}),'source_sha256':run.evidence.source_sha256,'design_revision':run.evidence.design_revision,'compile_status':result['compile_status'],'compile_log_excerpt':result['compile_log_excerpt'],'reported_total':len(result['items']),'total':len(items),'offset':offset,'limit':limit,'summary':result['metrics'],'items':items[offset:offset+limit]}
