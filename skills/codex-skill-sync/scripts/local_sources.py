"""Local skill entry resolution. Only explicitly registered root links are followed."""
import os
from pathlib import Path


def is_link(path):
    if path.is_symlink():return True
    check=getattr(os.path,'isjunction',None)
    if check and check(path):return True
    if os.name=='nt':
        import ctypes
        attrs=ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return attrs!=-1 and attrs!=0xffffffff and bool(attrs & 0x400)
    return False


def inspect(c,name):
    import skill_sync as e
    if not e.SAFE_NAME.fullmatch(name):raise RuntimeError('无效 skill 名称')
    entry=Path(c['root'])/name
    linked=any(is_link(p) for p in [entry,*entry.parents])
    result={'entry':str(entry),'linked':linked,'target':str(entry.absolute()),'problem':None}
    try:
        target=entry.resolve(strict=linked)
        result['target']=str(target)
        if linked and not (target.is_dir() and (target/'SKILL.md').is_file()):
            result['problem']='链接目标不是完整 skill；请修复入口指向。'
    except (OSError,RuntimeError) as error:
        result['problem']='链接已失效或循环；请修复入口指向后刷新。'
    result['approved']=not linked or (not result['problem'] and c.get('link_targets',{}).get(name)==result['target'])
    return result


def resolve(c,name,require_approval=True):
    info=inspect(c,name)
    if info['problem']:raise RuntimeError(name+'：'+info['problem'])
    if require_approval and not info['approved']:
        raise RuntimeError(name+'：链接目录尚未确认或目标已变化，请先“管理此目录”：'+info['target'])
    return Path(info['target'])


def approve(name,expected):
    import skill_sync as e
    c=e.load();info=inspect(c,name)
    if not info['linked'] or info['problem'] or info['target']!=str(expected):
        raise RuntimeError('链接目标已变化或失效，请刷新后重新确认。')
    e.files(Path(info['target']))  # Nested links/private files remain disallowed.
    c.setdefault('link_targets',{})[name]=info['target'];e.save(e.CONFIG,c)
    return info['target']


def revoke(name):
    import skill_sync as e
    c=e.load();c.setdefault('link_targets',{}).pop(name,None);e.save(e.CONFIG,c)


def inventory(c):
    import skill_sync as e
    root=Path(c['root']);groups={};result={}
    if not root.is_dir():return result
    for p in root.iterdir():
        if not e.SAFE_NAME.fullmatch(p.name):continue
        if not is_link(p) and not (p.is_dir() and (p/'SKILL.md').is_file()):continue
        info=inspect(c,p.name)
        key=info['target'] if not info['problem'] else str(p)
        groups.setdefault(key,[]).append((p.name,info))
    for target,entries in groups.items():
        entries.sort(key=lambda pair:(pair[1]['linked'],pair[0]!=Path(target).name,pair[0]))
        name,info=entries[0];info['aliases']=[n for n,_ in entries[1:]];result[name]=info
    return result


def check_targets(c,names):
    paths=[]
    for name in names:
        path=resolve(c,name)
        for other,previous in paths:
            if path==previous or path in previous.parents or previous in path.parents:
                raise RuntimeError('同步目标重复或重叠：'+other+' / '+name+'；请仅选择一个入口。')
        paths.append((name,path))
