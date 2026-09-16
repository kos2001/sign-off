from importlib.metadata import PackageNotFoundError
from pathlib import Path
import importlib.util

import pytest

spec = importlib.util.spec_from_file_location('dependency_check', Path(__file__).resolve().parents[1] / 'scripts/check_dependencies.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def files(tmp_path, direct='Example>=1.0', locked='example==1.2', hashes=True):
    source, lock = tmp_path / 'requirements.in', tmp_path / 'requirements.txt'
    source.write_text(direct + '\n')
    suffix = ' \\\n    --hash=sha256:' + 'a' * 64 if hashes else ''
    lock.write_text(locked + suffix + '\n')
    return source, lock


def test_consistent_names_versions_and_continuations(tmp_path):
    assert checker.check(*files(tmp_path), installed_version=lambda name: '1.2') == (1, 1)


@pytest.mark.parametrize('direct', ['example>=2', 'another>=1'])
def test_direct_requirement_change_requires_compatible_lock(tmp_path, direct):
    with pytest.raises(checker.DependencyError):
        checker.check(*files(tmp_path, direct=direct), installed_version=lambda name: '1.2')


@pytest.mark.parametrize('locked,hashes', [('example>=1', True), ('example==1.*', True), ('example==1.2', False),
    ('example==1.2 --hash=sha256:short', False), ('example @ https://example.invalid/wheel.whl', True)])
def test_invalid_or_unhashed_lock_is_rejected(tmp_path, locked, hashes):
    with pytest.raises(checker.DependencyError):
        checker.check(*files(tmp_path, locked=locked, hashes=hashes), installed_version=lambda name: '1.2')


def test_missing_or_drifted_installation_is_rejected(tmp_path):
    paths = files(tmp_path)
    with pytest.raises(checker.DependencyError, match='differs'):
        checker.check(*paths, installed_version=lambda name: '1.3')
    def missing(name):
        raise PackageNotFoundError(name)
    with pytest.raises(checker.DependencyError, match='not installed'):
        checker.check(*paths, installed_version=missing)


def test_inactive_platform_package_is_not_required(tmp_path):
    paths = files(tmp_path, direct='example>=1; python_version < "1"', locked='example==1.2; python_version < "1"')
    assert checker.check(*paths, installed_version=lambda name: pytest.fail('inactive marker')) == (0, 0)


def test_active_transitive_packages_are_checked(tmp_path):
    paths = files(tmp_path, direct='# no direct dependency')
    with pytest.raises(checker.DependencyError, match='differs'):
        checker.check(*paths, installed_version=lambda name: '2.0')


def test_repository_environment_matches_lock():
    root = Path(__file__).resolve().parents[1]
    direct, locked = checker.check(root / 'requirements.in', root / 'requirements.txt')
    assert direct > 0 and locked >= direct
