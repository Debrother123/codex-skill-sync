#!/usr/bin/env python3
"""Idempotent local onboarding for any agent with a user-verified skills directory."""
import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shlex
import sys
sys.dont_write_bytecode = True
import time
import skill_sync as engine
import runtime_support as runtime

BASE = runtime.normalize_path(os.environ.get('SKILL_SYNC_HOME', str(Path.home()/'.codex-skill-sync'))).resolve()
REGISTRY = BASE/'profiles.json'
INITIAL_GIT = os.environ.get('SKILL_SYNC_GIT')
PATTERN = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')


def registry():
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding='utf-8'))
    profiles = {}
    # Older config stays where it is: no destructive migration of state or baselines.
    if (BASE/'config.json').exists():
        c=json.loads((BASE/'config.json').read_text(encoding='utf-8'))
        profiles['legacy']={'name':'原有环境','skills_dir':c['root'],'state_dir':str(BASE),'variant':'shared'}
    return {'active':next(iter(profiles),None),'profiles':profiles}


def activate(profile):
    r=registry()
    if profile not in r['profiles']:raise RuntimeError('环境未登记：'+profile)
    meta=r['profiles'][profile]
    engine.HOME=Path(meta['state_dir'])
    engine.CONFIG=engine.HOME/'config.json'
    engine.DEFAULT_ROOT=meta['skills_dir']
    engine.DEFAULT_VARIANT=meta.get('variant','shared')
    git_exe=meta.get('runtime',{}).get('git_exe')
    if git_exe:os.environ['SKILL_SYNC_GIT']=git_exe
    elif INITIAL_GIT:os.environ['SKILL_SYNC_GIT']=INITIAL_GIT
    else:os.environ.pop('SKILL_SYNC_GIT',None)
    r['active']=profile;engine.save(REGISTRY,r)
    return meta


def launcher_content(profile, meta, windows=None):
    """Render an absolute, profile-specific launcher; no PATH Python assumption."""
    windows = os.name == 'nt' if windows is None else windows
    capabilities=meta['runtime']
    entry='skill_sync_gui.py' if capabilities['gui'] else 'skill_sync.py'
    script=Path(meta['skills_dir'])/'codex-skill-sync'/'scripts'/entry
    shortcuts=Path(meta['shortcut_dir'])
    python_exe=capabilities['python_exe']
    git_exe=capabilities.get('git_exe')
    if windows:
        # Percent expansion is active even inside quotes; reject those rare paths.
        for value in [str(script),str(BASE),python_exe,git_exe or '']:
            if any(ch in value for ch in ['%', '\n', '\r', '"']):
                raise RuntimeError('启动路径含不支持的批处理字符')
        launcher=shortcuts/('Skills同步助手-'+profile+'.bat')
        lines=['@echo off','setlocal DisableDelayedExpansion','chcp 65001 >nul',
               'set "PYTHONUTF8=1"','set "PYTHONDONTWRITEBYTECODE=1"','set "SKILL_SYNC_HOME='+str(BASE)+'"',
               'set "PYTHON_EXE='+python_exe+'"']
        if git_exe:
            lines.extend(['set "SKILL_SYNC_GIT='+git_exe+'"',
                          'set "PATH='+str(PureWindowsPath(git_exe).parent)+';%PATH%"'])
        lines.extend(['"%PYTHON_EXE%" "'+str(script)+'" --profile '+profile,
                      'if errorlevel 1 pause'])
        return launcher,'\n'.join(lines)+'\n'
    launcher=shortcuts/('Skills同步助手-'+profile+'.command')
    lines=['#!/bin/sh','export PYTHONUTF8=1','export PYTHONDONTWRITEBYTECODE=1','export SKILL_SYNC_HOME='+shlex.quote(str(BASE))]
    if git_exe:
        lines.extend(['export SKILL_SYNC_GIT='+shlex.quote(git_exe),
                      'export PATH='+shlex.quote(str(Path(git_exe).parent))+':"$PATH"'])
    lines.append('exec '+shlex.quote(python_exe)+' '+shlex.quote(str(script))+' --profile '+shlex.quote(profile))
    return launcher,'\n'.join(lines)+'\n'


def initialize(profile, name, skills_dir, shortcut_dir, variant='shared',
               python_exe=None, git_exe=None, state_home=None, cli=False, refresh_launcher=False):
    global BASE, REGISTRY
    if state_home is not None:
        BASE=runtime.normalize_path(state_home).resolve()
        REGISTRY=BASE/'profiles.json'
        os.environ['SKILL_SYNC_HOME']=str(BASE)
    if not PATTERN.fullmatch(profile) or (variant!='shared' and not PATTERN.fullmatch(variant)):
        raise RuntimeError('环境 ID/专用版本名仅用小写字母、数字、短横线或下划线。')
    target_root=runtime.normalize_path(skills_dir).resolve()
    shortcuts=runtime.normalize_path(shortcut_dir).resolve()
    if not target_root.is_dir() or not shortcuts.is_dir():
        raise RuntimeError('请由接入智能体先确认并创建实际 skills 目录与用户指定的快捷方式目录。')
    capabilities=runtime.discover_runtime(python_exe,git_exe,cli)
    r=registry();existing=r['profiles'].get(profile)
    state=BASE/'profiles'/profile
    meta={'name':name,'skills_dir':str(target_root),'state_dir':str(state),'variant':variant,'shortcut_dir':str(shortcuts)}
    if existing and any(existing.get(k)!=v for k,v in meta.items()):
        raise RuntimeError('该环境已登记为不同配置，请保留原环境并使用新的环境 ID。')
    for pid, other in r['profiles'].items():
        if pid!=profile and Path(other['skills_dir']).resolve()==target_root:
            raise RuntimeError('该 skills 目录已由另一个环境管理：'+pid)
    meta['runtime']=capabilities
    launcher,content=launcher_content(profile,meta)
    launcher_changed=launcher.exists() and launcher.read_text(encoding='utf-8')!=content
    if launcher_changed and not (refresh_launcher and existing):
        raise RuntimeError('同名快捷方式已有其他内容，未覆盖；已登记环境可显式使用 --refresh-launcher 备份更新：'+str(launcher))
    source=Path(__file__).resolve().parent.parent
    target=target_root/'codex-skill-sync'
    source_hash=engine.files(source)
    if target.exists() and engine.files(target)!=source_hash:
        raise RuntimeError('同名管理 skill 内容不同。请接入智能体比较并备份更新后再初始化。')
    state.mkdir(parents=True,exist_ok=True)
    old_home=engine.HOME;engine.HOME=state
    try:
        if not target.exists():engine.replace_tree(source,target,source_hash)
    finally:engine.HOME=old_home
    if launcher_changed:
        backup=state/'launcher-backups'/(str(time.time_ns())+'-'+launcher.name)
        backup.parent.mkdir(parents=True,exist_ok=True)
        import shutil
        shutil.copy2(launcher,backup)
        launcher.write_text(content,encoding='utf-8')
        print('旧启动入口备份：',backup)
    elif not launcher.exists():
        with launcher.open('x',encoding='utf-8') as f:f.write(content)
    launcher.chmod(0o755)
    r['profiles'][profile]=meta;r['active']=profile
    engine.save(REGISTRY,r)
    print('环境已登记：'+name+'\nSkills：'+str(target_root)+'\n快捷方式：'+str(launcher))
    print('运行时：'+capabilities['python_exe']+'；界面：'+('GUI' if capabilities['gui'] else 'CLI 数字菜单'))
    if not capabilities['git_exe']:print('未发现 Git；本地登记已完成，联网同步前请接入智能体安装或指定 --git-exe。')
    print('本地初始化完成。GitHub 连接和智能体适配验证分别检查，不因登记成功而宣称完成。')
    return meta


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='智能体首次接入：安装同步工具、登记环境并生成快捷方式')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('init')
    for flag in ['profile','name','skills-dir','shortcut-dir']:p.add_argument('--'+flag,required=True)
    p.add_argument('--variant',default='shared')
    p.add_argument('--python-exe')
    p.add_argument('--git-exe')
    p.add_argument('--state-home')
    p.add_argument('--cli',action='store_true')
    p.add_argument('--refresh-launcher',action='store_true')
    sub.add_parser('list')
    args=parser.parse_args()
    try:
        if args.command=='list':print(json.dumps(registry(),ensure_ascii=False,indent=2))
        else:initialize(args.profile,args.name,args.skills_dir,args.shortcut_dir,args.variant,
                        args.python_exe,args.git_exe,args.state_home,args.cli,args.refresh_launcher)
    except (RuntimeError,OSError,ValueError) as e:
        parser.exit(1,str(e)+'\n')
