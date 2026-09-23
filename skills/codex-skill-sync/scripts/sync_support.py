"""Diffs, explicit conflict decisions, line-ending policy and dependency checks."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

TEXT = {'.md','.txt','.py','.yaml','.yml','.json','.toml','.sh','.command','.bat','.ps1','.ini','.cfg','.js','.ts','.css','.html'}


def data(path, normalize=False):
    value=path.read_bytes()
    if normalize and path.suffix.lower() in TEXT and b'\0' not in value:
        try:value.decode('utf-8')
        except UnicodeDecodeError:return value
        return value.replace(b'\r\n',b'\n')
    return value


def snapshot(path, c):
    import skill_sync as e
    raw=e.files(path)
    if raw is None or c.get('comparison','bytes')!='lf':return raw
    return {rel:hashlib.sha256(data(path/rel,True)).hexdigest() for rel in raw}


def baseline(c,n,local,remote):
    import skill_sync as e
    if c.get('comparison','bytes')!='lf':return c['baseline'].get(n)
    if n in c.get('baseline_lf',{}):return c['baseline_lf'][n]
    old=c['baseline'].get(n)
    if old is not None:
        for path in [local,remote]:
            if e.files(path)==old:return snapshot(path,c)
    return None


def register(c,n,local,remote):
    import skill_sync as e
    if snapshot(local,c)==snapshot(remote,c) and e.files(local) is not None:
        c.setdefault('baseline',{})[n]=e.files(remote)
        c.setdefault('installed_hashes',{})[n]=e.files(local)
        if c.get('comparison','bytes')=='lf':c.setdefault('baseline_lf',{})[n]=snapshot(remote,c)
        else:c.setdefault('baseline_lf',{}).pop(n,None)
        c.setdefault('resolutions',{}).pop(n,None)
        return True
    return False


def accepted(c,n,local,remote):
    import skill_sync as e
    record=c.get('resolutions',{}).get(n)
    return bool(record and record['local']==e.files(local) and record['remote']==e.files(remote))


def diff(c,n,repo):
    import skill_sync as e
    if not e.SAFE_NAME.fullmatch(n):raise RuntimeError('无效 skill 名称')
    local=Path(c['root'])/n;remote=e.shared_skill(c,repo,n)
    a=e.files(local) or {};b=e.files(remote) or {};lines=[]
    for rel in sorted(a.keys()|b.keys()):
        if a.get(rel)==b.get(rel):continue
        lines.append('\n文件：'+rel+'\n')
        left=data(local/rel) if rel in a else b''
        right=data(remote/rel) if rel in b else b''
        try:
            if b'\0' in left+right:raise UnicodeError()
            l=left.decode('utf-8').splitlines(keepends=True);r=right.decode('utf-8').splitlines(keepends=True)
            if l==r and left!=right:lines.append('仅字节/行尾不同。\n')
            else:
                out=list(difflib.unified_diff(l,r,fromfile='本机/'+rel,tofile='GitHub/'+rel))
                lines.extend(out[:1200])
                if len(out)>1200:lines.append('\n[此文件差异已截断，请检查冲突副本]\n')
        except UnicodeError:lines.append('二进制文件或非 UTF-8 文本；请比较保存的副本。\n')
    return ''.join(lines) or '文件完全一致。\n'


def required(root):
    result=set();manifest=root/'sync-dependencies.json'
    if manifest.exists():
        values=json.loads(manifest.read_text(encoding='utf-8')).get('skills',[])
        if not isinstance(values,list) or not all(isinstance(v,str) for v in values):raise RuntimeError('依赖声明格式无效：'+str(manifest))
        result.update(values)
    text=(root/'SKILL.md').read_text(encoding='utf-8')
    result.update(re.findall(r'Call\s+the\s+Skill\s+tool\s+with\s+["\x27`]([a-z0-9_-]+)["\x27`]',text,re.I))
    return result


def check_dependencies(c,repo,direction):
    import skill_sync as e
    seen=set();missing=[]
    def source(name):
        return Path(c['root'])/name if direction=='upload' else e.shared_skill(c,repo,name)
    def destination(name):
        return e.shared_skill(c,repo,name) if direction=='upload' else Path(c['root'])/name
    def walk(n,path):
        if n in seen:return
        seen.add(n)
        if not (path/'SKILL.md').is_file():return
        for dep in required(path):
            if not e.SAFE_NAME.fullmatch(dep):raise RuntimeError('无效依赖名称：'+dep)
            if dep in c['selected'] and (source(dep)/'SKILL.md').is_file():target=source(dep)
            elif (destination(dep)/'SKILL.md').is_file():target=destination(dep)
            else:
                missing.append(n+' → '+dep);continue
            walk(dep,target)
    for n in c['selected']:walk(n,source(n))
    if missing:raise RuntimeError('缺少依赖，请同时勾选所需 skill 或先安装它：\n'+'\n'.join(missing))


def validate_python(root):
    import skill_sync as e
    for rel in e.files(root) or {}:
        if rel.endswith('.py'):
            try:compile((root/rel).read_bytes(),rel,'exec')
            except SyntaxError as error:raise RuntimeError('Python 语法检查失败：'+rel+'（当前解释器；如目标需更高版本请切换运行时）') from error


def resolve(n,choice,merged_dir=None,confirm=None):
    import skill_sync as e
    c=e.load();repo=e.repo_check(c)
    if not e.SAFE_NAME.fullmatch(n):raise RuntimeError('无效 skill 名称')
    local=Path(c['root'])/n;remote=e.shared_skill(c,repo,n)
    before_l=e.files(local);before_r=e.files(remote)
    if before_l is None or before_r is None:raise RuntimeError('冲突处理要求双方都存在；新增请使用普通同步。')
    print(diff(c,n,repo))
    if choice not in {'export','local','remote','merge'}:raise RuntimeError('未知冲突处理方式')
    merged=Path(merged_dir).expanduser().resolve() if merged_dir else None
    if choice=='remote':
        validate_python(remote)
        check_dependencies({**c,'selected':[n]},repo,'download')
    if choice=='merge':
        if not merged:raise RuntimeError('请指定人工/智能体合并好的完整 skill 目录。')
        wanted=e.files(merged)
        if wanted is None:raise RuntimeError('合并目录不存在：'+str(merged))
        validate_python(merged)
        for rel in wanted:
            if Path(rel).suffix in TEXT and re.search(rb'(?m)^(<<<<<<<|>>>>>>>) ',(merged/rel).read_bytes()):raise RuntimeError('合并目录仍有冲突标记：'+rel)
    else:wanted=before_r if choice=='remote' else before_l
    if choice!='export' and not (confirm() if confirm else input('输入 yes 确认此冲突处理：').strip()=='yes'):return
    e.repo_check(c)
    if e.files(local)!=before_l or e.files(remote)!=before_r:raise RuntimeError('比较后双方发生变化，请重新处理。')
    folder=e.HOME/'conflicts'/(str(time.time_ns())+'-'+n)
    folder.mkdir(parents=True)
    shutil.copytree(local,folder/'local');shutil.copytree(remote,folder/'github')
    (folder/'diff.txt').write_text(diff(c,n,repo),encoding='utf-8')
    print('双方冲突副本：',folder)
    if choice=='export':return str(folder)
    if choice in {'remote','merge'}:
        e.replace_tree(remote if choice=='remote' else merged,local,wanted)
    if choice=='remote':register(c,n,local,remote)
    else:
        # Bind an explicit overwrite decision to both exact versions. Baseline is
        # not fabricated; it is only recorded after verified upload/equivalence.
        c.setdefault('resolutions',{})[n]={'local':e.files(local),'remote':before_r,'copies':str(folder)}
        if snapshot(local,c)==snapshot(remote,c):register(c,n,local,remote)
    e.save(e.CONFIG,c)
    print('已采用 GitHub 版并登记基线。' if choice=='remote' else '已登记明确的本机/合并决策；下一次上传将使用此版本，远程若再变化会重新停止。')
    return str(folder)
