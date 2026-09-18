"""Strict exchange format for commercial CDC/RDC static-signoff results."""
import hashlib,json
from .report_import import reject_constant,unique_object
FORMAT='signoff/commercial-cdc-rdc/v1';PARSER='commercial-cdc-rdc-json/v1'
TOOLS={'Synopsys VC SpyGlass CDC/RDC','Cadence Jasper CDC'}
KINDS={'cdc','rdc','constraint','synchronizer','protocol','reconvergence'}
def text(value,label,limit,*,optional=False):
 if value is None and optional:return None
 if not isinstance(value,str)or not value.strip()or value!=value.strip()or len(value)>limit or any(ord(c)<32 for c in value):raise ValueError(f'{label}: invalid text')
 return value
def count(value,label):
 if type(value)is not int or not 0<=value<=10**12:raise ValueError(f'{label}: invalid count')
 return value
def parse_commercial_cdc(source:str)->dict:
 raw=source.encode()
 if len(raw)>2_000_000:raise ValueError('report exceeds 2 MB')
 try:doc=json.loads(source.removeprefix('\ufeff'),object_pairs_hook=unique_object,parse_constant=reject_constant)
 except(ValueError,RecursionError):raise ValueError('invalid JSON report (check syntax, duplicate fields and finite numbers)')from None
 if not isinstance(doc,dict)or doc.get('format')!=FORMAT:raise ValueError(f'expected {FORMAT} report')
 tool=doc.get('tool')
 if tool not in TOOLS:raise ValueError('tool must be Synopsys VC SpyGlass CDC/RDC or Cadence Jasper CDC')
 version=text(doc.get('tool_version'),'tool_version',80);top=text(doc.get('top'),'top',200);verdict=doc.get('status')
 if verdict not in{'clean','violations','error'}:raise ValueError('status must be clean, violations or error')
 keys={'clock_domains','reset_domains','cdc_crossings','rdc_crossings'};summary=doc.get('summary')
 if not isinstance(summary,dict)or set(summary)!=keys:raise ValueError('summary must contain the exact CDC/RDC count fields')
 normalized={key:count(summary[key],f'summary.{key}')for key in keys}
 rows=doc.get('findings')
 if not isinstance(rows,list)or len(rows)>5000:raise ValueError('findings must contain at most 5000 entries')
 items=[]
 for index,row in enumerate(rows,1):
  if not isinstance(row,dict):raise ValueError(f'finding {index}: expected an object')
  kind=row.get('kind');severity=row.get('severity')
  if kind not in KINDS:raise ValueError(f'finding {index}: unsupported kind')
  if severity not in{'warning','error','critical'}:raise ValueError(f'finding {index}: unsupported severity')
  rule=text(row.get('rule'),f'finding {index} rule',200);name=text(row.get('name'),f'finding {index} name',500);source_object=text(row.get('source_object'),f'finding {index} source_object',500,optional=True);destination_object=text(row.get('destination_object'),f'finding {index} destination_object',500,optional=True);source_domain=text(row.get('source_domain'),f'finding {index} source_domain',200,optional=True);destination_domain=text(row.get('destination_domain'),f'finding {index} destination_domain',200,optional=True);message=text(row.get('message'),f'finding {index} message',2000)
  identity={'kind':kind,'rule':rule,'name':name,'source_object':source_object,'destination_object':destination_object,'source_domain':source_domain,'destination_domain':destination_domain}
  items.append({'index':index,**identity,'severity':severity,'message':message,'fingerprint':hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()})
 blocking=sum(item['severity']in{'error','critical'}for item in items);error_message=text(doc.get('error_message'),'error_message',2000,optional=verdict!='error')
 if verdict!='error'and doc.get('error_message')is not None:raise ValueError('error_message is only valid for an error result')
 if verdict=='clean'and blocking:raise ValueError('clean CDC/RDC result cannot contain blocking findings')
 if verdict=='violations'and not blocking:raise ValueError('violations result must contain an error or critical finding')
 metrics={**normalized,'reported_findings':len(items),'blocking_findings':blocking,**{f'{kind}_findings':sum(item['kind']==kind for item in items)for kind in sorted(KINDS)}}
 return{'parser':PARSER,'tool':tool,'tool_version':version,'top':top,'cdc_status':verdict,'error_message':error_message,'summary':normalized,'items':items,'metrics':metrics,'source_sha256':hashlib.sha256(raw).hexdigest(),'coverage':'reported_cdc_rdc_findings_only','coverage_note':'Submitted CDC/RDC findings only; complete constraints, hierarchy and analysis scope are not established.','status':'failed'if verdict!='clean'else'incomplete'}
