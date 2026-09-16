"""Bounded KLayout marker database import; preserves value strings in cell coordinates."""
import hashlib
import json
import re
from xml.etree import ElementTree as ET


def parse_klayout(source):
    raw = source.encode('utf-8')
    if len(raw) > 2_000_000:
        raise ValueError('report exceeds 2 MB')
    if re.search(r'<!\s*(DOCTYPE|ENTITY)\b', source, re.I):
        raise ValueError('XML DTD and entity declarations are not supported')
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        raise ValueError('invalid KLayout XML report') from None
    if root.tag != 'report-database':
        raise ValueError('expected KLayout report-database root')
    stack = [(root, 0)]
    count = 0
    while stack:
        element, depth = stack.pop()
        count += 1
        if depth > 32 or count > 50000:
            raise ValueError('XML structure exceeds supported limits')
        stack.extend((child, depth+1) for child in element)
    def field(element, name, *, required=False, limit=2000):
        matches = element.findall(name)
        if len(matches) > 1 or (required and not matches):
            raise ValueError(f'missing or duplicate {name}')
        if not matches:
            return ''
        if len(matches[0]):
            raise ValueError(f'expected text for {name}')
        value = matches[0].text or ''
        if len(value) > limit:
            raise ValueError(f'{name} exceeds supported length')
        return value
    containers = root.findall('items')
    if len(containers) != 1 or any(item.tag != 'item' for item in containers[0]):
        raise ValueError('expected one items container containing item elements')
    if len(containers[0]) > 1000:
        raise ValueError('report exceeds 1000 marker items')
    items = []
    for index, item in enumerate(containers[0], 1):
        category = field(item, 'category', required=True)
        if not category.strip():
            raise ValueError('marker category must not be blank')
        cell = field(item, 'cell', required=True, limit=200)
        multiplicity_text = field(item, 'multiplicity') or '1'
        if not re.fullmatch(r'[0-9]{1,10}', multiplicity_text) or int(multiplicity_text) > 1_000_000_000:
            raise ValueError('invalid marker multiplicity')
        values = item.findall('values')
        if len(values) != 1 or len(values[0]) > 100 or any(value.tag != 'value' or len(value) for value in values[0]):
            raise ValueError('expected one values container with at most 100 text values')
        value_texts = [value.text or '' for value in values[0]]
        if any(len(value) > 20000 for value in value_texts):
            raise ValueError('marker value exceeds supported length')
        identity = {'category': category, 'cell': cell, 'values': value_texts}
        items.append({'index': index, **identity,
                      'fingerprint': hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                      'multiplicity': int(multiplicity_text), 'tags': field(item, 'tags'),
                      'visited': field(item, 'visited'), 'comment': field(item, 'comment', limit=20000)})
    return {'parser': 'klayout-lyrdb-xml/v1', 'coverage': 'reported_markers_only',
            'coverage_note': 'Marker database only; rule deck, checked layers and complete DRC coverage are not established.',
            'severity_policy': 'Submitted DRC marker items are conservatively filed as errors. The source format has no standard severity field; tags are not approvals.',
            'coordinate_note': 'Value strings are retained in their reported cell context (micrometers for geometry); no hierarchy transform is applied.',
            'source_sha256': hashlib.sha256(raw).hexdigest(), 'status': 'failed' if items else 'incomplete',
            'metrics': {'reported_items': len(items), 'reported_multiplicity': sum(item['multiplicity'] for item in items)},
            'description': field(root, 'description', limit=20000), 'top_cell': field(root, 'top-cell', limit=200),
            'generator': field(root, 'generator'), 'items': items}
