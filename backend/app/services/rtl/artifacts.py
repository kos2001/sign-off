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
    """Exclude the generated HDL body from review inputs and gate summaries."""
    artifact = result.get('netlist')
    if not isinstance(artifact, dict):
        return result
    return {**result, 'netlist': {key: value for key, value in artifact.items() if key != 'text'}}
