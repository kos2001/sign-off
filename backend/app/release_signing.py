"""Ed25519 signatures for independently verifiable sign-off decisions."""

import argparse
import base64
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PRIVATE_KEY_ENV = 'SIGNOFF_RELEASE_SIGNING_PRIVATE_KEY'
PRIVATE_KEY_FILE_ENV = 'SIGNOFF_RELEASE_SIGNING_PRIVATE_KEY_FILE'
REQUIRED_ENV = 'SIGNOFF_RELEASE_SIGNING_REQUIRED'
SIGNATURE_VERSION = 1
CONTEXT = b'signoff/release-decision-signature/v1\x00'
B64_32 = re.compile(r'^[A-Za-z0-9_-]{43}$')
B64_64 = re.compile(r'^[A-Za-z0-9_-]{86}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _decode(value: str, pattern: re.Pattern, name: str) -> bytes:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f'{name} has an invalid base64url encoding')
    try:
        return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError(f'{name} has an invalid base64url encoding') from error


def key_id(public_bytes: bytes) -> str:
    return hashlib.sha256(public_bytes).hexdigest()


def signed_message(decision_sha256: str) -> bytes:
    if not isinstance(decision_sha256, str) or SHA256.fullmatch(decision_sha256) is None:
        raise ValueError('decision_sha256 must be a lowercase SHA-256 digest')
    return CONTEXT + bytes.fromhex(decision_sha256)


@dataclass(frozen=True)
class DecisionSigner:
    private_key: Ed25519PrivateKey
    public_key: str
    signing_key_id: str

    @classmethod
    def from_encoded(cls, encoded: str):
        raw = _decode(encoded, B64_32, 'release signing private key')
        private_key = Ed25519PrivateKey.from_private_bytes(raw)
        public_bytes = private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )
        return cls(private_key, _encode(public_bytes), key_id(public_bytes))

    def sign(self, decision_sha256: str) -> dict:
        return {
            'signature_version': SIGNATURE_VERSION,
            'signing_key_id': self.signing_key_id,
            'signing_public_key': self.public_key,
            'decision_signature': _encode(self.private_key.sign(signed_message(decision_sha256))),
        }


def signing_required() -> bool:
    value = os.environ.get(REQUIRED_ENV, '0')
    if value not in {'0', '1'}:
        raise RuntimeError(f'{REQUIRED_ENV} must be 0 or 1')
    return value == '1'


def configured_signer() -> DecisionSigner | None:
    encoded = os.environ.get(PRIVATE_KEY_ENV)
    key_file = os.environ.get(PRIVATE_KEY_FILE_ENV)
    required = signing_required()
    if encoded and key_file:
        raise RuntimeError(f'{PRIVATE_KEY_ENV} and {PRIVATE_KEY_FILE_ENV} are mutually exclusive')
    if key_file:
        try:
            path = Path(key_file)
            if path.stat().st_size > 1024:
                raise RuntimeError(f'{PRIVATE_KEY_FILE_ENV} is too large')
            encoded = path.read_text(encoding='ascii').strip()
        except (OSError, UnicodeError) as error:
            raise RuntimeError(f'{PRIVATE_KEY_FILE_ENV} cannot be read') from error
    if not encoded:
        if required:
            raise RuntimeError(f'a release signing private key is required when {REQUIRED_ENV}=1')
        return None
    try:
        return DecisionSigner.from_encoded(encoded)
    except ValueError as error:
        raise RuntimeError(str(error)) from error


def verify_signature(decision_sha256: str, *, signature_version, signing_key_id,
                     signing_public_key, decision_signature) -> bool:
    values = (signature_version, signing_key_id, signing_public_key, decision_signature)
    if all(value is None for value in values):
        return False
    if any(value is None for value in values):
        raise ValueError('decision signature fields are incomplete')
    if signature_version != SIGNATURE_VERSION:
        raise ValueError('unsupported decision signature version')
    if not isinstance(signing_key_id, str) or SHA256.fullmatch(signing_key_id) is None:
        raise ValueError('decision signing_key_id is invalid')
    public_bytes = _decode(signing_public_key, B64_32, 'decision signing public key')
    if key_id(public_bytes) != signing_key_id:
        raise ValueError('decision signing key id does not match its public key')
    signature = _decode(decision_signature, B64_64, 'decision signature')
    try:
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature, signed_message(decision_sha256))
    except InvalidSignature as error:
        raise ValueError('decision signature verification failed') from error
    return True


def load_public_key(path: Path) -> tuple[str, str]:
    if path.stat().st_size > 16 * 1024:
        raise ValueError(f'{path} is too large to be an Ed25519 public key')
    raw = path.read_bytes().strip()
    try:
        public_bytes = _decode(raw.decode('ascii'), B64_32, 'trusted public key')
    except (UnicodeError, ValueError):
        try:
            public = serialization.load_pem_public_key(raw)
        except ValueError as error:
            raise ValueError(f'{path} is not an Ed25519 public key') from error
        if not isinstance(public, Ed25519PublicKey):
            raise ValueError(f'{path} is not an Ed25519 public key')
        public_bytes = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key_id(public_bytes), _encode(public_bytes)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Manage Sign-off Hub release signing keys')
    subparsers = parser.add_subparsers(dest='command', required=True)
    generate = subparsers.add_parser('generate')
    generate.add_argument('--private-key', required=True, type=Path)
    generate.add_argument('--public-key', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.private_key == args.public_key:
        parser.error('private and public key paths must differ')
    for path in (args.private_key, args.public_key):
        if path.exists():
            parser.error(f'{path} already exists')
        if not path.parent.is_dir():
            parser.error(f'{path.parent} is not a directory')
    private = Ed25519PrivateKey.generate()
    private_bytes = private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption(),
    )
    public_bytes = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    private_created = False
    public_created = False
    try:
        descriptor = os.open(args.private_key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        private_created = True
        with os.fdopen(descriptor, 'w', encoding='ascii') as stream:
            stream.write(_encode(private_bytes) + '\n')
        descriptor = os.open(args.public_key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        public_created = True
        with os.fdopen(descriptor, 'w', encoding='ascii') as stream:
            stream.write(_encode(public_bytes) + '\n')
    except Exception:
        if private_created:
            args.private_key.unlink(missing_ok=True)
        if public_created:
            args.public_key.unlink(missing_ok=True)
        raise
    print(f'Generated Ed25519 release signing key {key_id(public_bytes)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
