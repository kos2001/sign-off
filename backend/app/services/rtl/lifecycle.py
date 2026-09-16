"""Deployment ownership and maximum container lifetime metadata."""
import hashlib
import os
from pathlib import Path
import re
import socket

LEASE_SECONDS = 360  # Worker deadline 300s plus startup/cleanup grace.


def deployment_owner():
    configured = os.environ.get('SIGNOFF_RTL_WORKER_OWNER')
    if configured is None:
        identity = f'{socket.gethostname()}:{Path(__file__).resolve().parents[3]}'
        configured = 'local-' + hashlib.sha256(identity.encode()).hexdigest()[:24]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', configured):
        raise ValueError('SIGNOFF_RTL_WORKER_OWNER must be a 1–64 character identifier')
    return configured


def lifecycle_labels():
    return {'signoff.rtl-owner': deployment_owner(), 'signoff.rtl-lease-seconds': str(LEASE_SECONDS)}
