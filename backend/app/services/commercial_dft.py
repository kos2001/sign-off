"""Strict exchange format for commercial scan/ATPG signoff results."""
import hashlib,json,math
from .report_import import reject_constant,unique_object
FORMAT='signoff/commercial-dft/v1';PARSER='commercial-dft-json/v1'
TOOLS={'Synopsys TestMAX ATPG','Siemens Tessent TestKompress','Cadence Modus ATPG'}
MODELS={'stuck_at','transition','bridging','cell_aware','path_delay'}
KINDS={'scan_chain','dft_rule','coverage','aborted_fault','pattern_validation'}
def text(v,label,limit,optional=False):
 if v is None and optional:return None
 if not isinstance(v,str)or not v.strip()or v!=v.strip()or len(v)>limit or any(ord(c)<32 for c in v):raise ValueError(f'{label}: invalid text')
 return v
def integer(v,label):
 if type(v)is not int or not 0<=v<=10**12:raise ValueError(f'{label}: invalid count')
 return v
def number(v,label):
 if type(v)not in(int,float)or not math.isfinite(v)or not 0<=v<=100:raise ValueError(f'{label}: invalid percentage')
 return float(v)
def parse_commercial_dft(source:str)->dict:
 raw=source.encode()
 if len(raw)>2_000_000:raise ValueError('report exceeds 2 MB')
 try:doc=json.loads(source.removeprefix('\ufeff'),object_pairs_hook=unique_object,parse_constant=reject_constant)
 except(ValueError,RecursionError):raise ValueError('invalid JSON report (check syntax, duplicate fields and finite numbers)')from None
 if not isinstance(doc,dict)or doc.get('format')!=FORMAT:raise ValueError(f'expected {FORMAT} report')
 tool=doc.get('tool')
 if tool not in TOOLS:raise ValueError('unsupported commercial DFT tool')
 version=text(doc.get('tool_version'),'tool_version',80);top=text(doc.get('top'),'top',200);verdict=doc.get('status')
 if verdict not in{'passed','failed','error'}:raise ValueError('status must be passed, failed or error')
 keys={'scan_chains','scan_cells','broken_chains','dft_rule_violations'};summary=doc.get('summary')
 if not isinstance(summary,dict)or set(summary)!=keys:raise ValueError('summary must contain the exact DFT count fields')
 normalized={key:integer(summary[key],f'summary.{key}')for key in keys}
 rows=doc.get('fault_models')
 if not isinstance(rows,list)or not rows or len(rows)>20:raise ValueError('fault_models must contain 1 to 20 entries')
 models=[];seen=set()
 required={'name','total_faults','detected_faults','untestable_faults','aborted_faults','coverage_percent','required_coverage_percent','pattern_count'}
 for index,row in enumerate(rows,1):
  if not isinstance(row,dict)or set(row)!=required:raise ValueError(f'fault model {index}: expected exact fields')
  name=row['name']
  if name not in MODELS or name in seen:raise ValueError(f'fault model {index}: unsupported or duplicate name')
  seen.add(name);total=integer(row['total_faults'],f'{name}.total_faults');detected=integer(row['detected_faults'],f'{name}.detected_faults');untestable=integer(row['untestable_faults'],f'{name}.untestable_faults');aborted=integer(row['aborted_faults'],f'{name}.aborted_faults');patterns=integer(row['pattern_count'],f'{name}.pattern_count');coverage=number(row['coverage_percent'],f'{name}.coverage_percent');threshold=number(row['required_coverage_percent'],f'{name}.required_coverage_percent')
  if detected+untestable+aborted>total:raise ValueError(f'{name}: fault counts exceed total_faults')
  testable=total-untestable;calculated=100.0 if testable==0 else detected/testable*100
  if abs(coverage-calculated)>1e-6:raise ValueError(f'{name}: coverage_percent does not match fault counts')
  models.append({'name':name,'total_faults':total,'detected_faults':detected,'untestable_faults':untestable,'aborted_faults':aborted,'coverage_percent':coverage,'required_coverage_percent':threshold,'pattern_count':patterns,'violated':coverage<threshold or aborted>0})
 findings=doc.get('findings')
 if not isinstance(findings,list)or len(findings)>5000:raise ValueError('findings must contain at most 5000 entries')
 items=[]
 for index,row in enumerate(findings,1):
  if not isinstance(row,dict):raise ValueError(f'finding {index}: expected an object')
  kind=row.get('kind');severity=row.get('severity')
  if kind not in KINDS or severity not in{'warning','error','critical'}:raise ValueError(f'finding {index}: unsupported kind or severity')
  rule=text(row.get('rule'),f'finding {index} rule',200);name=text(row.get('name'),f'finding {index} name',500);location=text(row.get('location'),f'finding {index} location',500,optional=True);message=text(row.get('message'),f'finding {index} message',2000);identity={'kind':kind,'rule':rule,'name':name,'location':location}
  items.append({'index':index,**identity,'severity':severity,'message':message,'fingerprint':hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()})
 blocking=sum(x['severity']in{'error','critical'}for x in items);model_failures=sum(x['violated']for x in models);summary_failures=normalized['broken_chains']+normalized['dft_rule_violations'];error_message=text(doc.get('error_message'),'error_message',2000,optional=verdict!='error')
 if verdict!='error'and doc.get('error_message')is not None:raise ValueError('error_message is only valid for an error result')
 if verdict=='passed'and(summary_failures or model_failures or blocking):raise ValueError('passed DFT result cannot contain blocking failures')
 if verdict=='failed'and not(summary_failures or model_failures or blocking):raise ValueError('failed DFT result must contain a blocking failure')
 metrics={**normalized,'reported_fault_models':len(models),'violated_fault_models':model_failures,'reported_findings':len(items),'blocking_findings':blocking,'total_patterns':sum(x['pattern_count']for x in models)}
 return{'parser':PARSER,'tool':tool,'tool_version':version,'top':top,'dft_status':verdict,'error_message':error_message,'summary':normalized,'fault_models':models,'items':items,'metrics':metrics,'source_sha256':hashlib.sha256(raw).hexdigest(),'coverage':'reported_dft_result_only','coverage_note':'Submitted DFT result only; complete scan, ATPG, fault simulation and pattern-validation scope are not established.','status':'failed'if verdict!='passed'else'incomplete'}
