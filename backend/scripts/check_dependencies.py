"""Check direct requirements, hashed pins and installed versions on this platform."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import sys

from packaging.requirements import Requirement, InvalidRequirement
from packaging.utils import canonicalize_name


class DependencyError(ValueError):
    pass


def requirements(path, *, locked):
    text = Path(path).read_text(encoding='utf-8').replace('\\\n', ' ')
    entries = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        hashes = re.findall(r'\s+--hash=sha256:([a-f0-9]{64})(?=\s|$)', line)
        if locked:
            if not hashes:
                raise DependencyError('Every locked requirement must have a SHA-256 hash.')
            line = re.sub(r'\s+--hash=sha256:[a-f0-9]{64}(?=\s|$)', '', line).strip()
        try:
            item = Requirement(line)
        except InvalidRequirement:
            raise DependencyError('Unsupported or malformed requirement syntax.') from None
        if item.url or item.extras:
            raise DependencyError('Direct URLs and extras require an explicitly supported dependency-check workflow.')
        if locked and (len(item.specifier) != 1 or any(pin.operator != '==' or '*' in pin.version for pin in item.specifier)):
            raise DependencyError(f'{item.name}: lock must contain one exact version.')
        if item.marker is not None and not item.marker.evaluate():
            continue
        name = canonicalize_name(item.name)
        if name in entries:
            raise DependencyError(f'{name}: overlapping requirements on this platform.')
        entries[name] = item
    return entries


def check(direct_path, lock_path, installed_version=version):
    direct = requirements(direct_path, locked=False)
    locked = requirements(lock_path, locked=True)
    for name, requirement in direct.items():
        if name not in locked:
            raise DependencyError(f'{name}: direct requirement is missing from the active lock.')
        pinned = next(iter(locked[name].specifier)).version
        if not requirement.specifier.contains(pinned, prereleases=True):
            raise DependencyError(f'{name}: locked version does not satisfy requirements.in; regenerate the lock.')
    for name, requirement in locked.items():
        pinned = next(iter(requirement.specifier)).version
        try:
            installed = installed_version(name)
        except PackageNotFoundError:
            raise DependencyError(f'{name}: locked package is not installed.') from None
        if installed != pinned:
            raise DependencyError(f'{name}: installed version differs from the lock; use a fresh environment.')
    return len(direct), len(locked)


def main():
    root = Path(__file__).resolve().parents[1]
    try:
        direct, locked = check(root / 'requirements.in', root / 'requirements.txt')
    except (DependencyError, OSError) as error:
        print(f'Dependency check failed: {error}', file=sys.stderr)
        return 1
    print(f'Dependency check passed: {direct} direct, {locked} locked packages match this environment.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
