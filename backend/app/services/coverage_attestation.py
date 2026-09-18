"""Verify short-lived coverage claims emitted by configured report collectors."""

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timedelta, timezone


REQUIRED_STA_CLAIMS = {
    'tool_run_completed',
    'modes_corners_complete',
    'constraints_validated',
    'parasitics_requirement_satisfied',
    'findings_complete',
    'unconstrained_paths_zero',
}
REQUIRED_DRC_CLAIMS = {
    'tool_run_completed',
    'rule_deck_complete',
    'layout_inputs_complete',
    'hierarchy_complete',
    'checks_complete',
    'findings_complete',
}
REQUIRED_EMIR_CLAIMS = {
    'tool_run_completed',
    'rail_coverage_complete',
    'modes_corners_complete',
    'activity_vectors_complete',
    'extraction_complete',
    'checks_complete',
    'findings_complete',
}
REQUIRED_POWER_CLAIMS = {
    'tool_run_completed',
    'modes_corners_complete',
    'activity_vectors_complete',
    'power_models_complete',
    'hierarchy_complete',
    'findings_complete',
}
REQUIRED_THERMAL_CLAIMS = {
    'tool_run_completed',
    'material_models_complete',
    'boundary_conditions_complete',
    'power_map_complete',
    'package_stack_complete',
    'analysis_scope_complete',
    'mesh_convergence_complete',
    'findings_complete',
}
REQUIRED_CLAIMS = {
    'sta': REQUIRED_STA_CLAIMS,
    'pv': REQUIRED_DRC_CLAIMS,
    'emir': REQUIRED_EMIR_CLAIMS,
    'glitch_power': REQUIRED_POWER_CLAIMS,
    'thermal': REQUIRED_THERMAL_CLAIMS,
}


class AttestationConfigurationError(RuntimeError):
    pass


def validate_optional_configuration():
    if os.environ.get('SIGNOFF_COVERAGE_HMAC_KEYS'):
        configured_keys()


def configured_keys() -> dict[str, tuple[bytes, frozenset[str]]]:
    raw = os.environ.get('SIGNOFF_COVERAGE_HMAC_KEYS', '')
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate key id')
            value[key] = item
        return value
    try:
        document = json.loads(raw, object_pairs_hook=unique_object)
    except (TypeError, ValueError):
        raise AttestationConfigurationError('coverage attestation keys are not configured') from None
    if not isinstance(document, dict) or not document or len(document) > 16:
        raise AttestationConfigurationError('coverage attestation keys are not configured')
    keys = {}
    for key_id, config in document.items():
        if (not isinstance(key_id, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', key_id)
                or not isinstance(config, dict) or set(config) != {'secret', 'domains'}):
            raise AttestationConfigurationError('coverage attestation key configuration is invalid')
        secret, domains = config['secret'], config['domains']
        if (not isinstance(secret, str) or not 32 <= len(secret.encode()) <= 512
                or not isinstance(domains, list) or not domains
                or any(not isinstance(domain, str) for domain in domains)
                or len(domains) != len(set(domains))
                or not set(domains) <= set(REQUIRED_CLAIMS)):
            raise AttestationConfigurationError('coverage attestation key configuration is invalid')
        keys[key_id] = (secret.encode(), frozenset(domains))
    return keys


def canonical_payload(attestation) -> bytes:
    value = attestation.model_dump(mode='json', exclude={'signature'})
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()


def verify_attestation(attestation, *, domain, project_id, payload, result, now=None):
    if attestation is None:
        return None
    for field in ('design_revision', 'tool_version', 'scenario'):
        if getattr(payload, field) != getattr(payload, field).strip():
            raise ValueError(f'{field} must not have surrounding whitespace when using a coverage attestation')
    if str(attestation.attestation_id) != str(payload.import_id):
        raise ValueError('coverage attestation id must equal import_id')
    bindings = {
        'project_id': project_id, 'stage': payload.stage, 'domain': domain,
        'design_revision': payload.design_revision,
        'source_sha256': result['source_sha256'], 'tool': result['tool'],
        'tool_version': payload.tool_version, 'scenario': payload.scenario,
    }
    for field, expected in bindings.items():
        actual = getattr(attestation, field)
        actual = actual.value if hasattr(actual, 'value') else actual
        expected = expected.value if hasattr(expected, 'value') else expected
        if actual != expected:
            raise ValueError(f'coverage attestation {field} does not match the report request')
    required = REQUIRED_CLAIMS[domain]
    if set(attestation.claims) != required or not all(attestation.claims.values()):
        raise ValueError(f'coverage attestation must affirm every required {domain.upper()} coverage claim')
    if domain == 'sta' and result['metrics']['unconstrained_paths']:
        raise ValueError('coverage attestation claims zero unconstrained paths but the report contains one')
    if domain == 'pv' and not result.get('description', '').strip():
        raise ValueError('coverage attestation claims a complete rule deck but the report does not identify one')

    issued_at, expires_at = attestation.issued_at, attestation.expires_at
    if issued_at.tzinfo is None or expires_at.tzinfo is None:
        raise ValueError('coverage attestation timestamps must include a timezone')
    issued_at, expires_at = issued_at.astimezone(timezone.utc), expires_at.astimezone(timezone.utc)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if expires_at <= issued_at or expires_at - issued_at > timedelta(days=7):
        raise ValueError('coverage attestation validity must be greater than zero and at most 7 days')
    if current < issued_at - timedelta(minutes=5) or current > expires_at:
        raise ValueError('coverage attestation is not currently valid')

    key = configured_keys().get(attestation.key_id)
    if key is None or domain not in key[1]:
        raise ValueError('coverage attestation key_id is not trusted for this domain')
    expected = hmac.new(key[0], canonical_payload(attestation), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, attestation.signature):
        raise ValueError('coverage attestation signature is invalid')
    preserved = attestation.model_dump(mode='json')
    preserved['verified'] = True
    return preserved


def verify_sta_attestation(attestation, **context):
    return verify_attestation(attestation, domain='sta', **context)


def verify_drc_attestation(attestation, **context):
    return verify_attestation(attestation, domain='pv', **context)


def verify_emir_attestation(attestation, **context):
    return verify_attestation(attestation, domain='emir', **context)


def verify_power_attestation(attestation, **context):
    return verify_attestation(attestation, domain='glitch_power', **context)


def verify_thermal_attestation(attestation, **context):
    return verify_attestation(attestation, domain='thermal', **context)
