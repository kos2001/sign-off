import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

path = Path(__file__).resolve().parents[2] / 'scripts/self_improve.py'
spec = importlib.util.spec_from_file_location('improvement_loop', path)
loop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loop)


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    (root / '.gitignore').write_text('.self-improve/\n__pycache__/\n')
    (root / 'app.py').write_text('value = 0\n')
    (root / 'check.py').write_text('from app import value\nassert value == 1\n')
    (root / 'improvement-loop.json').write_text(json.dumps({
        'goal': 'Fix app.value so the immutable acceptance check passes',
        'checks': [{'name': 'acceptance', 'cwd': '.', 'argv': [sys.executable, 'check.py']}],
        'protected': ['check.py', 'improvement-loop.json', '.gitignore'],
    }))
    return root


def run(root, code, *extra):
    status = loop.main(['run', '--root', str(root), '--max-iterations', '2', '--max-seconds', '30', '--agent-command', json.dumps([sys.executable, '-c', code]), *extra])
    output = sorted((root / '.self-improve').glob('*/report.json'))[-1]
    return status, json.loads(output.read_text()), output.parent


def test_failure_fix_verify_and_patch_preserve_dirty_source(repository):
    (repository / 'untracked.txt').write_text('existing user work')
    (repository / '.env.private').write_text('excluded private fixture')
    original = loop.files(repository)
    status, report, output = run(repository, "from pathlib import Path; Path('app.py').write_text('value = 1\\n')")
    assert status == 0
    assert report['accepted'] == 1
    assert report['iterations'][0]['status'] == 'verified_candidate'
    assert report['iterations'][1]['status'] == 'no_change'
    assert report['baseline_checks'][0]['exit_code'] != 0
    assert report['iterations'][0]['checks'][0]['exit_code'] == 0
    assert report['source_unchanged'] and loop.files(repository) == original
    assert (repository / 'app.py').read_text() == 'value = 0\n'
    assert '+value = 1' in (output / 'changes.patch').read_text()
    assert (output / 'candidate/untracked.txt').read_text() == 'existing user work'
    assert not (output / 'candidate/.env.private').exists()
    subprocess.run(['git', '-C', str(repository), 'apply', '--check', str(output / 'changes.patch')], check=True)


@pytest.mark.parametrize('code, expected', [
    ("from pathlib import Path; Path('check.py').write_text('pass\\n')", 'protected_change_rejected'),
    ("pass", 'no_change'),
    ("from pathlib import Path; Path('app.py').write_text('value = 2\\n')", 'regression_rejected'),
    ("raise SystemExit(4)", 'agent_failed'),
])
def test_rejection_and_no_progress_stop(repository, code, expected):
    status, report, output = run(repository, code)
    assert status == 1
    assert report['status'] == 'stalled'
    assert report['accepted'] == 0
    assert [entry['status'] for entry in report['iterations']] == [expected, expected]
    assert not (output / 'changes.patch').exists()
    assert (repository / 'app.py').read_text() == 'value = 0\n'


def test_checker_cannot_rewrite_a_changed_source_file(repository):
    (repository / 'check.py').write_text("from app import value\nassert value == 1\nfrom pathlib import Path\nPath('app.py').write_text('value = 2\\n')\n")
    status, report, _ = run(repository, "from pathlib import Path; Path('app.py').write_text('value = 1\\n')")
    assert status == 1
    assert report['accepted'] == 0
    assert report['iterations'][0]['status'] == 'checker_changed_source'


def test_live_lock_prevents_second_loop(repository):
    output = repository / '.self-improve'
    output.mkdir()
    with loop.loop_lock(output):
        assert loop.main(['check', '--root', str(repository)]) == 2


def test_timeout_and_log_limit(tmp_path, monkeypatch):
    result = loop.run_command([sys.executable, '-c', 'import time; time.sleep(10)'], tmp_path, tmp_path / 'timeout.log', 0.1)
    assert result['error'] == 'command timeout' and result['exit_code'] != 0
    monkeypatch.setattr(loop, 'MAX_LOG_BYTES', 64)
    result = loop.run_command([sys.executable, '-c', 'print("x" * 10000)'], tmp_path, tmp_path / 'large.log', 10)
    assert result['error'] == 'log size limit exceeded'
    assert (tmp_path / 'large.log').stat().st_size <= 64



def test_opt_in_apply_requires_unchanged_baseline(repository):
    status, report, _ = run(repository, "from pathlib import Path; Path('app.py').write_text('value = 1\\n')", '--max-iterations', '1', '--apply')
    assert status == 0 and report['applied']
    assert (repository / 'app.py').read_text() == 'value = 1\n'


def test_concurrent_source_edit_blocks_apply(repository):
    code = "from pathlib import Path; Path('app.py').write_text('value = 1\\n'); Path(" + repr(str(repository / 'untracked.txt')) + ").write_text('concurrent user edit')"
    status, report, output = run(repository, code, '--max-iterations', '1', '--apply')
    assert status == 1 and report['status'] == 'error'
    assert 'source changed since baseline' in report['error']
    assert (repository / 'app.py').read_text() == 'value = 0\n'
    assert (repository / 'untracked.txt').read_text() == 'concurrent user edit'
    assert (output / 'changes.patch').exists()



def test_shared_dependencies_are_not_source_or_patch(repository):
    dependency = repository / 'backend/.venv'
    dependency.mkdir(parents=True)
    (dependency / 'marker').write_text('shared dependency')
    status, report, output = run(repository, "from pathlib import Path; Path('app.py').write_text('value = 1\\n')", '--max-iterations', '1')
    assert status == 0, report
    assert (output / 'candidate/backend/.venv').is_symlink()
    assert 'backend/.venv' not in (output / 'changes.patch').read_text()
    assert not any(name.startswith('backend/.venv') for name in report['source_files'])


def test_environment_cannot_redirect_git_or_skip_configured_checks(repository, monkeypatch):
    for key in ['GIT_DIR', 'GIT_WORK_TREE', 'PYTHONPATH', 'PYTEST_ADDOPTS', 'SIGNOFF_DATABASE_URL', 'OPENAI_API_KEY']:
        monkeypatch.setenv(key, 'unwanted-inherited-setting')
    assert 'app.py' in loop.files(repository)
    result = loop.run_command([sys.executable, '-c', "import os; assert not any(key in os.environ for key in ['GIT_DIR', 'GIT_WORK_TREE', 'PYTHONPATH', 'PYTEST_ADDOPTS', 'SIGNOFF_DATABASE_URL', 'OPENAI_API_KEY'])"], repository, repository / 'environment.log', 10)
    assert result['exit_code'] == 0 and not result['error']
