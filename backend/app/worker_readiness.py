"""A bounded, process-local cache for the container execution prerequisite."""
import os
import re
import subprocess
import threading
import time

from .services.rtl.worker_client import container_mode, configured_image


class WorkerReadiness:
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.lock = threading.Lock()
        self.cached = None

    def cached_value(self, key):
        snapshot = self.cached
        if snapshot is not None and snapshot[0] == key and self.clock() < snapshot[2]:
            return snapshot[1]
        return None

    def ready(self):
        if not container_mode():
            return True
        image = configured_image()
        key = (image, *(os.environ.get(name) for name in (
            'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH')))
        cached = self.cached_value(key)
        if cached is not None:
            return cached
        # Do not accumulate waiting HTTP threads while Docker is unavailable.
        # During a cold/expired check, concurrent callers get not_ready.
        if not self.lock.acquire(blocking=False):
            return False
        try:
            cached = self.cached_value(key)
            if cached is not None:
                return cached
            value = False
            try:
                inspected = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
                                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, timeout=3)
                value = (inspected.returncode == 0 and
                         re.fullmatch(rb'sha256:[0-9a-f]{64}', inspected.stdout.strip()) is not None)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self.cached = (key, value, self.clock() + 5)
            return value
        finally:
            self.lock.release()
