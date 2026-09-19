import base64
import json
import stat

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.release_signing import (
    DecisionSigner,
    configured_signer,
    load_public_key,
    main,
    verify_signature,
)


def encoded_private_key() -> str:
    raw = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption(),
    )
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def test_sign_and_verify_is_domain_separated_and_tamper_evident():
    signer = DecisionSigner.from_encoded(encoded_private_key())
    digest = 'a' * 64
    fields = signer.sign(digest)
    assert verify_signature(digest, **fields)
    with pytest.raises(ValueError, match='verification failed'):
        verify_signature('b' * 64, **fields)
    with pytest.raises(ValueError, match='key id'):
        verify_signature(digest, **{**fields, 'signing_key_id': '0' * 64})


def test_signing_configuration_is_strict(monkeypatch):
    monkeypatch.setenv('SIGNOFF_RELEASE_SIGNING_REQUIRED', '1')
    monkeypatch.delenv('SIGNOFF_RELEASE_SIGNING_PRIVATE_KEY', raising=False)
    with pytest.raises(RuntimeError, match='is required'):
        configured_signer()
    monkeypatch.setenv('SIGNOFF_RELEASE_SIGNING_PRIVATE_KEY', 'not-a-private-key')
    with pytest.raises(RuntimeError, match='base64url'):
        configured_signer()
    monkeypatch.setenv('SIGNOFF_RELEASE_SIGNING_REQUIRED', 'yes')
    with pytest.raises(RuntimeError, match='must be 0 or 1'):
        configured_signer()


def test_signing_key_can_be_loaded_from_a_secret_file(monkeypatch, tmp_path):
    encoded = encoded_private_key()
    path = tmp_path / 'private.key'
    path.write_text(encoded + '\n')
    monkeypatch.delenv('SIGNOFF_RELEASE_SIGNING_PRIVATE_KEY', raising=False)
    monkeypatch.setenv('SIGNOFF_RELEASE_SIGNING_PRIVATE_KEY_FILE', str(path))
    assert configured_signer().signing_key_id == DecisionSigner.from_encoded(encoded).signing_key_id
    monkeypatch.setenv('SIGNOFF_RELEASE_SIGNING_PRIVATE_KEY', encoded)
    with pytest.raises(RuntimeError, match='mutually exclusive'):
        configured_signer()


def test_key_generator_uses_exclusive_private_permissions(tmp_path):
    private = tmp_path / 'release-private.key'
    public = tmp_path / 'release-public.key'
    assert main(['generate', '--private-key', str(private), '--public-key', str(public)]) == 0
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    identifier, encoded = load_public_key(public)
    signer = DecisionSigner.from_encoded(private.read_text().strip())
    assert (identifier, encoded) == (signer.signing_key_id, signer.public_key)
    with pytest.raises(SystemExit):
        main(['generate', '--private-key', str(private), '--public-key', str(public)])


def test_public_key_loader_rejects_large_or_wrong_keys(tmp_path):
    large = tmp_path / 'large.key'
    large.write_bytes(b'x' * (16 * 1024 + 1))
    with pytest.raises(ValueError, match='too large'):
        load_public_key(large)
    wrong = tmp_path / 'wrong.pem'
    wrong.write_text(json.dumps({'secret': 'never-a-key'}))
    with pytest.raises(ValueError, match='not an Ed25519 public key'):
        load_public_key(wrong)
