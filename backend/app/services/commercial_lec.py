"""Strict exchange format for commercial logical-equivalence results."""
import hashlib
import json
from .report_import import reject_constant, unique_object
FORMAT='signoff/commercial-lec/v1'; PARSER='commercial-lec-json/v1'
TOOLS={'Synopsys Formality','Cadence Conformal'}
KINDS={'non_equivalent','unmapped','aborted','black_box','setup'}
def text(value,label,limit,*,optional=False):
 if value is None and optional:return None
 if not isinstance(value,str) or not value.strip() or value!=value.strip() or len(value)>limit or any(ord(c)<32 for c in value):raise ValueError(f'{label}: invalid text')
 return value
def count(value,label):
 if type(value)is not int or not 0<=value<=10**12:raise ValueError(f'{label}: invalid count')
 return value
def parse_commercial_lec(source:str)->dict:
 raw=source.encode()
 if len(raw)>2_000_000:raise ValueError('report exceeds 2 MB')
 try:document=json.loads(source.removeprefix('\ufeff'),object_pairs_hook=unique_object,parse_constant=reject_constant)
 except(ValueError,RecursionError):raise ValueError('invalid JSON report (check syntax, duplicate fields and finite numbers)')from None
 if not isinstance(document,dict)or document.get('format')!=FORMAT:raise ValueError(f'expected {FORMAT} report')
 tool=document.get('tool')
 if tool not in TOOLS:raise ValueError('tool must be Synopsys Formality or Cadence Conformal')
 version=text(document.get('tool_version'),'tool_version',80);reference_top=text(document.get('reference_top'),'reference_top',200);implementation_top=text(document.get('implementation_top'),'implementation_top',200)
 verdict=document.get('status')
 if verdict not in{'equivalent','non_equivalent','error'}:raise ValueError('status must be equivalent, non_equivalent or error')
 keys={'reference_compare_points','implementation_compare_points','matched_points','failing_points','aborted_points','unreachable_points'};summary=document.get('summary')
 if not isinstance(summary,dict)or set(summary)!=keys:raise ValueError('summary must contain the exact LEC count fields')
 normalized={key:count(summary[key],f'summary.{key}')for key in keys}
 if normalized['matched_points']>min(normalized['reference_compare_points'],normalized['implementation_compare_points']):raise ValueError('matched_points cannot exceed either compare-point total')
 rows=document.get('failures')
 if not isinstance(rows,list)or len(rows)>5000:raise ValueError('failures must contain at most 5000 entries')
 items=[]
 for index,row in enumerate(rows,1):
  if not isinstance(row,dict):raise ValueError(f'failure {index}: expected an object')
  kind=row.get('kind');severity=row.get('severity')
  if kind not in KINDS:raise ValueError(f'failure {index}: unsupported kind')
  if severity not in{'error','critical'}:raise ValueError(f'failure {index}: severity must be error or critical')
  name=text(row.get('name'),f'failure {index} name',500);reference_object=text(row.get('reference_object'),f'failure {index} reference_object',500,optional=True);implementation_object=text(row.get('implementation_object'),f'failure {index} implementation_object',500,optional=True);message=text(row.get('message'),f'failure {index} message',2000)
  identity={'kind':kind,'name':name,'reference_object':reference_object,'implementation_object':implementation_object}
  items.append({'index':index,**identity,'severity':severity,'message':message,'fingerprint':hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()})
 error_message=text(document.get('error_message'),'error_message',2000,optional=verdict!='error')
 if verdict!='error'and document.get('error_message')is not None:raise ValueError('error_message is only valid for an error result')
 if verdict=='equivalent'and(items or normalized['failing_points']or normalized['aborted_points']):raise ValueError('equivalent LEC result cannot contain failures or failing/aborted points')
 if verdict=='non_equivalent'and(not items or not normalized['failing_points']+normalized['aborted_points']):raise ValueError('non_equivalent LEC result requires failures and failing or aborted points')
 metrics={**normalized,'reported_failures':len(items),**{f'{kind}_failures':sum(item['kind']==kind for item in items)for kind in sorted(KINDS)}}
 return{'parser':PARSER,'tool':tool,'tool_version':version,'reference_top':reference_top,'implementation_top':implementation_top,'lec_status':verdict,'error_message':error_message,'summary':normalized,'items':items,'metrics':metrics,'source_sha256':hashlib.sha256(raw).hexdigest(),'coverage':'reported_lec_result_only','coverage_note':'Submitted LEC result only; complete inputs, setup and compare scope are not established.','status':'failed'if verdict!='equivalent'else'incomplete'}
