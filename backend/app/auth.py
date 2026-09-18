"""Cookie sessions and project authorization; local mode retains the demo workflow."""
import hashlib
import hmac
import os
import re
import secrets
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuthSession, CollectorCredential, Project, ProjectMember, SignoffRun, User, Violation

ROLES = {'viewer': 0, 'editor': 1, 'approver': 2, 'owner': 3}
COOKIE = 'signoff_session'
SESSION_SECONDS = 12 * 60 * 60


def auth_required():
    mode = os.environ.get('SIGNOFF_AUTH_MODE', 'local')
    if mode not in {'local', 'required'}:
        raise RuntimeError('SIGNOFF_AUTH_MODE must be local or required')
    return mode == 'required'


def secure_cookie():
    return os.environ.get('SIGNOFF_COOKIE_SECURE', 'true') != 'false'


def password_hash(password):
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600_000).hex()
    return f'pbkdf2_sha256$600000${salt}${derived}'


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt, expected = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or iterations != '600000':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def get_identity(request: Request, db: Session):
    token = request.cookies.get(COOKIE, '')
    if not token or len(token) > 128:
        return None, None
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token), AuthSession.expires_at > int(time.time())))
    user = db.get(User, session.user_id) if session else None
    if user is None or user.disabled:
        return None, None
    return user, session


def check_csrf(request, session):
    if not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), session.csrf_token):
        raise HTTPException(403, 'invalid CSRF token; reload and try again')


def project_role(db, project_id):
    user = db.info.get('user')
    if not auth_required() or (user and user.is_admin):
        return 'owner'
    return db.scalar(select(ProjectMember.role).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user.id)) if user else None


def require_project(db, project_id, minimum='viewer'):
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    role = project_role(db, project_id)
    if role not in ROLES:
        raise HTTPException(404, 'project not found')
    if ROLES[role] < ROLES[minimum]:
        raise HTTPException(403, f'{minimum} project role required')


def database_id(value, name, *, allow_text=True):
    if type(value) is int:
        number = value
    elif allow_text and isinstance(value, str) and re.fullmatch(r'[0-9]{1,19}', value):
        number = int(value)
    else:
        raise HTTPException(422, f'invalid {name}')
    if not 1 <= number <= 2**63 - 1:
        raise HTTPException(422, f'invalid {name}')
    return number


async def object_body(request):
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, 'request body must be a JSON object') from None
    if not isinstance(body, dict):
        raise HTTPException(422, 'request body must be a JSON object')
    return body


async def authorize(request: Request, db: Session = Depends(get_db)):
    required = auth_required()
    if not required:
        for key in {'project_id', 'run_id', 'violation_id', 'review_id', 'release_id', 'batch_id', 'user_id'} & request.path_params.keys():
            database_id(request.path_params[key], key)
        return
    authorization = request.headers.get('Authorization')
    if authorization is not None:
        if request.cookies.get(COOKIE) or not authorization.startswith('Bearer ') or authorization.count(' ') != 1:
            raise HTTPException(401, 'invalid collector credential')
        token = authorization[7:]
        if not 32 <= len(token) <= 128:
            raise HTTPException(401, 'invalid collector credential')
        credential = db.scalar(select(CollectorCredential).where(
            CollectorCredential.token_hash == token_hash(token),
            CollectorCredential.revoked_at.is_(None),
            CollectorCredential.expires_at > int(time.time()),
        ))
        route = request.scope['route'].path
        allowed = {
            '/projects/{project_id}/imports/commercial-sta',
            '/projects/{project_id}/imports/commercial-drc',
            '/projects/{project_id}/imports/commercial-emir',
            '/projects/{project_id}/imports/commercial-power',
            '/projects/{project_id}/imports/commercial-thermal',
            '/projects/{project_id}/imports/commercial-rtl',
            '/projects/{project_id}/imports/commercial-lvs',
            '/projects/{project_id}/imports/commercial-lec',
            '/projects/{project_id}/imports/commercial-cdc',
            '/projects/{project_id}/imports/commercial-dft',
            '/projects/{project_id}/imports/commercial-low-power',
        }
        if request.method != 'POST' or route not in allowed:
            raise HTTPException(401, 'invalid collector credential')
        project_id = database_id(request.path_params.get('project_id'), 'project_id')
        if credential is None or credential.project_id != project_id:
            raise HTTPException(401, 'invalid collector credential')
        body = await object_body(request)
        if not isinstance(body.get('coverage_attestation'), dict):
            raise HTTPException(422, 'collector submissions require a coverage attestation')
        db.info['collector'] = credential
        request.state.collector_id = credential.id
        return
    user, session = get_identity(request, db)
    if user is None:
        raise HTTPException(401, 'login required')
    db.info['user'] = user
    request.state.user_id = user.id
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        check_csrf(request, session)
    for key in {'project_id', 'run_id', 'violation_id', 'review_id', 'release_id', 'batch_id', 'user_id'} & request.path_params.keys():
        database_id(request.path_params[key], key)
    path = request.scope['route'].path
    project_id = request.path_params.get('project_id')
    if 'run_id' in request.path_params:
        run = db.get(SignoffRun, int(request.path_params['run_id']))
        if not run:
            raise HTTPException(404, 'run not found')
        project_id = run.project_id
    if 'violation_id' in request.path_params:
        violation = db.get(Violation, int(request.path_params['violation_id']))
        if not violation:
            raise HTTPException(404, 'violation not found')
        project_id = violation.run.project_id
        if request.method != 'GET':
            body = await object_body(request)
            approval = path.endswith('/waiver') or body.get('status') == 'waived' or violation.status.value == 'waived'
            require_project(db, project_id, 'approver' if approval else 'editor')
            return
    if project_id is not None:
        require_project(db, int(project_id), 'owner' if '/members' in path else 'viewer' if request.method == 'GET' else 'editor')
        return
    if path == '/projects':
        return  # Listing is filtered, and the creator becomes owner.
    if path.startswith('/analysis/'):
        body = await object_body(request)
        if isinstance(body, dict) and body.get('project_id') is not None:
            pid = database_id(body['project_id'], 'project_id', allow_text=False)
            require_project(db, pid, 'editor')
        return
    if path.startswith('/agents/'):
        return  # These endpoints only process submitted data; sessions are user-scoped.
    raise HTTPException(403, 'endpoint has no authorization policy')
