"""Change membership and append its audit event in the caller's transaction."""
from sqlalchemy import delete, select, update

from ..models import ProjectAccessEvent, ProjectMember


class MembershipConflict(ValueError):
    pass


def change_membership(db, project_id, subject, role, *, actor=None, source='api'):
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == subject.id))
    before = member.role if member else None
    if before == role:
        return False
    if member:
        predicate = (ProjectMember.id == member.id) & (ProjectMember.role == before)
        statement = delete(ProjectMember).where(predicate) if role is None else update(ProjectMember).where(predicate).values(role=role)
        changed = db.execute(statement.execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise MembershipConflict('membership changed; reload and retry')
        db.expire(member)
    else:
        db.add(ProjectMember(project_id=project_id, user_id=subject.id, role=role))
        db.flush()  # Unique key detects concurrent first-time grants.
    db.add(ProjectAccessEvent(
        project_id=project_id, subject_user_id=subject.id, subject_username=subject.username,
        actor_user_id=actor.id if actor else None, actor=actor.username if actor else 'local operator',
        source=source, before_role=before, after_role=role,
    ))
    return True
