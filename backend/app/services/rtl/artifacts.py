"""Bounded, integrity-checked synthesis artifacts shared by worker and host."""
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_NETLIST_BYTES = 1024 * 1024


class NetlistArtifact(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    format: Literal['yosys-generic-verilog/v1']
    text: str = Field(min_length=1, max_length=MAX_NETLIST_BYTES)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    byte_length: int = Field(ge=1, le=MAX_NETLIST_BYTES)

    @model_validator(mode='after')
    def check_integrity(self):
        raw = self.text.encode('utf-8')
        if len(raw) != self.byte_length or hashlib.sha256(raw).hexdigest() != self.sha256:
            raise ValueError('netlist integrity mismatch')
        return self


def netlist_metadata_only(result: dict) -> dict:
    """Exclude generated artifact bodies from review inputs and gate summaries."""
    summary = dict(result)
    for key in ('netlist', 'structure'):
        artifact = summary.get(key)
        if isinstance(artifact, dict):
            summary[key] = {field: value for field, value in artifact.items() if field != 'text'}
    return summary


def parse_structure(text: str) -> dict:
    """Validate the bounded subset consumed by the structure explorer."""
    import json
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate structure key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('invalid JSON constant')
    def finite_float(value):
        import math
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('non-finite number')
        return result
    try:
        data = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant, parse_float=finite_float)
    except RecursionError as exc:
        raise ValueError('structure nesting limit') from exc
    pending = [(data, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 64:
            raise ValueError('structure nesting limit')
        if isinstance(value, str):
            value.encode('utf-8')
        elif isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
            for name in value:
                name.encode('utf-8')
                if len(name) > 1024:
                    raise ValueError('structure name limit')
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
    if not isinstance(data, dict) or not isinstance(data.get('modules'), dict) or not data['modules']:
        raise ValueError('missing modules')
    def bits(value):
        if not isinstance(value, list) or any(not (type(bit) is int and 0 <= bit <= 2**53-1 or type(bit) is str and bit in {'0','1','x','z'}) for bit in value):
            raise ValueError('invalid bit vector')
    for module in data['modules'].values():
        if not isinstance(module, dict) or any(not isinstance(module.get(key), dict) for key in ['ports','cells','netnames']):
            raise ValueError('invalid module')
        for port in module['ports'].values():
            if not isinstance(port, dict) or port.get('direction') not in ('input','output','inout'):
                raise ValueError('invalid port')
            bits(port.get('bits'))
        for net in module['netnames'].values():
            if not isinstance(net, dict):
                raise ValueError('invalid net')
            bits(net.get('bits'))
        for cell in module['cells'].values():
            if not isinstance(cell, dict) or not isinstance(cell.get('type'), str) or not isinstance(cell.get('connections'), dict) or not isinstance(cell.get('port_directions'), dict):
                raise ValueError('invalid cell')
            for name, vector in cell['connections'].items():
                if cell['port_directions'].get(name) not in ('input','output','inout'):
                    raise ValueError('unknown port direction')
                bits(vector)
    return data


class StructureArtifact(NetlistArtifact):
    format: Literal['yosys-json/v1']

    @model_validator(mode='after')
    def check_structure(self):
        parse_structure(self.text)
        return self
