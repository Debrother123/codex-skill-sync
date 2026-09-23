#!/usr/bin/env python3
"""Discover installed runtimes without installing software or changing credentials."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True


def normalize_path(value, platform=None):
    """Normalize MSYS drive paths only on Windows; preserve spaces and Unicode."""
    value = os.path.expandvars(os.path.expanduser(str(value)))
    if (platform or os.name) in {'nt', 'win32', 'windows'}:
        match = re.match(r'^/([a-zA-Z])(?:/|$)', value)
        if match:
            value = match.group(1).upper() + ':/' + value[match.end():]
    return Path(value)


def _executable(value):
    if not value:
        return None
    path = normalize_path(value)
    if path.is_file():
        return str(path.resolve())
    found = shutil.which(str(value))
    return str(Path(found).resolve()) if found else None


def probe_python(exe):
    """Return Python 3.9+ capabilities, or None for a missing/unusable runtime."""
    exe = _executable(exe)
    if not exe:
        return None
    code = ('import sys,json,importlib.util; '
            'print(json.dumps({"version":list(sys.version_info[:3]),'
            '"tk":importlib.util.find_spec("tkinter") is not None}))')
    try:
        result = subprocess.run([exe, '-I', '-c', code], capture_output=True,
                                text=True, encoding='utf-8', timeout=15)
        data = json.loads(result.stdout.strip())
        if result.returncode or tuple(data['version']) < (3, 9):
            return None
        # A module spec alone does not prove that the native Tk library loads.
        if data['tk']:
            # Apple's legacy Tk 8.5 can import successfully but render blank windows.
            check = subprocess.run([exe, '-I', '-c',
                'import sys,tkinter; import _tkinter; '
                'sys.exit(0 if sys.platform != "darwin" or tkinter.TkVersion >= 8.6 else 1)'],
                capture_output=True, timeout=15)
            data['tk'] = check.returncode == 0
        return {'python_exe': exe, 'python_version': data['version'], 'gui': bool(data['tk'])}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return None


def probe_git(exe):
    exe = _executable(exe)
    if not exe:
        return None
    try:
        result = subprocess.run([exe, '--version'], capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=15)
        return exe if result.returncode == 0 and result.stdout.startswith('git version ') else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _bundled_pythons():
    """Bounded search of common agent runtime caches, never the entire disk."""
    roots = [Path.home()/'.cache'/'codex-runtimes', Path.home()/'.workbuddy'/'binaries', Path.home()/'.codex']
    local = os.environ.get('LOCALAPPDATA')
    if local:
        roots.extend(Path(local)/'Programs'/name for name in ['Python', 'Codex', 'WorkBuddy'])
    seen_dirs = 0
    for root in roots:
        if not root.is_dir():
            continue
        for parent, dirs, names in os.walk(root, followlinks=False):
            seen_dirs += 1
            if seen_dirs > 1800:
                return
            depth = len(Path(parent).relative_to(root).parts)
            dirs[:] = [n for n in dirs if n not in {'.git','node_modules','__pycache__'}
                       and not (Path(parent)/n).is_symlink()] if depth < 10 else []
            for name in ('python.exe', 'python3', 'python'):
                if name in names:
                    yield str(Path(parent)/name)


def python_candidates():
    yield sys.executable
    for name in ('SKILL_SYNC_PYTHON', 'PYTHON_EXE', 'CODEX_PYTHON'):
        if os.environ.get(name):
            yield os.environ[name]
    for command in ('python3', 'python'):
        candidate = shutil.which(command)
        if candidate:
            yield candidate
    if os.name == 'nt':
        launcher = shutil.which('py')
        if launcher:
            try:
                result = subprocess.run([launcher, '-0p'], capture_output=True,
                                        text=True, errors='replace', timeout=15)
                for line in result.stdout.splitlines():
                    match = re.search(r'([A-Za-z]:[\\/].*python(?:w)?\.exe)\s*$', line, re.I)
                    if match:
                        yield match.group(1)
            except (OSError, subprocess.TimeoutExpired):
                pass
    else:
        yield '/usr/local/bin/python3'
        yield '/opt/homebrew/bin/python3'
    yield from _bundled_pythons()


def git_candidates():
    if os.environ.get('SKILL_SYNC_GIT'):
        yield os.environ['SKILL_SYNC_GIT']
    yield shutil.which('git')
    if os.name == 'nt':
        for root in [Path.home()/'.workbuddy'/'binaries'/'PortableGit'/'versions']:
            if root.is_dir():
                for candidate in sorted(root.glob('*/cmd/git.exe'),reverse=True):yield str(candidate)
        for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)'),
                     os.environ.get('LOCALAPPDATA')):
            if base:
                for rel in ('Git/cmd/git.exe', 'Git/bin/git.exe', 'Programs/Git/cmd/git.exe'):
                    yield str(Path(base)/rel)
        # Portable runtimes sometimes place Git beside Python.
        for base in (Path(sys.executable).parent, Path(sys.executable).parent.parent):
            yield str(base/'git'/'cmd'/'git.exe')
            yield str(base/'git.exe')


def discover_runtime(python_exe=None, git_exe=None, cli=False):
    """Prefer actual Python, find Tk if possible; allow offline init without Git.

    Explicit executable paths are validated and never silently substituted.
    With no explicit Python, a discovered Tk runtime wins over a CLI-only one.
    """
    chosen = probe_python(python_exe) if python_exe else None
    if python_exe and chosen is None:
        raise RuntimeError('指定 Python 无法运行或版本低于 3.9：' + str(python_exe))
    if chosen is None or (not cli and not chosen['gui']):
        seen = set()
        fallback = chosen
        chosen = None
        for candidate in python_candidates():
            resolved = _executable(candidate)
            if not resolved or resolved in seen:
                continue
            seen.add(resolved)
            found = probe_python(resolved)
            if found:
                fallback = fallback or found
                if cli or found['gui']:
                    chosen = found
                    break
        chosen = chosen or fallback
    if chosen is None:
        raise RuntimeError('找不到可用 Python 3.9+，请接入智能体提供 --python-exe 的实际路径。')
    chosen = dict(chosen)
    chosen['gui'] = chosen['gui'] and not cli
    if git_exe:
        git = probe_git(git_exe)
        if git is None:
            raise RuntimeError('指定 Git 无法运行：' + str(git_exe))
    else:
        git = next((found for candidate in git_candidates() if candidate
                    for found in [probe_git(candidate)] if found), None)
    chosen['git_exe'] = git
    return chosen


def launch(argv=None):
    parser = argparse.ArgumentParser(description='使用已登记或已发现的运行时启动同步助手')
    parser.add_argument('--profile')
    parser.add_argument('--cli', action='store_true')
    parser.add_argument('--python-exe')
    parser.add_argument('--git-exe')
    args = parser.parse_args(argv)
    import bootstrap
    profile = args.profile or bootstrap.registry().get('active')
    saved = bootstrap.activate(profile).get('runtime', {}) if profile else {}
    runtime = discover_runtime(args.python_exe or saved.get('python_exe'),
                               args.git_exe or saved.get('git_exe'),
                               args.cli or (bool(saved) and not saved.get('gui', True)))
    env = dict(os.environ)
    if runtime['git_exe']:
        env['SKILL_SYNC_GIT'] = runtime['git_exe']
        env['PATH'] = str(Path(runtime['git_exe']).parent) + os.pathsep + env.get('PATH', '')
    env['PYTHONUTF8'] = '1'
    entry = 'skill_sync_gui.py' if runtime['gui'] else 'skill_sync.py'
    if not runtime['gui']:
        print('当前使用命令行菜单；未启用 Tk 图形界面。', flush=True)
    command = [runtime['python_exe'], str(Path(__file__).parent/entry)]
    if profile:
        command.extend(['--profile', profile])
    return subprocess.call(command, env=env)


if __name__ == '__main__':
    try:
        sys.exit(launch())
    except (RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
