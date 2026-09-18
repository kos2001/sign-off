"""Strict exchange format for commercial thermal-analysis hotspots."""
import hashlib, json, math
from decimal import Decimal
from .report_import import JsonNumberRangeError, finite_json_float, reject_constant, unique_object

FORMAT='signoff/commercial-thermal/v1'; PARSER='commercial-thermal-json/v1'
TOOLS={'Cadence Celsius','Ansys Icepak','Siemens Calibre 3DSTACK'}; SEVERITIES={'info','warning','error','critical'}

def parse_commercial_thermal(source:str)->dict:
    raw=source.encode('utf-8')
    if len(raw)>2_000_000: raise ValueError('report exceeds 2 MB')
    try: doc=json.loads(source.removeprefix('\ufeff'),object_pairs_hook=unique_object,parse_constant=reject_constant,parse_float=finite_json_float)
    except JsonNumberRangeError: raise ValueError('JSON number outside the supported floating-point range; check report units and values') from None
    except (ValueError,RecursionError): raise ValueError('invalid JSON report (check syntax, duplicate fields and finite numbers)') from None
    if not isinstance(doc,dict) or doc.get('format')!=FORMAT: raise ValueError(f'expected {FORMAT} report')
    tool=doc.get('tool')
    if tool not in TOOLS: raise ValueError('unsupported commercial thermal tool')
    version=text(doc.get('tool_version'),'tool_version',80)
    if version!=version.strip(): raise ValueError('tool_version must not have surrounding whitespace')
    temp_unit=doc.get('temperature_unit')
    if temp_unit not in {'C','K'}: raise ValueError('temperature_unit must be C or K')
    coord_unit=doc.get('coordinate_unit');factor={'um':Decimal('1'),'mm':Decimal('1000')}.get(coord_unit)
    if factor is None: raise ValueError('coordinate_unit must be um or mm')
    top_cell=text(doc.get('top_cell'),'top_cell',200); rows=doc.get('hotspots')
    if not isinstance(rows,list) or len(rows)>5000: raise ValueError('hotspots must contain at most 5000 entries')
    items=[]
    for index,row in enumerate(rows,1):
        if not isinstance(row,dict): raise ValueError(f'hotspot {index}: expected an object')
        temperature=temp(row.get('temperature'),temp_unit,f'hotspot {index} temperature');limit=temp(row.get('limit'),temp_unit,f'hotspot {index} limit')
        severity=row.get('severity')
        if severity not in SEVERITIES: raise ValueError(f'hotspot {index}: invalid severity')
        identity={'component':text(row.get('component'),f'hotspot {index} component',500),'layer':optional(row,'layer',index,200),
                  'x_um':coord(row.get('x'),factor,f'hotspot {index} x'),'y_um':coord(row.get('y'),factor,f'hotspot {index} y'),
                  'z_um':coord(row.get('z',0),factor,f'hotspot {index} z')}
        items.append({'index':index,**identity,'temperature_c':float(temperature),'limit_c':float(limit),'severity':severity,
          'violated':temperature>limit,'message':optional(row,'message',index,2000),
          'fingerprint':hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()})
    violated=[x for x in items if x['violated']]
    temps=[x['temperature_c'] for x in items]
    return {'parser':PARSER,'tool':tool,'tool_version':version,'temperature_unit':temp_unit,'coordinate_unit':coord_unit,'top_cell':top_cell,
      'coverage':'reported_hotspots_only','coverage_note':'Hotspot exchange only; complete materials, boundary conditions, power maps, package and transient coverage are not established.',
      'source_sha256':hashlib.sha256(raw).hexdigest(),'status':'failed' if violated else 'incomplete',
      'metrics':{'reported_hotspots':len(items),'violated_hotspots':len(violated),'maximum_temperature_c':max(temps,default=None)},'items':items}

def text(v,label,limit):
    if not isinstance(v,str) or not v.strip() or len(v)>limit or any(ord(c)<32 for c in v):raise ValueError(f'{label}: invalid text')
    return v
def optional(src,key,index,limit):
    v=src.get(key,'')
    if not isinstance(v,str) or len(v)>limit or any(ord(c)<32 for c in v):raise ValueError(f'hotspot {index} {key}: invalid text')
    return v
def number(v,label):
    if type(v) not in (int,float) or(type(v)is float and not math.isfinite(v)):raise ValueError(f'{label}: expected a finite number')
    return Decimal(str(v))
def temp(v,unit,label):
    n=number(v,label)-(Decimal('273.15') if unit=='K' else 0)
    if n<Decimal('-273.15') or n>Decimal('1e6'):raise ValueError(f'{label}: outside the supported range')
    return n
def coord(v,factor,label):
    n=number(v,label)*factor
    if n.copy_abs()>Decimal('1e12') or(n and n.copy_abs()<Decimal('1e-12')):raise ValueError(f'{label}: outside the supported range')
    return format(n,'f')
