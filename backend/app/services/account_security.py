"""Append account security events without storing credential material."""
from ..models import AccountSecurityEvent

ACTIONS = {'login', 'login_failed', 'logout', 'password_changed', 'other_sessions_revoked',
           'account_created', 'admin_account_created', 'password_reset', 'account_disabled', 'account_enabled',
           'all_sessions_revoked'}


def record_security_event(db, action, *, subject=None, actor=None, source='api', revoked_sessions=None, submitted_username=None):
    if action not in ACTIONS or source not in {'api', 'operator'}:
        raise ValueError('unsupported account security event')
    db.add(AccountSecurityEvent(
        subject_user_id=subject.id if subject else None,
        subject_username=subject.username if subject else submitted_username,
        actor_user_id=actor.id if actor else None,
        actor=actor.username if actor else 'local operator' if source == 'operator' else 'unverified client', source=source,
        action=action, revoked_sessions=revoked_sessions,
    ))
