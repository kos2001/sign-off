"""Operator-only management for project-scoped collector bearer credentials."""

import argparse
import json
import re
import secrets
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .auth import token_hash
from .db import SessionLocal, engine
from .migrations import initialize_schema
from .models import CollectorCredential, CollectorCredentialEvent, Project


def issue_credential(db, project_id: int, name: str, valid_days: int, *, actor='local operator',
                     actor_user_id=None) -> tuple[CollectorCredential, str]:
    if db.get(Project, project_id) is None:
        raise ValueError('project not found')
    if re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,63}', name) is None:
        raise ValueError('name is invalid (lowercase letters, digits, _, ., -; maximum 64)')
    if not 1 <= valid_days <= 3650:
        raise ValueError('valid-days must be between 1 and 3650')
    token = 'soct_' + secrets.token_urlsafe(32)
    credential = CollectorCredential(
        project_id=project_id, name=name, token_hash=token_hash(token),
        expires_at=int(time.time()) + valid_days * 24 * 60 * 60,
    )
    db.add(credential)
    try:
        db.flush()
    except IntegrityError:
        raise ValueError('collector name already exists for this project') from None
    db.add(CollectorCredentialEvent(
        project_id=project_id, credential_id=credential.id, credential_name=name,
        action='issued', actor=actor, actor_user_id=actor_user_id,
        expires_at=credential.expires_at,
    ))
    return credential, token


def main(argv=None):
    parser = argparse.ArgumentParser(description='Sign-off Hub collector credential administration')
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    create.add_argument('project_id', type=int)
    create.add_argument('name')
    create.add_argument('--valid-days', type=int, default=90)
    revoke = commands.add_parser('revoke')
    revoke.add_argument('project_id', type=int)
    revoke.add_argument('name')
    listing = commands.add_parser('list')
    listing.add_argument('project_id', type=int)
    args = parser.parse_args(argv)
    initialize_schema(engine)
    with SessionLocal() as db:
        if db.get(Project, args.project_id) is None:
            raise ValueError('project not found')
        if args.command == 'create':
            credential, token = issue_credential(db, args.project_id, args.name, args.valid_days)
            db.commit()
            print(json.dumps({'id': credential.id, 'project_id': credential.project_id,
                'name': credential.name, 'expires_at': credential.expires_at, 'token': token}))
            return
        credential = db.scalar(select(CollectorCredential).where(
            CollectorCredential.project_id == args.project_id,
            CollectorCredential.name == args.name,
        )) if args.command == 'revoke' else None
        if args.command == 'revoke':
            if credential is None:
                raise ValueError('collector credential not found')
            if credential.revoked_at is None:
                credential.revoked_at = datetime.now(timezone.utc)
                db.add(CollectorCredentialEvent(
                    project_id=args.project_id, credential_id=credential.id,
                    credential_name=credential.name, action='revoked', actor='operator CLI',
                    actor_user_id=None, expires_at=credential.expires_at,
                ))
            db.commit()
            print('Collector credential revoked.')
            return
        rows = db.scalars(select(CollectorCredential).where(
            CollectorCredential.project_id == args.project_id,
        ).order_by(CollectorCredential.id)).all()
        print(json.dumps([{'id': row.id, 'project_id': row.project_id, 'name': row.name,
            'expires_at': row.expires_at, 'revoked_at': row.revoked_at.isoformat() if row.revoked_at else None}
            for row in rows]))


if __name__ == '__main__':
    main()
