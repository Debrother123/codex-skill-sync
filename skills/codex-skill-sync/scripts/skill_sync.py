#!/usr/bin/env python3
"""Interactive, dependency-free skill synchronizer. Python 3.9+ and Git."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
import tempfile
import time
import sync_support as support
from runtime_support import normalize_path

HOME = normalize_path(os.environ.get('SKILL_SYNC_HOME', str(Path.home() / '.codex-skill-sync')))
CONFIG = HOME / 'config.json'
DEFAULT_ROOT = None
DEFAULT_VARIANT = 'shared'
SAFE_NAME = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
IGNORE = {'.DS_Store', 'Thumbs.db', '__pycache__', '.git', 'node_modules', '.venv', '.cache'}
SECRET = re.compile(rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{32,}')


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.sync-state-', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def git_error(stderr):
    value=stderr.lower()
    if any(x in value for x in ['could not read username','authentication failed','401','terminal prompts disabled']):
        return 'Git 认证不可用。请复用本机凭据管理器，或执行 auth --device 由本人完成设备授权；不要发送令牌。'
    if any(x in value for x in ['403','permission denied','access denied']):
        return 'Git 拒绝访问：检查当前身份、仓库权限与凭据有效性；不会自动扩大权限。'
    if any(x in value for x in ['404','not found']):
        return '无法访问仓库：可能地址错误、未登录或无该私有仓库权限，仅凭 404 无法区分。'
    if any(x in value for x in ['resolve host','connect','timed out','ssl','certificate']):
        return 'Git 网络/证书连接失败，请检查网络和系统证书；不会绕过证书验证。'
    if any(x in value for x in ['non-fast-forward','fetch first','rejected']):
        return '远端已变化或拒绝提交；本机提交已保留。请检查分叉后普通推送，不要强推。'
    return 'Git 操作失败，现场已保留。请当前智能体检查仓库分支、提交身份和本机 Git 配置。'


def git(repo, *args, allow_fail=False):
    p = subprocess.run([os.environ.get('SKILL_SYNC_GIT') or shutil.which('git') or 'git', '-C', str(repo), *args], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120,
                       env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    if p.returncode and not allow_fail:
        # Do not echo remote URLs or credential-helper diagnostics.
        raise RuntimeError('Git 操作失败（%s）。现场已保留；请当前智能体 检查仓库、网络或本机认证。' % args[0])
    return p.stdout.strip() if not p.returncode else None


def files(root):
    from local_sources import is_link
    if any(is_link(p) for p in [root, *root.parents]):
        raise RuntimeError('不自动同步符号链接目录：' + root.name)
    if not root.exists():
        return None
    if not root.is_dir() or not (root / 'SKILL.md').is_file():
        raise RuntimeError('不是完整的 skill：' + root.name)
    result = {}
    folded = {}
    def walk_error(error):
        raise error
    for parent, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        for name in dirs + names:
            if name.startswith('.env') and name in dirs:
                raise RuntimeError('发现潜在私密目录，停止同步：' + name)
            if is_link(Path(parent) / name):
                raise RuntimeError('发现符号链接，请先处理：' + name)
        dirs[:] = [n for n in dirs if n not in IGNORE]
        for name in names:
            if name in IGNORE or name.endswith('.pyc'):
                continue
            p = Path(parent) / name
            rel = p.relative_to(root).as_posix()
            if any(re.search(r'[\x00-\x1f<>:"\\|?*]|[. ]$', part) or part.split('.')[0].upper() in {'CON','PRN','AUX','NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))} for part in Path(rel).parts):
                raise RuntimeError('Windows 不兼容文件名：' + rel)
            parts = Path(rel).parts
            for i in range(1, len(parts) + 1):
                prefix = '/'.join(parts[:i])
                key = prefix.casefold()
                if key in folded and folded[key] != prefix:
                    raise RuntimeError('存在大小写冲突：' + rel)
                folded[key] = prefix
            if name.startswith('.env') or name in {'auth.json', 'credentials.json'} or p.suffix.lower() in {'.key','.pem','.p12'}:
                raise RuntimeError('发现潜在私密文件，停止同步：' + rel)
            if p.stat().st_size > 10 * 1024 * 1024:
                raise RuntimeError('文件超过本工具 10 MB 限制，请另行检查：' + rel)
            content = p.read_bytes()
            if SECRET.search(content):
                raise RuntimeError('发现疑似密钥，停止同步：' + rel)
            result[rel] = hashlib.sha256(content).hexdigest()
    return result


def replace_tree(source, target, expected):
    """Stage and verify before replacing, preserving an exact rollback copy."""
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.skill-sync-', dir=target.parent))
    backup = None
    try:
        for rel in expected:
            out = stage / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / rel, out)
        if files(stage) != expected:
            raise RuntimeError('源文件在操作期间发生变化，已停止。')
        if target.exists():
            backup = HOME / 'backups' / (str(time.time_ns()) + '-' + target.name)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(target, backup)
            shutil.rmtree(target)
        try:
            os.replace(stage, target)
            if files(target) != expected:
                raise RuntimeError('安装校验失败')
        except Exception:
            if target.exists():
                shutil.rmtree(target)
            if backup:
                shutil.copytree(backup, target)
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    if backup:
        print('覆盖旧版，备份：', backup)
    else:
        print('新增安装，无旧版需要备份：', target)
    return str(backup) if backup else None


def load():
    if not CONFIG.exists():
        raise RuntimeError('请先选择 1 完成首次配置。')
    c = json.loads(CONFIG.read_text(encoding='utf-8'))
    variant=c.get('variant','shared')
    if variant != 'shared' and not SAFE_NAME.fullmatch(variant):
        raise RuntimeError('无效专用版本名')
    for n in c['selected']:
        if not SAFE_NAME.fullmatch(n):
            raise RuntimeError('同步名单含无效名称')
    return c


def shared_root(c, repo):
    variant=c.get('variant','shared')
    return repo/'skills' if variant=='shared' else repo/'variants'/variant/'skills'


def shared_skill(c, repo, name):
    # The manager has one common release regardless of target-agent variants.
    return repo/'skills'/name if name=='codex-skill-sync' else shared_root(c,repo)/name


def local_skill(c, name):
    import local_sources
    return local_sources.resolve(c,name)


def available(c, repo):
    import local_sources
    local=local_sources.inventory(c)
    aliases={alias for info in local.values() for alias in info['aliases']}
    remote=shared_root(c,repo)
    names=set(local)|{p.name for p in remote.iterdir() if p.is_dir() and not p.is_symlink() and (p/'SKILL.md').is_file() and SAFE_NAME.fullmatch(p.name) and p.name not in aliases} if remote.is_dir() else set(local)
    if (repo/'skills'/'codex-skill-sync'/'SKILL.md').is_file():names.add('codex-skill-sync')
    return sorted(names)


def repo_check(c):
    repo = Path(c['repo'])
    if git(repo, 'remote', 'get-url', 'origin') != c['url']:
        raise RuntimeError('远程地址与登记不符，已停止。')
    if git(repo, 'symbolic-ref', '--short', 'HEAD') != c['branch']:
        raise RuntimeError('当前分支与登记不符，已停止。')
    if git(repo, 'status', '--porcelain'):
        raise RuntimeError('仓库有未提交修改，已保留。请当前智能体 检查，不自动提交已有现场。')
    git(repo, 'fetch', 'origin')
    head = git(repo, 'rev-parse', '--verify', 'HEAD', allow_fail=True)
    remote = git(repo, 'rev-parse', '--verify', 'refs/remotes/origin/' + c['branch'], allow_fail=True)
    if head and remote and head != remote:
        if git(repo, 'merge-base', head, remote) != head:
            raise RuntimeError('有未推送提交或分支分叉。请当前智能体 检查并恢复普通推送，禁止覆盖。')
        git(repo, 'merge', '--ff-only', remote)
    elif not head and remote:
        git(repo, 'merge', '--ff-only', remote)
    elif head and not remote:
        raise RuntimeError('远程分支不存在且本地已有提交，需人工检查。')
    return repo


def setup(url=None, root_path=None):
    if CONFIG.exists():
        print('已配置：', CONFIG, '；如需更改仓库，请当前智能体 检查后调整。')
        return
    print('请输入已建立的 GitHub skills 专用仓库。不会创建或改变仓库可见性。')
    url = url or input('GitHub 地址（HTTPS 或 git@github.com）：').strip()
    if not re.fullmatch(r'(https://github\.com/|git@github\.com:)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', url):
        raise RuntimeError('请使用不带令牌的标准 GitHub 仓库地址。')
    default = Path(DEFAULT_ROOT) if DEFAULT_ROOT else Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'skills'
    root = normalize_path(root_path or input('本机 skills 目录 [按回车使用 %s]：' % default).strip() or default).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError('目录不存在，请核实本机路径。')
    HOME.mkdir(parents=True, exist_ok=True)
    repo = HOME / 'repository'
    if repo.exists():
        raise RuntimeError('工作副本已存在，保留现场，请当前智能体 检查。')
    git(HOME, 'clone', '--', url, str(repo))
    branch = git(repo, 'symbolic-ref', '--short', 'HEAD')
    save(CONFIG, {'url':url, 'branch':branch, 'repo':str(repo), 'root':str(root), 'selected':read_selection(), 'baseline':{}, 'variant':DEFAULT_VARIANT, 'comparison':'lf'})
    print('配置完成。请用菜单 2 选择 skills。')


def choose():
    c = load()
    names = available(c, Path(c['repo']))
    for i, n in enumerate(names, 1):
        print('%3d %s %s' % (i, '[已选]' if n in c['selected'] else '[    ]', n))
    print('名单仅影响这台电脑；仓库中的其他 skills 保留。取消选择不会删除文件。')
    raw = input('输入要同步的全部编号（逗号分隔），回车保持，0 清空：').strip()
    if not raw:
        return
    indices = [] if raw == '0' else [int(x.strip()) for x in raw.split(',')]
    if any(i < 1 or i > len(names) for i in indices):
        raise RuntimeError('编号超出范围')
    c['selected'] = sorted({names[i-1] for i in indices})
    save(CONFIG, c)
    print('名单已保存：', ', '.join(c['selected']) or '空')


def plan(c, repo, direction):
    actions = []
    blocked = []
    for n in c['selected']:
        a, b = local_skill(c,n), shared_skill(c, repo, n)
        local, shared = support.snapshot(a,c), support.snapshot(b,c)
        baseline = support.baseline(c,n,a,b)
        if local == shared:
            continue
        if direction == 'upload':
            if local is None:
                blocked.append(n + '：本机不存在；不传播删除')
            elif shared is not None and (baseline is None or shared != baseline) and not support.accepted(c,n,a,b):
                blocked.append(n + '：共享版本变化或首次同名接入，需比较')
            else:
                actions.append((n, a, b, files(a)))
        else:
            if shared is None:
                blocked.append(n + '：仓库不存在；请先上传')
            elif local is not None and (baseline is None or local != baseline):
                blocked.append(n + '：存在本机改动或首次同名接入，需比较')
            else:
                actions.append((n, b, a, files(b)))
    if blocked:
        raise RuntimeError('整批操作已停止：\n' + '\n'.join(blocked)+'\n请使用「差异与冲突处理」或 CLI diff / resolve；无需手改基线。')
    return actions


def sync(direction, preview=False, confirm=None, selected=None, message=None):
    c = load()
    saved_selection=list(c['selected'])
    if selected is not None:
        if any(not SAFE_NAME.fullmatch(n) for n in selected):raise RuntimeError('无效 skill 名称')
        c['selected']=sorted(set(selected))
    def save_state():
        save(CONFIG,{**c,'selected':saved_selection})
    if not c['selected']:
        print('尚未选择 skills，请用菜单 2。')
        return
    import local_sources
    local_sources.check_targets(c,c['selected'])
    repo = repo_check(c)
    for n in c['selected']:
        support.register(c,n,local_skill(c,n),shared_skill(c,repo,n))
    save_state()
    support.check_dependencies(c,repo,direction)
    actions = plan(c, repo, direction)
    for _,source,_,_ in actions:support.validate_python(source)
    print('方向：', '本机 → GitHub' if direction == 'upload' else 'GitHub → 本机')
    changed_names={a[0] for a in actions}
    for n in c['selected']:
        if n not in changed_names:print(n+'：无变化，跳过')
    for n, source, target, snapshot in actions:
        print(n+'：'+('更新' if target.exists() else '新增'))
        old = files(target) or {}
        added = sorted(set(snapshot)-set(old))
        deleted = sorted(set(old)-set(snapshot))
        changed = sorted(k for k in snapshot.keys() & old.keys() if snapshot[k] != old[k])
        print('\n' + n)
        for label, items in [('新增',added),('修改',changed),('移除',deleted)]:
            for item in items:
                print(' ',label, item)
    if preview:
        print('预览完成，没有安装或上传。')
        return
    records=[]
    if actions:
        new=sum(not target.exists() for _,_,target,_ in actions)
        print('本次新增 %d 个、覆盖 %d 个；仅覆盖会备份旧版。每次执行另保存回执。' % (new,len(actions)-new))
        if not (confirm() if confirm else input('输入 yes 执行，其他输入取消：').strip().lower() == 'yes'):
            return
        if direction == 'upload':
            git(repo, 'var', 'GIT_AUTHOR_IDENT')
        # Recheck after the user reviewed the plan.
        repo_check(c)
        if plan(c, repo, direction) != actions:
            raise RuntimeError('预览后文件发生变化，请重新执行。')
        for n, source, target, snapshot in actions:
            if local_skill(c,n)!=(source if direction=='upload' else target):raise RuntimeError('链接目标在操作期间变化，请重新预览。')
            backup=replace_tree(source, target, snapshot)
            records.append({'skill':n,'target':str(target),'backup':backup,'kind':'replace' if backup else 'new','hashes':snapshot})
        if direction == 'upload':
            for n, _, _, _ in actions:
                git(repo, 'add', '--', shared_skill(c, repo, n).relative_to(repo).as_posix())
            if git(repo, 'diff', '--cached', '--name-only'):
                git(repo, 'commit', '-m', (message or '').strip() or 'Update selected personal skills')
            git(repo, 'push', 'origin', 'HEAD:refs/heads/'+c['branch'])
            sha = git(repo, 'rev-parse', 'HEAD')
            remote = git(repo, 'ls-remote', 'origin', 'refs/heads/'+c['branch'])
            if not remote or remote.split()[0] != sha:
                raise RuntimeError('远程 SHA 未能核对，未登记成功。')
    for n in c['selected']:
        support.register(c,n,local_skill(c,n),shared_skill(c,repo,n))
    c['last_sha'] = git(repo, 'rev-parse', '--verify', 'HEAD', allow_fail=True)
    c['last_run']={'direction':direction,'selected':list(c['selected']),'applied':[r['skill'] for r in records],'sha':c['last_sha']}
    receipt=HOME/'receipts'/(str(time.time_ns())+'.json')
    save(receipt,{**c['last_run'],'files':records})
    save_state()
    print('完成：文件已落地并核对，Python 脚本仅做语法检查；业务调用由目标智能体验证。')
    print('仓库 SHA：',c['last_sha'],'\n同步回执：',receipt)


def read_selection():
    if CONFIG.exists():return load()['selected']
    path=HOME/'selection.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


def set_selection(names):
    if not all(SAFE_NAME.fullmatch(n) for n in names):raise RuntimeError('名单含无效 skill 名称')
    names=sorted(set(names))
    if CONFIG.exists():
        c=load();c['selected']=names;save(CONFIG,c)
    save(HOME/'selection.json',names)


def auth_status(url=None):
    c=load() if CONFIG.exists() else None
    url=url or (c['url'] if c else None)
    if not url:raise RuntimeError('请指定仓库地址或先连接仓库。')
    if not re.fullmatch(r'(https://github\.com/|git@github\.com:)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?',url):raise RuntimeError('仅接受无凭据的标准 GitHub 地址')
    HOME.mkdir(parents=True,exist_ok=True)
    git(Path(c['repo']) if c else HOME,'ls-remote',url)
    print('已能读取此仓库。读取成功不代表已验证推送权限；首次上传将单独核验。')


def device_login():
    executable=os.environ.get('SKILL_SYNC_GIT') or shutil.which('git') or 'git'
    for helper in ['credential-manager','credential-manager-core']:
        p=subprocess.run([executable,helper,'github','login','--help'],capture_output=True,text=True,errors='replace',timeout=15)
        help_text=p.stdout+p.stderr
        if '--device' in help_text:
            print('请本人完成下方 GitHub 官方设备授权。程序不读取、展示或存储令牌。',flush=True)
            args=[executable,helper,'github','login','--device']
            if '--url' in help_text:args+=['--url','https://github.com']
            result=subprocess.run(args,timeout=300)
            if result.returncode:raise RuntimeError('设备授权未完成，请检查本机 Git Credential Manager。')
            return
    raise RuntimeError('未发现支持设备登录的 Git Credential Manager。请当前智能体安装/配置官方凭据管理器，或复用本机已有安全登录；不需要 gh，也不要提供令牌。')


def cli():
    import argparse
    import bootstrap
    parser=argparse.ArgumentParser(description='Skills 同步助手：可无头执行，默认仅预览')
    parser.add_argument('--profile')
    parser.add_argument('command',nargs='?',default='menu',choices=['menu','sync','connect','select','diff','resolve','auth','policy','link'])
    parser.add_argument('--direction',choices=['upload','download'],default='download')
    parser.add_argument('--skills',nargs='+');parser.add_argument('--all',action='store_true')
    parser.add_argument('--yes',action='store_true');parser.add_argument('--url')
    parser.add_argument('--skill');parser.add_argument('--take',choices=['local','remote','merge','export'],default='export')
    parser.add_argument('--merged-dir');parser.add_argument('--comparison',choices=['lf','bytes'])
    parser.add_argument('--device',action='store_true')
    parser.add_argument('--target');parser.add_argument('--revoke',action='store_true')
    args=parser.parse_args()
    profile=args.profile or bootstrap.registry().get('active')
    if profile:bootstrap.activate(profile)
    bootstrap.BASE.mkdir(parents=True,exist_ok=True)
    lock=bootstrap.BASE/'running.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    except FileExistsError:raise RuntimeError('已有同步操作或异常退出遗留的锁；确认后由智能体处理。')
    try:
        if args.command=='menu':return main()
        if args.command=='auth':
            if args.device:device_login()
            return auth_status(args.url)
        if args.command=='connect':
            if not args.url:parser.error('connect 需要 --url')
            return setup(args.url,DEFAULT_ROOT)
        if args.command=='select':
            if not args.skills:parser.error('select 需要 --skills')
            return set_selection(args.skills)
        c=load();repo=Path(c['repo'])
        if args.command=='link':
            import local_sources
            if not args.skill:parser.error('link 需要 --skill')
            if args.revoke:return local_sources.revoke(args.skill)
            if not args.target or not args.yes:parser.error('link 需要 --target 真实目录 --yes；授权只登记目录，不执行同步')
            print(local_sources.approve(args.skill,args.target));return
        if args.command=='policy':
            if not args.comparison:parser.error('policy 需要 --comparison')
            c['comparison']=args.comparison;save(CONFIG,c);return
        if args.command=='sync':
            if args.all and args.skills:parser.error('--all 与 --skills 不可同时使用')
            if args.all:
                repo_check(c);c['selected']=available(c,repo)
            elif args.skills:c['selected']=args.skills
            if args.all or args.skills:set_selection(c['selected'])
            return sync(args.direction,preview=not args.yes,confirm=lambda:True)
        if not args.skill:parser.error('diff/resolve 需要 --skill')
        if args.command=='diff':repo_check(c);print(support.diff(c,args.skill,repo));return
        if args.take!='export' and not args.yes:parser.error('采用版本或登记合并需要 --yes；可先 diff/export')
        return support.resolve(args.skill,args.take,args.merged_dir,confirm=lambda:True)
    finally:lock.unlink(missing_ok=True)



def main():
    while True:
        print('\n=== Skills 同步助手 ===\n1 连接仓库\n2 选择名单\n3 预览上传\n4 上传\n5 预览接收\n6 接收更新\n0 退出')
        choice=input('请选择：').strip()
        if choice=='0':return
        try:
            if choice=='1':setup()
            elif choice=='2':choose()
            elif choice in {'3','4','5','6'}:sync('upload' if choice in {'3','4'} else 'download',choice in {'3','5'})
        except (RuntimeError,OSError,ValueError,subprocess.TimeoutExpired) as error:print('未完成：',error)


if __name__=='__main__':
    sys.modules['skill_sync']=sys.modules[__name__]
    try:cli()
    except (KeyboardInterrupt,EOFError):print('已退出。')
    except (RuntimeError,OSError,ValueError,subprocess.TimeoutExpired) as error:
        print('未完成：',error,file=sys.stderr);sys.exit(1)
