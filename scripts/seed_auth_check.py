"""Seed a disposable auth browser fixture. Run from backend with PYTHONPATH=."""
import json
import os
from pathlib import Path
import secrets
import tempfile

from app.auth import password_hash
from app.db import SessionLocal, engine
from app.migrations import initialize_schema
from app.models import Project, ProjectMember, SignoffRun, User, Violation
from app.services.account_security import record_security_event

# Refuse to put known QA accounts into an existing database.
if not engine.url.database or Path(engine.url.database).exists():
    raise SystemExit('Use a new, disposable SIGNOFF_DATABASE_URL path')
initialize_schema(engine)
password = secrets.token_urlsafe(24)
encoded = password_hash(password)
with SessionLocal() as db:
    users = {role: User(username='qa-' + role, password_hash=encoded) for role in ['owner', 'editor', 'approver', 'viewer']}
    db.add_all(users.values())
    project = Project(name='Account browser QA', foundry='test', process_node='5nm')
    hidden = Project(name='Private project', foundry='test', process_node='5nm')
    db.add_all([project, hidden])
    db.flush()
    for role, user in users.items():
        db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    run = SignoffRun(project_id=project.id, domain='sta', stage='final', tool='QA')
    db.add(run)
    db.flush()
    violation = Violation(run_id=run.id, check_name='QA timing', severity='error')
    db.add(violation)
    if os.environ.get('SIGNOFF_SEED_SECURITY_HISTORY') == '1':
        db.add(User(username='qa-admin', password_hash=encoded, is_admin=True))
        for _ in range(30):
            record_security_event(db, 'password_reset', subject=users['editor'], source='operator', revoked_sessions=0)
        record_security_event(db, 'all_sessions_revoked', source='operator', revoked_sessions=7)
    db.commit()
    fd, name = tempfile.mkstemp(prefix='signoff-auth-fixture-', suffix='.json')
    with os.fdopen(fd, 'w') as file:
        json.dump({'project': project.id, 'hidden': hidden.id, 'violation': violation.id, 'approver': users['approver'].id, 'password': password}, file)
    print(name)
