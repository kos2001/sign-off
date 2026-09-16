"""Bounded export of current violation state and recorded transitions."""
from datetime import datetime, timezone
import json

from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ..models import Violation, ViolationEvent
from ..schemas import ProjectViolationOut, ViolationEventOut

MAX_EVENTS = 10000
MAX_BYTES = 8 * 1024 * 1024


def export_history(db, violation_id):
    statement = (select(Violation, ViolationEvent)
                 .outerjoin(ViolationEvent, ViolationEvent.violation_id == Violation.id)
                 .where(Violation.id == violation_id)
                 .options(joinedload(Violation.run), joinedload(Violation.waiver))
                 .order_by(ViolationEvent.id).limit(MAX_EVENTS + 1)
                 .execution_options(yield_per=1, populate_existing=True))
    rows = db.execute(statement)
    prefix, events, size = None, [], 0
    try:
        for violation, event in rows:
            if prefix is None:
                # Refresh identity-map objects loaded during authorization and
                # capture state from the same SELECT as the ordered history.
                metadata = {'format': 'signoff/violation-history-export/v1',
                            'exported_at': datetime.now(timezone.utc).isoformat(),
                            'violation': ProjectViolationOut.model_validate(violation).model_dump(mode='json'),
                            'coverage_note': 'Recorded status transitions only; legacy records may have incomplete history.'}
                prefix = json.dumps(metadata, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()[:-1] + b',"events":['
                size = len(prefix)
            if event is not None:
                if len(events) >= MAX_EVENTS:
                    raise HTTPException(413, 'Violation history exceeds 10000 events; no partial export was created.')
                encoded = ViolationEventOut.model_validate(event).model_dump_json().encode()
                size += len(encoded) + (1 if events else 0)
                events.append(encoded)
            if size > MAX_BYTES:
                raise HTTPException(413, 'Violation history export exceeds 8 MiB; no partial export was created.')
    finally:
        rows.close()
    if prefix is None:
        raise HTTPException(404, 'violation not found')
    suffix = b'],"total":' + str(len(events)).encode() + b'}'
    if size + len(suffix) > MAX_BYTES:
        raise HTTPException(413, 'Violation history export exceeds 8 MiB; no partial export was created.')
    return Response(prefix + b','.join(events) + suffix, media_type='application/json', headers={
        'Content-Disposition': f'attachment; filename="violation-{violation_id}-history.json"',
        'Cache-Control': 'no-store',
    })
