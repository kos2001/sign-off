"""Bound HTTP request bodies before JSON parsing allocates unbounded memory."""

import os
import re

from fastapi import Request

DEFAULT_MAX_REQUEST_BYTES = 64 * 1024 * 1024
MIN_MAX_REQUEST_BYTES = 1024
MAX_MAX_REQUEST_BYTES = 256 * 1024 * 1024
BODY_METHODS = {'DELETE', 'PATCH', 'POST', 'PUT'}


class RequestBodyError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def configured_request_limit() -> int:
    raw = os.environ.get('SIGNOFF_MAX_REQUEST_BYTES')
    if raw is None or raw == '':
        return DEFAULT_MAX_REQUEST_BYTES
    if re.fullmatch(r'[0-9]+', raw) is None:
        raise RuntimeError('SIGNOFF_MAX_REQUEST_BYTES must be an integer')
    value = int(raw)
    if not MIN_MAX_REQUEST_BYTES <= value <= MAX_MAX_REQUEST_BYTES:
        raise RuntimeError('SIGNOFF_MAX_REQUEST_BYTES must be between 1024 and 268435456')
    return value


def declared_content_length(request: Request) -> int | None:
    values = [value for name, value in request.scope.get('headers', []) if name.lower() == b'content-length']
    if not values:
        return None
    if len(values) != 1:
        raise RequestBodyError(400, 'invalid Content-Length')
    try:
        value = values[0].decode('ascii')
    except UnicodeDecodeError:
        raise RequestBodyError(400, 'invalid Content-Length') from None
    if re.fullmatch(r'[0-9]+', value) is None:
        raise RequestBodyError(400, 'invalid Content-Length')
    if len(value) > 20:
        raise RequestBodyError(413, 'request body is too large')
    return int(value)


async def cache_limited_body(request: Request, limit: int):
    declared = declared_content_length(request)
    if declared is not None and declared > limit:
        raise RequestBodyError(413, f'request body exceeds {limit} bytes')
    if request.method not in BODY_METHODS and not declared:
        return
    body = bytearray()
    while True:
        message = await request.receive()
        if message['type'] == 'http.disconnect':
            raise RequestBodyError(400, 'request body was interrupted')
        chunk = message.get('body', b'')
        if len(body) + len(chunk) > limit:
            raise RequestBodyError(413, f'request body exceeds {limit} bytes')
        body.extend(chunk)
        if not message.get('more_body', False):
            break
    if declared is not None and len(body) != declared:
        raise RequestBodyError(400, 'Content-Length does not match request body')
    request._body = bytes(body)
