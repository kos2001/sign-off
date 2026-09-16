#!/usr/bin/env python3
"""Bounded, isolated development loop. Source changes require --apply."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

MAX_LOG_BYTES = 8 * 1024 * 1024


def save_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def git(root, *args):
    environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    return subprocess.check_output(['git', '-C', str(root), *args], env=environment, stderr=subprocess.PIPE, timeout=30)


def files(root):
    paths = set(git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0'))
    result = {}
    for name in sorted(paths - {''}):
        path = root / name
        if any(name == dep or name.startswith(dep + '/') for dep in ['backend/.venv', 'frontend/node_modules']):
            continue
        if name.startswith('.self-improve/') or path.name.startswith('.env') and path.name != '.env.example' or path.suffix in {'.db', '.sqlite', '.sqlite3'}:
            continue
        if path.is_symlink():
            # Dependencies are linked by this controller and ignored by git.
            raise ValueError(f'source symlinks are not supported: {name}')
        if not path.is_file():
            continue
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError(f'source file is too large: {name}')
        result[name] = hashlib.sha256(path.read_bytes() + str(path.stat().st_mode & 0o111).encode()).hexdigest()
    return result


def snapshot(source, destination, dependencies):
    before = files(source)
    destination.mkdir(parents=True)
    for name in before:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    git(destination, 'init', '-q')
    with (destination / '.git/info/exclude').open('a') as exclusions:
        exclusions.write('\n/backend/.venv\n/frontend/node_modules\n')
    git(destination, 'add', '.')
    git(destination, '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', '-c', 'user.name=Sign-off Improvement Loop', '-c', 'user.email=local-loop@localhost', 'commit', '-q', '--allow-empty', '-m', 'Isolated baseline')
    if files(destination) != before or files(source) != before:
        raise ValueError('source changed during snapshot; retry when edits have settled')
    for name in ['backend/.venv', 'frontend/node_modules']:
        dependency = dependencies / name
        if dependency.exists():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(dependency, target_is_directory=True)
    return before


def run_command(argv, cwd, log, timeout, *, stdin=None, model=False):
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(('SIGNOFF_', 'GIT_')) or key in {'PYTHONPATH', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'} or not model and key in {'OPENAI_API_KEY', 'CODEX_API_KEY'}:
            env.pop(key)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    started = time.monotonic()
    error = None
    with log.open('wb') as output:
        with (stdin.open('rb') if stdin else open(os.devnull, 'rb')) as input_file:
            try:
                process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=input_file, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError as exc:
                output.write(str(exc).encode())
                return {'exit_code': None, 'error': str(exc), 'seconds': 0, 'log': str(log)}
            try:
                while process.poll() is None:
                    if time.monotonic() - started >= timeout:
                        error = 'command timeout'
                        break
                    if log.stat().st_size > MAX_LOG_BYTES:
                        error = 'log size limit exceeded'
                        break
                    time.sleep(0.1)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
    if log.stat().st_size > MAX_LOG_BYTES:
        error = 'log size limit exceeded'
        with log.open('r+b') as file:
            file.truncate(MAX_LOG_BYTES)
    return {'exit_code': process.returncode, 'error': error, 'seconds': round(time.monotonic() - started, 2), 'log': str(log)}


def check_workspace(workspace, config, output, python, deadline, timeout):
    results = []
    for index, check in enumerate(config['checks']):
        cwd = (workspace / check['cwd']).resolve()
        if not cwd.is_relative_to(workspace.resolve()):
            raise ValueError('check cwd must remain inside the workspace')
        argv = [arg.replace('{python}', python) for arg in check['argv']]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            results.append({'name': check['name'], 'exit_code': None, 'error': 'loop deadline reached'})
            break
        result = run_command(argv, cwd, output / f'check-{index}.log', min(timeout, remaining))
        results.append({'name': check['name'], **result})
    return results


def green(results, config):
    return len(results) == len(config['checks']) and all(r['exit_code'] == 0 and not r['error'] for r in results)


def protected_changes(before, after, protected):
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    forbidden = {name for name in changed if any(name == rule or rule.endswith('/') and name.startswith(rule) for rule in protected)}
    return sorted(changed), sorted(forbidden)


@contextmanager
def loop_lock(root):
    with (root / 'lock').open('a') as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another improvement loop is running')
        yield


def execute(args):
    root = Path(args.root).resolve()
    config = json.loads((root / args.config).read_text())
    if not isinstance(config.get('checks'), list) or not config['checks'] or not all(isinstance(c, dict) and isinstance(c.get('cwd'), str) and isinstance(c.get('name'), str) and isinstance(c.get('argv'), list) and c['argv'] and all(isinstance(a, str) for a in c['argv']) for c in config['checks']):
        raise ValueError('configure at least one check with a name, cwd, and argv array')
    if not isinstance(config.get('protected'), list) or not all(isinstance(p, str) and p for p in config['protected']) or not isinstance(config.get('goal'), str):
        raise ValueError('config requires protected path list and goal text')
    output_root = root / '.self-improve'
    output_root.mkdir(exist_ok=True, mode=0o700)
    output_root.chmod(0o700)
    with loop_lock(output_root):
        output = output_root / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8])
        output.mkdir()
        python = str(root / 'backend/.venv/bin/python') if (root / 'backend/.venv/bin/python').exists() else sys.executable
        deadline = time.monotonic() + args.max_seconds
        report = {'source': str(root), 'goal': args.goal or config['goal'], 'status': 'running', 'iterations': [], 'accepted': 0, 'note': 'Passing configured checks proves regression checks only, not product completeness.'}
        save_json(output / 'report.json', report)
        print(f'Run directory: {output}', flush=True)
        try:
            baseline = output / 'baseline'
            report['source_files'] = snapshot(root, baseline, root)
            results = check_workspace(baseline, config, output, python, deadline, args.command_timeout)
            if files(baseline) != report['source_files']:
                raise ValueError('baseline check changed source files')
            report['baseline_checks'] = results
            accepted = baseline
            if args.command == 'check':
                report['status'] = 'checks_passed' if green(results, config) else 'checks_failed'
            else:
                stalled = 0
                for number in range(1, args.max_iterations + 1):
                    if time.monotonic() >= deadline:
                        report['status'] = 'time_limit'
                        break
                    iteration = output / f'iteration-{number}'
                    workspace = iteration / 'workspace'
                    before = snapshot(accepted, workspace, root)
                    prompt = iteration / 'prompt.txt'
                    tails = []
                    for result in results:
                        if result.get('log'):
                            tails.append(Path(result['log']).read_text(errors='replace')[-6000:])
                    prompt.write_text(
                        f"Objective: {report['goal']}\nIteration: {number}\n"
                        "Inspect current code and make ONE concrete, useful improvement. Work only in this isolated checkout. "
                        "Do not access services, databases, source worktrees, credentials, external applications, or publish anything. "
                        "Do not spawn other agents. Do not commit changes or weaken existing tests/checks. "
                        f"Do not modify these protected paths: {config['protected']}. "
                        "Prefer fixing evidenced failures. When checks already pass, improve a real user workflow within the objective. "
                        "Finish with a concise explanation of problem, change, evidence, and remaining limitations. "
                        "Do not claim the entire product is complete.\n"
                        f"Previous iteration: {json.dumps(report['iterations'][-1:] , ensure_ascii=False)}\n"
                        f"Last evaluated checks (may describe a rejected candidate): {json.dumps(results, ensure_ascii=False)}\nLogs:\n" + '\n'.join(tails))
                    argv = json.loads(args.agent_command) if args.agent_command else ['codex', 'exec', '--sandbox', 'workspace-write', '--json', '--output-last-message', str(iteration / 'agent-summary.txt'), '-']
                    if not isinstance(argv, list) or not argv or not all(isinstance(value, str) for value in argv):
                        raise ValueError('agent-command must be a JSON argv array')
                    print(f'Iteration {number}: proposing one improvement', flush=True)
                    agent = run_command(argv, workspace, iteration / 'agent.log', min(args.command_timeout, deadline - time.monotonic()), stdin=prompt, model=True)
                    candidate_files = files(workspace)
                    changed, forbidden = protected_changes(before, candidate_files, config['protected'])
                    entry = {'number': number, 'agent': agent, 'changed': changed, 'protected_changes': forbidden, 'workspace': str(workspace)}
                    if agent['exit_code'] != 0 or agent['error']:
                        entry['status'] = 'agent_failed'
                    elif forbidden:
                        entry['status'] = 'protected_change_rejected'
                    elif not changed:
                        entry['status'] = 'no_change'
                    else:
                        candidate_results = check_workspace(workspace, config, iteration, python, deadline, args.command_timeout)
                        entry['checks'] = candidate_results
                        results = candidate_results
                        if green(candidate_results, config):
                            # Checkers must not change tracked source while evaluating it.
                            if files(workspace) != candidate_files:
                                entry['status'] = 'checker_changed_source'
                            else:
                                accepted = workspace
                                report['accepted'] += 1
                                entry['status'] = 'verified_candidate'
                        else:
                            entry['status'] = 'regression_rejected'
                    stalled = 0 if entry['status'] == 'verified_candidate' else stalled + 1
                    report['iterations'].append(entry)
                    save_json(output / 'report.json', report)
                    print(f"Iteration {number}: {entry['status']}", flush=True)
                    if stalled >= args.stop_after:
                        report['status'] = 'stalled'
                        break
                else:
                    report['status'] = 'iteration_limit'
            if report['accepted']:
                exported = output / 'candidate'
                snapshot(baseline, exported, root)
                final_files = files(accepted)
                for name in report['source_files'].keys() - final_files.keys():
                    (exported / name).unlink()
                for name in final_files:
                    target = exported / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(accepted / name, target)
                # Rebuild the scratch index so coarse filesystem timestamps cannot hide a change.
                git(exported, 'read-tree', '--empty')
                git(exported, 'add', '--all', '.')
                (output / 'changes.patch').write_bytes(git(exported, 'diff', 'HEAD', '--binary'))
                report['candidate'] = str(exported)
                if args.apply:
                    if files(root) != report['source_files']:
                        raise ValueError('source changed since baseline; patch was not applied')
                    git(root, 'apply', '--check', str(output / 'changes.patch'))
                    git(root, 'apply', str(output / 'changes.patch'))
                    report['applied'] = True
            report['source_unchanged'] = files(root) == report['source_files']
        except KeyboardInterrupt:
            report['status'] = 'interrupted'
        except Exception as error:
            report['status'] = 'error'
            report['error'] = str(error)
        finally:
            save_json(output / 'report.json', report)
            print(json.dumps({'status': report['status'], 'accepted': report['accepted'], 'report': str(output / 'report.json')}, ensure_ascii=False), flush=True)
        return 0 if report['status'] == 'checks_passed' or report['accepted'] and report['status'] not in {'error', 'interrupted'} else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'run'])
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--config', default='improvement-loop.json')
    parser.add_argument('--goal')
    parser.add_argument('--apply', action='store_true', help='Apply a verified patch only if source still matches the initial snapshot')
    parser.add_argument('--max-iterations', type=int, default=3)
    parser.add_argument('--max-seconds', type=int, default=1800)
    parser.add_argument('--command-timeout', type=int, default=600)
    parser.add_argument('--stop-after', type=int, default=2)
    parser.add_argument('--agent-command', help='Testing/custom adapter only: JSON argv array, prompt arrives on stdin')
    args = parser.parse_args(argv)
    if args.apply and args.command != 'run':
        parser.error('--apply requires run mode')
    if min(args.max_iterations, args.max_seconds, args.command_timeout, args.stop_after) <= 0:
        parser.error('limits must be positive integers')
    try:
        return execute(args)
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
