"""Build a validated, signed commercial-report import request for a trusted collector."""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

from .commercial_drc import parse_commercial_drc
from .commercial_emir import parse_commercial_emir
from .commercial_power import parse_commercial_power
from .commercial_rtl import parse_commercial_rtl
from .commercial_thermal import parse_commercial_thermal
from .coverage_attestation import REQUIRED_CLAIMS, canonical_payload
from .report_import import parse_commercial_sta


PARSERS = {
    'sta': parse_commercial_sta,
    'pv': parse_commercial_drc,
    'emir': parse_commercial_emir,
    'glitch_power': parse_commercial_power,
    'thermal': parse_commercial_thermal,
    'rtl': parse_commercial_rtl,
}


def validate_claims(domain: str, claims: object) -> dict[str, bool]:
    required = REQUIRED_CLAIMS.get(domain)
    if required is None:
        raise ValueError('unsupported coverage domain')
    if not isinstance(claims, dict) or set(claims) != required:
        raise ValueError(f'claims must contain exactly the required {domain} coverage keys')
    if any(value is not True for value in claims.values()):
        raise ValueError('every coverage claim must be explicitly true')
    return claims


def build_import_request(*, domain: str, source_text: str, filename: str, project_id: int,
                         stage: str, design_revision: str, scenario: str, tool_version: str,
                         key_id: str, secret: str, claims: object, valid_for_seconds: int = 3600,
                         import_id: str | None = None, now: datetime | None = None) -> dict:
    """Validate the report and bindings, then return the exact API request body."""
    if not isinstance(secret, str) or not 32 <= len(secret.encode()) <= 512:
        raise ValueError('collector secret must contain 32 to 512 UTF-8 bytes')
    if not 1 <= valid_for_seconds <= 7 * 24 * 60 * 60:
        raise ValueError('validity must be between 1 second and 7 days')
    for label, value, limit in (
        ('filename', filename, 160), ('design_revision', design_revision, 160),
        ('scenario', scenario, 160), ('tool_version', tool_version, 80), ('key_id', key_id, 64),
    ):
        if not isinstance(value, str) or not value or value != value.strip() or len(value) > limit:
            raise ValueError(f'{label} is invalid or has surrounding whitespace')
    parser = PARSERS.get(domain)
    if parser is None:
        raise ValueError('unsupported coverage domain')
    result = parser(source_text)
    if result['tool_version'] != tool_version:
        raise ValueError('tool_version does not match the version captured in the report')
    verified_claims = validate_claims(domain, claims)
    issued_at = now or datetime.now(timezone.utc)
    if issued_at.tzinfo is None:
        raise ValueError('collector time must include a timezone')
    issued_at = issued_at.astimezone(timezone.utc)
    request_id = str(uuid.UUID(import_id)) if import_id else str(uuid.uuid4())
    body = {
        'import_id': request_id, 'stage': stage, 'filename': filename,
        'tool_version': tool_version, 'design_revision': design_revision,
        'scenario': scenario, 'source_text': source_text,
    }
    attestation = {
        'format': 'signoff/coverage-attestation/v1', 'attestation_id': request_id,
        'key_id': key_id, 'issued_at': issued_at, 'expires_at': issued_at + timedelta(seconds=valid_for_seconds),
        'project_id': project_id, 'stage': stage, 'domain': domain,
        'design_revision': design_revision, 'source_sha256': hashlib.sha256(source_text.encode()).hexdigest(),
        'tool': result['tool'], 'tool_version': tool_version, 'scenario': scenario,
        'claims': verified_claims, 'signature': '0' * 64,
    }
    # Reuse the server schema so UUID, enums and timestamps have exactly the same canonical form.
    from ..routers.imports import CoverageAttestationPayload
    parsed = CoverageAttestationPayload.model_validate(attestation)
    attestation['signature'] = hmac.new(secret.encode(), canonical_payload(parsed), hashlib.sha256).hexdigest()
    body['coverage_attestation'] = CoverageAttestationPayload.model_validate(attestation).model_dump(mode='json')
    return body
