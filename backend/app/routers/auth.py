import secrets
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import COOKIE, SESSION_SECONDS, auth_required, authorize, check_csrf, get_identity, password_hash, secure_cookie, token_hash, verify_password
from ..services.access import MembershipConflict, change_membership
from ..services.account_security import ACTIONS, record_security_event
from ..db import get_db
from ..models import AccountSecurityEvent, AuthSession, LoginBucket, ProjectMember, ProjectAccessEvent, User

router = APIRouter(prefix='/auth', tags=['accounts'])
members_router = APIRouter(tags=['project-members'], dependencies=[Depends(authorize)])
DUMMY_HASH = password_hash('not-a-real-account-' + secrets.token_hex(20))


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r'^[a-z0-9][a-z0-9_.-]*$')
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=15, max_length=256)


class MemberInput(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    role: Literal['viewer', 'editor', 'approver', 'owner']


def throttle(db, key, limit):
    now = int(time.time())
    digest = token_hash(key)
    def increment():
        return db.execute(update(LoginBucket).where(LoginBucket.key == digest).values(
            attempts=case((LoginBucket.expires_at <= now, 1), else_=LoginBucket.attempts + 1),
            expires_at=case((LoginBucket.expires_at <= now, now + 300), else_=LoginBucket.expires_at),
        )).rowcount
    if not increment():
        db.add(LoginBucket(key=digest, attempts=1, expires_at=now + 300))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            increment()
    db.commit()
    attempts = db.scalar(select(LoginBucket.attempts).where(LoginBucket.key == digest))
    if attempts > limit:
        raise HTTPException(429, 'too many login attempts; try again in five minutes', headers={'Retry-After': '300'})


def public_user(user):
    return {'id': user.id, 'username': user.username, 'is_admin': user.is_admin} if user else None


@router.get('/session')
def current_session(request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    if not auth_required():
        return {'mode': 'local', 'user': None, 'csrf_token': None, 'memberships': {}}
    user, session = get_identity(request, db)
    return session_payload(user, session, db)


def session_payload(user, session, db):
    memberships = dict(db.execute(select(ProjectMember.project_id, ProjectMember.role).where(ProjectMember.user_id == user.id)).all()) if user else {}
    return {'mode': 'required', 'user': public_user(user), 'csrf_token': session.csrf_token if session else None, 'memberships': memberships}


def session_identity(request, db):
    if not auth_required():
        raise HTTPException(409, 'session management requires authentication mode')
    user, session = get_identity(request, db)
    if user is None:
        raise HTTPException(401, 'login required')
    return user, session


@router.get('/sessions')
def list_sessions(request: Request, response: Response,
                  offset: int = Query(default=0, ge=0, le=2_147_483_647),
                  limit: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_db)):
    user, current = session_identity(request, db)
    active = (AuthSession.user_id == user.id, AuthSession.expires_at > int(time.time()))
    total = db.scalar(select(func.count()).select_from(AuthSession).where(*active))
    sessions = db.scalars(select(AuthSession).where(*active).order_by(
        case((AuthSession.id == current.id, 0), else_=1), AuthSession.id.desc()).offset(offset).limit(limit)).all()
    response.headers['Cache-Control'] = 'no-store'
    return {'total': total, 'offset': offset, 'limit': limit,
            'items': [{'id': item.id, 'current': item.id == current.id, 'expires_at': item.expires_at} for item in sessions]}


@router.post('/sessions/revoke-others')
def revoke_other_sessions(request: Request, response: Response, db: Session = Depends(get_db)):
    user, current = session_identity(request, db)
    check_csrf(request, current)
    # Use the same account lock as login and password changes. Recheck the
    # caller's session after the lock so an already revoked caller cannot
    # revoke a surviving session in a concurrent request.
    guarded = db.execute(update(User).where(User.id == user.id, User.password_hash == user.password_hash,
                                           User.disabled.is_(False)).values(password_hash=user.password_hash))
    if guarded.rowcount != 1 or db.scalar(select(AuthSession.id).where(
        AuthSession.id == current.id, AuthSession.token_hash == current.token_hash,
        AuthSession.user_id == user.id, AuthSession.expires_at > int(time.time()),
    )) is None:
        db.rollback()
        raise HTTPException(401, 'login required')
    removed = db.execute(delete(AuthSession).where(AuthSession.user_id == user.id,
        AuthSession.id != current.id, AuthSession.expires_at > int(time.time())))
    revoked = removed.rowcount
    record_security_event(db, 'other_sessions_revoked', subject=user, actor=user, revoked_sessions=revoked)
    db.commit()
    response.headers['Cache-Control'] = 'no-store'
    return {'revoked': revoked}


@router.get('/security-events')
def security_events(request: Request, response: Response,
                    before_id: int | None = Query(default=None, gt=0, le=2**63 - 1),
                    limit: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_db)):
    user, _ = session_identity(request, db)
    query = select(AccountSecurityEvent).where(AccountSecurityEvent.subject_user_id == user.id)
    response.headers['Cache-Control'] = 'no-store'
    return security_event_page(db, query, before_id, limit)


def security_event_page(db, query, before_id, limit, *, include_subject=False):
    if before_id is not None:
        query = query.where(AccountSecurityEvent.id < before_id)
    events = db.scalars(query.order_by(AccountSecurityEvent.id.desc()).limit(limit + 1)).all()
    page = events[:limit]
    fields = ['id', 'action', 'actor', 'actor_user_id', 'source', 'revoked_sessions', 'created_at']
    if include_subject:
        fields += ['subject_user_id', 'subject_username']
    return {'items': [{key: getattr(event, key) for key in fields} for event in page],
            'next_before_id': page[-1].id if len(events) > limit else None}


@router.get('/admin/security-events')
def admin_security_events(request: Request, response: Response,
                          subject_username: str | None = Query(default=None, min_length=1, max_length=64),
                          action: str | None = Query(default=None, min_length=1, max_length=40),
                          source: Literal['api', 'operator'] | None = None,
                          created_from: datetime | None = None,
                          created_before: datetime | None = None,
                          before_id: int | None = Query(default=None, gt=0, le=2**63 - 1),
                          limit: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_db)):
    user, _ = session_identity(request, db)
    if not user.is_admin:
        raise HTTPException(403, 'administrator account required')
    if action is not None and action not in ACTIONS:
        raise HTTPException(422, 'unknown account security action')
    def utc(value):
        if value is None:
            return None
        if value.utcoffset() is None:
            raise HTTPException(422, 'security event timestamps must include a timezone')
        try:
            return value.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            raise HTTPException(422, 'security event timestamp is outside the supported range') from None
    created_from, created_before = utc(created_from), utc(created_before)
    if created_from is not None and created_before is not None and created_from >= created_before:
        raise HTTPException(422, 'created_from must be earlier than created_before')
    query = select(AccountSecurityEvent)
    if subject_username is not None:
        query = query.where(AccountSecurityEvent.subject_username == subject_username)
    if action is not None:
        query = query.where(AccountSecurityEvent.action == action)
    if source is not None:
        query = query.where(AccountSecurityEvent.source == source)
    if created_from is not None:
        query = query.where(AccountSecurityEvent.created_at >= created_from)
    if created_before is not None:
        query = query.where(AccountSecurityEvent.created_at < created_before)
    response.headers['Cache-Control'] = 'no-store'
    return security_event_page(db, query, before_id, limit, include_subject=True)


@router.post('/login')
def login(payload: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    if not auth_required():
        raise HTTPException(409, 'login is not enabled')
    # Custom header requires a CORS preflight. This app does not allow cross-origin login.
    if request.headers.get('X-Signoff-Client') != '1':
        raise HTTPException(403, 'same-origin client header required')
    throttle(db, 'ip:' + (request.client.host if request.client else 'unknown'), 40)
    throttle(db, 'user:' + payload.username, 8)
    user = db.scalar(select(User).where(User.username == payload.username))
    correct = verify_password(payload.password, user.password_hash if user else DUMMY_HASH)
    if not correct or user is None or user.disabled:
        reject_login(db, user, payload.username)
    # Serialize credential validation/session creation against resets and disable.
    guarded = db.execute(update(User).where(User.id == user.id, User.password_hash == user.password_hash, User.disabled.is_(False)).values(password_hash=user.password_hash))
    if guarded.rowcount != 1:
        db.rollback()
        reject_login(db, user, payload.username)
    old = request.cookies.get(COOKIE)
    if old:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(old)))
    from ..auth_maintenance import cleanup_expired
    cleanup_expired(db, cutoff=int(time.time()), limit=100, apply=True)
    token = secrets.token_urlsafe(32)
    session = AuthSession(token_hash=token_hash(token), user_id=user.id, csrf_token=secrets.token_urlsafe(32), expires_at=int(time.time()) + SESSION_SECONDS)
    db.add(session)
    record_security_event(db, 'login', subject=user, actor=user)
    db.commit()
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=secure_cookie(), samesite='strict', path='/')
    response.headers["Cache-Control"] = "no-store"
    return session_payload(user, session, db)


def reject_login(db, user, submitted_username):
    # A matched account is the target, never the verified actor of a failure.
    record_security_event(db, 'login_failed', subject=user, submitted_username=submitted_username)
    db.commit()
    raise HTTPException(401, 'invalid username or password', headers={'Cache-Control': 'no-store'})


@router.post('/password')
def change_password(payload: PasswordChange, request: Request, response: Response, db: Session = Depends(get_db)):
    if not auth_required():
        raise HTTPException(409, 'password changes require authentication mode')
    user, session = get_identity(request, db)
    if user is None:
        raise HTTPException(401, 'login required')
    check_csrf(request, session)
    throttle(db, f'password-change:{user.id}', 8)
    previous_hash = user.password_hash
    if not verify_password(payload.current_password, previous_hash):
        raise HTTPException(400, 'current password is incorrect')
    if payload.current_password == payload.new_password:
        raise HTTPException(400, 'new password must differ from current password')
    replacement = password_hash(payload.new_password)
    guarded = db.execute(update(User).where(User.id == user.id, User.password_hash == previous_hash, User.disabled.is_(False)).values(password_hash=replacement).execution_options(synchronize_session=False))
    if guarded.rowcount != 1:
        db.rollback()
        raise HTTPException(409, 'account changed; sign in again before changing the password')
    revoked = db.execute(delete(AuthSession).where(AuthSession.user_id == user.id)).rowcount
    token = secrets.token_urlsafe(32)
    replacement_session = AuthSession(token_hash=token_hash(token), user_id=user.id, csrf_token=secrets.token_urlsafe(32), expires_at=int(time.time()) + SESSION_SECONDS)
    db.add(replacement_session)
    record_security_event(db, 'password_changed', subject=user, actor=user, revoked_sessions=revoked)
    db.commit()
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=secure_cookie(), samesite='strict', path='/')
    response.headers['Cache-Control'] = 'no-store'
    return session_payload(user, replacement_session, db)


@router.post('/logout')
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    if request.headers.get("X-Signoff-Client") != "1":
        raise HTTPException(403, "same-origin client header required")
    user, session = get_identity(request, db)
    if session:
        check_csrf(request, session)
        removed = db.execute(delete(AuthSession).where(AuthSession.id == session.id, AuthSession.token_hash == session.token_hash))
        if removed.rowcount:
            record_security_event(db, 'logout', subject=user, actor=user, revoked_sessions=removed.rowcount)
        db.commit()
    response.delete_cookie(COOKIE, path='/', secure=secure_cookie(), httponly=True, samesite='strict')
    response.headers['Cache-Control'] = 'no-store'
    return {'status': 'ok'}


@members_router.get('/projects/{project_id}/members')
def list_members(project_id: int, db: Session = Depends(get_db)):
    return [{'username': user.username, 'user_id': user.id, 'role': member.role, 'disabled': user.disabled}
            for member, user in db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id).where(ProjectMember.project_id == project_id)).all()]


@members_router.put('/projects/{project_id}/members')
def set_member(project_id: int, payload: MemberInput, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or user.disabled:
        raise HTTPException(404, 'active account not found')
    current = db.info.get('user')
    if current and current.id == user.id and not current.is_admin and payload.role != 'owner':
        raise HTTPException(409, 'owners cannot downgrade their own access')
    try:
        change_membership(db, project_id, user, payload.role, actor=current)
        db.commit()
    except (IntegrityError, MembershipConflict):
        db.rollback()
        raise HTTPException(409, 'membership changed; reload and retry')
    return {'status': 'ok'}


@members_router.delete('/projects/{project_id}/members/{user_id}')
def remove_member(project_id: int, user_id: int, db: Session = Depends(get_db)):
    current = db.info.get('user')
    if current and current.id == user_id and not current.is_admin:
        raise HTTPException(409, 'owners cannot remove their own access')
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, 'account not found')
    try:
        change_membership(db, project_id, user, None, actor=current)
        db.commit()
    except MembershipConflict:
        db.rollback()
        raise HTTPException(409, 'membership changed; reload and retry')
    return {'status': 'ok'}


@members_router.get('/projects/{project_id}/members/history')
def member_history(project_id: int, before_id: int | None = Query(default=None, gt=0, le=2**63 - 1), limit: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_db)):
    query = select(ProjectAccessEvent).where(ProjectAccessEvent.project_id == project_id)
    if before_id is not None:
        query = query.where(ProjectAccessEvent.id < before_id)
    events = db.scalars(query.order_by(ProjectAccessEvent.id.desc()).limit(limit + 1)).all()
    page = events[:limit]
    return {
        'items': [{key: getattr(event, key) for key in ['id', 'project_id', 'subject_user_id', 'subject_username', 'actor_user_id', 'actor', 'source', 'before_role', 'after_role', 'created_at']} for event in page],
        'next_before_id': page[-1].id if len(events) > limit else None,
    }
