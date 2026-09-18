from sqlalchemy import select

from ..models import StaScenarioDefinition, StaScenarioPlanRevision, Stage


def resolve_sta_scenario_plan(db, project_id: int, stage: Stage) -> dict:
    revision = db.scalar(select(StaScenarioPlanRevision).where(
        StaScenarioPlanRevision.project_id == project_id,
        StaScenarioPlanRevision.stage == stage,
    ).order_by(StaScenarioPlanRevision.version.desc()).limit(1))
    if revision is not None:
        return {
            'project_id': project_id, 'stage': stage.value, 'version': revision.version,
            'source': 'versioned', 'scenarios': revision.scenarios, 'reason': revision.reason,
            'updated_by': revision.updated_by, 'updated_by_user_id': revision.updated_by_user_id,
            'created_at': revision.created_at,
        }
    definitions = db.scalars(select(StaScenarioDefinition).where(
        StaScenarioDefinition.project_id == project_id,
        StaScenarioDefinition.stage == stage,
    ).order_by(StaScenarioDefinition.name)).all()
    return {
        'project_id': project_id, 'stage': stage.value, 'version': 0, 'source': 'legacy',
        'scenarios': [{'name': row.name, 'require_spef': row.require_spef} for row in definitions],
        'reason': None, 'updated_by': None, 'updated_by_user_id': None, 'created_at': None,
    }
