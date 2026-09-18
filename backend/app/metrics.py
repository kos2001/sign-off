"""Small bounded-cardinality Prometheus registry for one API process."""

import os
import threading
import time
from collections import defaultdict

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
METHODS = {'DELETE', 'GET', 'HEAD', 'OPTIONS', 'PATCH', 'POST', 'PUT'}


def configured_token() -> str | None:
    value = os.environ.get('SIGNOFF_METRICS_TOKEN')
    if value is None or value == '':
        return None
    if not 32 <= len(value) <= 256 or not all(33 <= ord(character) <= 126 for character in value):
        raise RuntimeError('SIGNOFF_METRICS_TOKEN must contain 32 to 256 printable ASCII characters')
    return value


def _label(value: str) -> str:
    return value.replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


class Metrics:
    def __init__(self):
        self.started_at = time.time()
        self._lock = threading.Lock()
        self._in_flight = 0
        self._requests = defaultdict(int)
        self._duration_count = defaultdict(int)
        self._duration_sum = defaultdict(float)
        self._duration_buckets = defaultdict(lambda: [0] * len(BUCKETS))
        self._readiness = defaultdict(int)

    def start_request(self):
        with self._lock:
            self._in_flight += 1

    def finish_request(self, method: str, route: str, status: int, elapsed: float):
        method = method if method in METHODS else 'OTHER'
        key = (method, route, f'{status // 100}xx')
        duration_key = (method, route)
        with self._lock:
            self._in_flight -= 1
            self._requests[key] += 1
            self._duration_count[duration_key] += 1
            self._duration_sum[duration_key] += elapsed
            values = self._duration_buckets[duration_key]
            for index, boundary in enumerate(BUCKETS):
                if elapsed <= boundary:
                    values[index] += 1

    def readiness(self, result: str, component: str):
        with self._lock:
            self._readiness[(result, component)] += 1

    def render(self) -> str:
        with self._lock:
            in_flight = self._in_flight
            requests = dict(self._requests)
            counts = dict(self._duration_count)
            sums = dict(self._duration_sum)
            buckets = {key: list(value) for key, value in self._duration_buckets.items()}
            readiness = dict(self._readiness)
        lines = [
            '# HELP signoff_process_start_time_seconds Unix time when this API process started.',
            '# TYPE signoff_process_start_time_seconds gauge',
            f'signoff_process_start_time_seconds {self.started_at:.6f}',
            '# HELP signoff_http_in_flight_requests Requests currently executing in this API process.',
            '# TYPE signoff_http_in_flight_requests gauge',
            f'signoff_http_in_flight_requests {in_flight}',
            '# HELP signoff_http_requests_total Completed HTTP requests by route template and status class.',
            '# TYPE signoff_http_requests_total counter',
        ]
        for (method, route, status_class), value in sorted(requests.items()):
            lines.append(f'signoff_http_requests_total{{method="{_label(method)}",route="{_label(route)}",status_class="{status_class}"}} {value}')
        lines += [
            '# HELP signoff_http_request_duration_seconds Time until response headers by route template.',
            '# TYPE signoff_http_request_duration_seconds histogram',
        ]
        for method, route in sorted(counts):
            labels = f'method="{_label(method)}",route="{_label(route)}"'
            for boundary, value in zip(BUCKETS, buckets[(method, route)]):
                lines.append(f'signoff_http_request_duration_seconds_bucket{{{labels},le="{boundary:g}"}} {value}')
            lines.append(f'signoff_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {counts[(method, route)]}')
            lines.append(f'signoff_http_request_duration_seconds_sum{{{labels}}} {sums[(method, route)]:.9f}')
            lines.append(f'signoff_http_request_duration_seconds_count{{{labels}}} {counts[(method, route)]}')
        lines += [
            '# HELP signoff_readiness_checks_total Readiness probe results by failed component.',
            '# TYPE signoff_readiness_checks_total counter',
        ]
        for (result, component), value in sorted(readiness.items()):
            lines.append(f'signoff_readiness_checks_total{{result="{_label(result)}",component="{_label(component)}"}} {value}')
        return '\n'.join(lines) + '\n'
