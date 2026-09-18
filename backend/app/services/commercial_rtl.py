"""Strict exchange format for commercial RTL simulation regressions."""
import hashlib,json,math
from .report_import import JsonNumberRangeError,finite_json_float,reject_constant,unique_object
FORMAT='signoff/commercial-rtl-regression/v1';PARSER='commercial-rtl-regression-json/v1';TOOLS={'Synopsys VCS','Cadence Xcelium'}
def parse_commercial_rtl(source:str)->dict:
 raw=source.encode()
 if len(raw)>2_000_000:raise ValueError('report exceeds 2 MB')
 try:doc=json.loads(source.removeprefix('\ufeff'),object_pairs_hook=unique_object,parse_constant=reject_constant,parse_float=finite_json_float)
 except JsonNumberRangeError:raise ValueError('JSON number outside the supported floating-point range')from None
 except(ValueError,RecursionError):raise ValueError('invalid JSON report (check syntax, duplicate fields and finite numbers)')from None
 if not isinstance(doc,dict)or doc.get('format')!=FORMAT:raise ValueError(f'expected {FORMAT} report')
 tool=doc.get('tool')
 if tool not in TOOLS:raise ValueError('tool must be Synopsys VCS or Cadence Xcelium')
 version=text(doc.get('tool_version'),'tool_version',80)
 if version!=version.strip():raise ValueError('tool_version must not have surrounding whitespace')
 compile_status=doc.get('compile_status')
 if compile_status not in {'passed','failed'}:raise ValueError('compile_status must be passed or failed')
 compile_log=text(doc.get('compile_log_excerpt',''),'compile_log_excerpt',20000,empty=True)
 rows=doc.get('tests')
 if not isinstance(rows,list)or len(rows)>5000:raise ValueError('tests must contain at most 5000 entries')
 items=[];names=set()
 for i,row in enumerate(rows,1):
  if not isinstance(row,dict):raise ValueError(f'test {i}: expected an object')
  name=text(row.get('name'),f'test {i} name',500)
  if name in names:raise ValueError(f'test {i}: duplicate name')
  names.add(name);status=row.get('status')
  if status not in {'passed','failed','skipped'}:raise ValueError(f'test {i}: invalid status')
  duration=row.get('duration_ms')
  if type(duration)not in(int,float)or(type(duration)is float and not math.isfinite(duration))or duration<0 or duration>1e12:raise ValueError(f'test {i}: invalid duration_ms')
  seed=row.get('seed')
  if seed is not None and(type(seed)is not int or abs(seed)>2**53-1):raise ValueError(f'test {i}: invalid seed')
  assertions=row.get('assertions')
  if not isinstance(assertions,dict):raise ValueError(f'test {i}: invalid assertions')
  counts={k:count(assertions.get(k),f'test {i} assertions.{k}')for k in ['passed','failed','disabled']}
  if status=='passed' and counts['failed']:raise ValueError(f'test {i}: passed test cannot have failed assertions')
  log=text(row.get('log_excerpt',''),f'test {i} log_excerpt',20000,empty=True)
  identity={'name':name,'seed':seed};items.append({'index':i,'name':name,'status':status,'duration_ms':float(duration),'seed':seed,'assertions':counts,'log_excerpt':log,'fingerprint':hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()})
 failed=sum(x['status']=='failed'for x in items);skipped=sum(x['status']=='skipped'for x in items)
 return {'parser':PARSER,'tool':tool,'tool_version':version,'coverage':'reported_tests_only','coverage_note':'Submitted regression only; complete test plan, functional/code coverage, plusargs, libraries and simulator execution are not established.','source_sha256':hashlib.sha256(raw).hexdigest(),'status':'failed'if compile_status=='failed'or failed else'incomplete','compile_status':compile_status,'compile_log_excerpt':compile_log,'metrics':{'reported_tests':len(items),'passed_tests':sum(x['status']=='passed'for x in items),'failed_tests':failed,'skipped_tests':skipped,'failed_assertions':sum(x['assertions']['failed']for x in items),'duration_ms':sum(x['duration_ms']for x in items)},'items':items}
def text(v,label,limit,empty=False):
 if not isinstance(v,str)or len(v)>limit or any(ord(c)<9 or 13<ord(c)<32 for c in v)or(not empty and not v.strip()):raise ValueError(f'{label}: invalid text')
 return v
def count(v,label):
 if type(v)is not int or not 0<=v<=1_000_000_000:raise ValueError(f'{label}: invalid count')
 return v
