"""Read-only catalog and filters shared by the GUI and tests."""
from pathlib import Path
import re
import skill_sync as engine


def description(root):
    try:
        text=(root/'SKILL.md').read_text(encoding='utf-8-sig')
    except (OSError,UnicodeError):return '缺少功能介绍'
    if not text.startswith('---'):return '缺少功能介绍'
    front=text.split('---',2)
    if len(front)<3:return '缺少功能介绍'
    lines=front[1].splitlines()
    for i,line in enumerate(lines):
        match=re.match(r'^description:\s*(.*)$',line)
        if not match:continue
        value=match.group(1).strip()
        continuation=[]
        for other in lines[i+1:]:
            if other.strip() and not other[0].isspace():break
            continuation.append(other.strip())
        if value in {'>','|','>-','|-','>+','|+'}:value=' '.join(continuation)
        elif continuation:value+=' '+' '.join(continuation)
        return value.strip('\"\x27') or '缺少功能介绍'
    return '缺少功能介绍'


def entry(c,repo,name):
    local=Path(c['root'])/name;remote=engine.shared_skill(c,repo,name)
    has_local=local.exists();has_remote=remote.exists()
    origin='两边都有' if has_local and has_remote else ('仅本机有' if has_local else '仅 GitHub 有')
    result={'name':name,'description':description(local if has_local else remote),'origin':origin}
    try:
        a=engine.support.snapshot(local,c);b=engine.support.snapshot(remote,c)
        if not (repo/'.git').exists():status='未连接 / 未核验'
        elif a is None:status='GitHub 有更新'
        elif b is None:status='尚未上传'
        elif a==b:status='两边一致'
        else:
            base=engine.support.baseline({**c,'baseline':c.get('baseline',{})},name,local,remote)
            if engine.support.accepted(c,name,local,remote) or (base is not None and b==base):status='本机有更新'
            elif base is not None and a==base:status='GitHub 有更新'
            else:status='有冲突 / 需比较'
    except (OSError,RuntimeError,ValueError) as error:
        status='无法检查';result['error']=str(error)
    result['status']=status
    return result


def matches(row,query='',mode='名称',status='全部',selection='全部',origin='全部',selected=False):
    value=row['name'] if mode=='名称' else row['description']
    return (query.strip().casefold() in value.casefold()
            and (status=='全部' or row['status']==status)
            and (origin=='全部' or row['origin']==origin)
            and (selection=='全部' or selected==(selection=='已勾选')))


def scope_names(selected,visible,scope):
    return sorted(set(selected) if scope=='all' else set(selected)&set(visible))
