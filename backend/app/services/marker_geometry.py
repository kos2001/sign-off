"""Render bounded marker primitives in a cell-local, aspect-preserving preview."""
from decimal import Decimal, InvalidOperation, localcontext
import re

NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z')


def coordinate(text):
    text = text.strip()
    if len(text) > 64 or not NUMBER.fullmatch(text):
        raise ValueError()
    value = Decimal(text)
    if value.copy_abs() > Decimal('1e12') or (value and value.copy_abs() < Decimal('1e-12')):
        raise ValueError()
    return value


def points(text):
    result = []
    for pair in text.split(';'):
        xy = pair.split(',')
        if len(xy) != 2:
            raise ValueError()
        result.append(tuple(coordinate(value) for value in xy))
    return result


def primitive(value):
    pair = re.fullmatch(r'edge-pair:\s*\(([^()]*)\)\s*/\s*\(([^()]*)\)\s*', value)
    if pair:
        contours = [points(pair[1]), points(pair[2])]
        if any(len(contour) != 2 for contour in contours):
            raise ValueError()
        return False, contours
    match = re.fullmatch(r'(box|edge|polygon):\s*\(([^()]*)\)\s*', value)
    if not match:
        raise ValueError()
    kind, body = match.groups()
    contours = [points(part) for part in body.split('/')]
    if kind == 'polygon':
        if any(len(contour) < 3 for contour in contours):
            raise ValueError()
        return True, contours
    if len(contours) != 1 or len(contours[0]) != 2:
        raise ValueError()
    if kind == 'box':
        (x1, y1), (x2, y2) = contours[0]
        return True, [[(x1, y1), (x2, y1), (x2, y2), (x1, y2)]]
    return False, contours


def marker_geometry(values):
    parsed, skipped, count = [], [], 0
    with localcontext() as context:
        context.prec = 80
        for index, value in enumerate(values, 1):
            try:
                closed, contours = primitive(value)
                size = sum(len(contour) for contour in contours)
                if count + size > 2000:
                    raise ValueError()
                count += size
                parsed.append((index, closed, contours))
            except (ValueError, InvalidOperation):
                skipped.append(index)
        if not parsed:
            return {'shapes': [], 'bounds_um': None, 'rendered_values': 0, 'unrendered_values': skipped}
        all_points = [point for _, _, contours in parsed for contour in contours for point in contour]
        xmin, xmax = min(p[0] for p in all_points), max(p[0] for p in all_points)
        ymin, ymax = min(p[1] for p in all_points), max(p[1] for p in all_points)
        span = max(xmax-xmin, ymax-ymin) or Decimal(1)
        cx, cy = (xmin+xmax)/2, (ymin+ymax)/2
        shapes = [{'value_index': index, 'closed': closed,
                   'contours': [[[float(100+(x-cx)*180/span), float(100-(y-cy)*180/span)] for x, y in contour] for contour in contours]}
                  for index, closed, contours in parsed]
        return {'shapes': shapes, 'bounds_um': {'xmin': str(xmin), 'xmax': str(xmax), 'ymin': str(ymin), 'ymax': str(ymax)},
                'rendered_values': len(parsed), 'unrendered_values': skipped}
