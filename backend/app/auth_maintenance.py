"""Bounded cleanup of expired authentication state; audit history is retained."""
import argparse
import json
import time

from sqlalchemy import delete, select

from .db import SessionLocal
from .models import AuthSession, LoginBucket


def cleanup_expired(db, *, cutoff: int, limit: int = 100, apply: bool = False):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('limit must be between 1 and 1000 per table')
    if type(cutoff) is not int:
        raise ValueError('cutoff must be an integer timestamp')
    result = {}
    for model in [AuthSession, LoginBucket]:
        ids = list(db.scalars(select(model.id).where(model.expires_at <= cutoff)
                              .order_by(model.expires_at, model.id).limit(limit + 1)))
        selected = ids[:limit]
        count = len(selected)
        if apply and selected:
            # Recheck expiry: a concurrent login can renew an expired bucket
            # between selection and deletion. Preserve its active rate limit.
            count = db.execute(delete(model).where(model.id.in_(selected),
                               model.expires_at <= cutoff)).rowcount
        result[model.__tablename__] = {'count': count, 'more_at_selection': len(ids) > limit}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=500, help='maximum rows per table (1–1000)')
    parser.add_argument('--apply', action='store_true', help='delete the expired rows; default is read-only preview')
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 1000:
        parser.error('--limit must be between 1 and 1000 per table')
    cutoff = int(time.time())
    with SessionLocal() as db:
        result = cleanup_expired(db, cutoff=cutoff, limit=args.limit, apply=args.apply)
        if args.apply:
            db.commit()
    print(json.dumps({'mode': 'apply' if args.apply else 'preview', 'cutoff': cutoff,
                      'limit_per_table': args.limit, 'tables': result}))


if __name__ == '__main__':
    main()
