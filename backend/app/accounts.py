"""Operator-only account provisioning; passwords are read without shell arguments."""
import argparse
import getpass
import re

from sqlalchemy import delete, select

from .services.access import change_membership
from .services.account_security import record_security_event
from .auth import ROLES, password_hash
from .db import SessionLocal, engine
from .migrations import initialize_schema
from .models import AuthSession, Project, User


def read_password():
    password = getpass.getpass('Password (15–256 characters): ')
    if not 15 <= len(password) <= 256:
        raise ValueError('password must contain 15–256 characters')
    if password != getpass.getpass('Repeat password: '):
        raise ValueError('passwords do not match')
    return password


def main(argv=None):
    parser = argparse.ArgumentParser(description='Sign-off Hub account administration')
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create-user')
    create.add_argument('username')
    create.add_argument('--admin', action='store_true')
    for command in ['reset-password', 'disable-user', 'enable-user']:
        sub.add_parser(command).add_argument('username')
    sub.add_parser('revoke-sessions')
    grant = sub.add_parser('grant')
    grant.add_argument('username')
    grant.add_argument('project_id', type=int)
    grant.add_argument('role', choices=ROLES)
    args = parser.parse_args(argv)
    initialize_schema(engine)
    with SessionLocal() as db:
        if args.command == 'revoke-sessions':
            revoked = db.execute(delete(AuthSession)).rowcount
            record_security_event(db, 'all_sessions_revoked', source='operator', revoked_sessions=revoked)
        else:
            user = db.scalar(select(User).where(User.username == args.username))
            if args.command == 'create-user':
                if user or re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,63}', args.username) is None:
                    raise ValueError('username exists or is invalid (lowercase letters, digits, _, ., -; maximum 64)')
                user = User(username=args.username, password_hash=password_hash(read_password()), is_admin=args.admin)
                db.add(user)
                db.flush()
                record_security_event(db, 'admin_account_created' if args.admin else 'account_created', subject=user, source='operator')
            else:
                if user is None:
                    raise ValueError('user not found')
                if args.command == 'grant':
                    if db.get(Project, args.project_id) is None:
                        raise ValueError('project not found')
                    change_membership(db, args.project_id, user, args.role, source='operator')
                else:
                    if args.command == 'reset-password':
                        user.password_hash = password_hash(read_password())
                    else:
                        user.disabled = args.command == "disable-user"
                    # Acquire the account row lock before revoking sessions, in
                    # the same order as login and self-service password changes.
                    db.flush()
                    revoked = db.execute(delete(AuthSession).where(AuthSession.user_id == user.id)).rowcount
                    action = {'reset-password': 'password_reset', 'disable-user': 'account_disabled', 'enable-user': 'account_enabled'}[args.command]
                    record_security_event(db, action, subject=user, source='operator', revoked_sessions=revoked)
        db.commit()
    print('Account operation completed.')


if __name__ == '__main__':
    main()
