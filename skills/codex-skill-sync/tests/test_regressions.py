import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import skill_sync as e
import sync_support as support
import runtime_support as rt
import bootstrap as b
import catalog


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name).resolve()
        self.old=(e.HOME,e.CONFIG,b.BASE,b.REGISTRY)
        e.HOME=self.base/'state';e.CONFIG=e.HOME/'config.json';e.HOME.mkdir()
        b.BASE=e.HOME;b.REGISTRY=b.BASE/'profiles.json'
        self.root=self.base/'local';self.root.mkdir()
        self.remote=self.base/'remote.git';self.remote.mkdir();e.git(self.remote,'init','--bare')
        self.repo=self.base/'repo';e.git(self.base,'clone',str(self.remote),str(self.repo))
        e.git(self.repo,'config','user.name','Sync Test');e.git(self.repo,'config','user.email','test@example.invalid')
        self.c={'url':str(self.remote),'repo':str(self.repo),'root':str(self.root),'branch':e.git(self.repo,'symbolic-ref','--short','HEAD'),'selected':['demo'],'baseline':{},'comparison':'lf'}
        e.save(e.CONFIG,self.c)
    def tearDown(self):
        e.HOME,e.CONFIG,b.BASE,b.REGISTRY=self.old;self.tmp.cleanup()
    def skill(self,root,name='demo',text=b'# Skill\n'):
        p=root/name;p.mkdir(parents=True,exist_ok=True);(p/'SKILL.md').write_bytes(text);return p
    def publish(self):
        e.git(self.repo,'add','.');e.git(self.repo,'commit','-m','fixture');e.git(self.repo,'push','origin',self.c['branch'])
    def run_sync(self,direction,preview=False):
        with contextlib.redirect_stdout(io.StringIO()):e.sync(direction,preview,confirm=lambda:True)

    def test_scoped_sync_keeps_hidden_selection_and_commit_message(self):
        self.skill(self.root);self.skill(self.root,'hidden')
        self.c['selected']=['demo','hidden'];e.save(e.CONFIG,self.c)
        with contextlib.redirect_stdout(io.StringIO()):e.sync('upload',False,lambda:True,selected=['demo'],message='更新说明：中文')
        self.assertEqual(e.load()['selected'],['demo','hidden'])
        self.assertFalse((self.repo/'skills/hidden').exists())
        self.assertEqual(e.load()['last_run']['selected'],['demo'])
        self.assertEqual(e.git(self.repo,'log','-1','--format=%B'),'更新说明：中文')
        (self.root/'demo/SKILL.md').write_text('changed')
        self.assertEqual(catalog.entry(e.load(),self.repo,'demo')['status'],'本机有更新')
        with contextlib.redirect_stdout(io.StringIO()):e.sync('upload',False,lambda:True,selected=['demo'])
        self.assertEqual(catalog.entry(e.load(),self.repo,'demo')['status'],'两边一致')
        self.assertEqual(e.load()['selected'],['demo','hidden'])

    def test_scoped_preview_and_cancel_preserve_selection(self):
        self.skill(self.root);self.c['selected']=['demo','hidden'];e.save(e.CONFIG,self.c)
        for preview in [True,False]:
            with contextlib.redirect_stdout(io.StringIO()):e.sync('upload',preview,lambda:False,selected=['demo'])
            self.assertEqual(e.load()['selected'],['demo','hidden'])
            self.assertFalse((self.repo/'skills/demo').exists())

    def test_catalog_search_filters_and_status(self):
        self.skill(self.root,text='---\nname: demo\ndescription: >-\n  生成周报\n  支持中文\n---\n'.encode())
        row=catalog.entry(self.c,self.repo,'demo')
        self.assertEqual(row['description'],'生成周报 支持中文')
        self.assertTrue(catalog.matches(row,'周报','功能',status='尚未上传',origin='仅本机有'))
        self.assertFalse(catalog.matches(row,'周报','名称'))
        self.assertTrue(catalog.matches(row,'DEMO','名称',selection='已勾选',selected=True))
        self.assertFalse(catalog.matches(row,selection='未勾选',selected=True))
        self.assertEqual(catalog.scope_names(['demo','hidden'],['demo'],'visible'),['demo'])
        self.assertEqual(catalog.scope_names(['demo','hidden'],['demo'],'all'),['demo','hidden'])
        self.skill(self.repo/'skills',text=b'different')
        self.assertEqual(catalog.entry(self.c,self.repo,'demo')['status'],'有冲突 / 需比较')

    def test_lf_identical_registers_preview_without_rewrite(self):
        local=self.skill(self.root,text=b'# Skill\r\nline\r\n');self.skill(self.repo/'skills',text=b'# Skill\nline\n');self.publish()
        self.run_sync('download',True)
        self.assertIn('demo',e.load()['baseline_lf']);self.assertEqual((local/'SKILL.md').read_bytes(),b'# Skill\r\nline\r\n')
        self.assertEqual(e.plan(e.load(),self.repo,'upload'),[])
    def test_local_conflict_adoption_then_upload(self):
        self.skill(self.root,text=b'local\n');self.skill(self.repo/'skills',text=b'remote\n');self.publish()
        with self.assertRaises(RuntimeError):e.plan(e.load(),self.repo,'upload')
        with contextlib.redirect_stdout(io.StringIO()):folder=support.resolve('demo','local',confirm=lambda:True)
        self.assertEqual((Path(folder)/'github/SKILL.md').read_bytes(),b'remote\n')
        self.assertNotIn('demo',e.load()['baseline'])
        self.run_sync('upload');self.assertEqual((self.repo/'skills/demo/SKILL.md').read_bytes(),b'local\n')
        self.assertEqual(e.plan(e.load(),self.repo,'upload'),[])
    def test_remote_conflict_adoption_backup_and_baseline(self):
        self.skill(self.root,text=b'local\n');self.skill(self.repo/'skills',text=b'remote\n');self.publish()
        with contextlib.redirect_stdout(io.StringIO()):folder=support.resolve('demo','remote',confirm=lambda:True)
        self.assertEqual((Path(folder)/'local/SKILL.md').read_bytes(),b'local\n')
        self.assertEqual((self.root/'demo/SKILL.md').read_bytes(),b'remote\n')
        self.assertEqual(e.plan(e.load(),self.repo,'download'),[])
    def test_merge_accepted_and_stale_decision_rejected(self):
        self.skill(self.root,text=b'local\n');self.skill(self.repo/'skills',text=b'remote\n');self.publish()
        merged=self.skill(self.base/'merge',text=b'merged\n')
        with contextlib.redirect_stdout(io.StringIO()):support.resolve('demo','merge',merged,lambda:True)
        self.assertEqual(len(e.plan(e.load(),self.repo,'upload')),1)
        (self.repo/'skills/demo/SKILL.md').write_bytes(b'new remote\n')
        with self.assertRaises(RuntimeError):e.plan(e.load(),self.repo,'upload')
    def test_dependency_must_be_selected_for_download(self):
        self.skill(self.repo/'skills',text=b'Call the Skill tool with "other".\n');self.skill(self.repo/'skills','other')
        with self.assertRaises(RuntimeError):support.check_dependencies(self.c,self.repo,'download')
        self.c['selected'].append('other');support.check_dependencies(self.c,self.repo,'download')
    def test_selected_preserved_receipt_for_new_install(self):
        self.skill(self.repo/'skills');self.publish();self.run_sync('download')
        c=e.load();self.assertEqual(c['selected'],['demo']);self.assertEqual(c['last_run']['applied'],['demo'])
        receipt=json.loads(next((e.HOME/'receipts').glob('*.json')).read_text())
        self.assertEqual(receipt['files'][0]['kind'],'new');self.assertIsNone(receipt['files'][0]['backup'])
    def test_offline_selection_survives_connect(self):
        e.CONFIG.unlink();e.set_selection(['demo'])
        actual_git=e.git
        def fake_git(repo,*args,**kwargs):
            if args[0]=='clone':return actual_git(repo,'clone',str(self.remote),args[-1])
            return actual_git(repo,*args,**kwargs)
        with patch.object(e,'git',side_effect=fake_git):e.setup('https://github.com/test/test.git',str(self.root))
        self.assertEqual(e.load()['selected'],['demo'])
    def test_cli_uses_same_selection_and_no_tk(self):
        self.skill(self.repo/'skills');self.publish()
        meta={'name':'test','skills_dir':str(self.root),'state_dir':str(e.HOME),'variant':'shared'}
        e.save(b.REGISTRY,{'active':'test','profiles':{'test':meta}})
        env={**os.environ,'SKILL_SYNC_HOME':str(b.BASE),'PYTHONDONTWRITEBYTECODE':'1'}
        p=subprocess.run([sys.executable,str(Path(e.__file__)),'--profile','test','sync','--direction','download','--yes'],env=env,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertTrue((self.root/'demo/SKILL.md').exists())
    def test_explicit_git_executable_used(self):
        real=shutil.which('git')
        with patch.dict(os.environ,{'SKILL_SYNC_GIT':real}):self.assertIsNotNone(e.git(self.repo,'status','--porcelain'))
    def test_syntax_check_no_pycache(self):
        p=self.skill(self.root);(p/'test.py').write_text('x = 1\n');support.validate_python(p)
        self.assertFalse((p/'__pycache__').exists())
        (p/'test.py').write_text('x =\n')
        with self.assertRaises(RuntimeError):support.validate_python(p)


class RuntimeTests(unittest.TestCase):
    def test_msys_windows_paths(self):
        self.assertEqual(str(rt.normalize_path('/c/Users/中文 目录',platform='nt')).replace('\\','/'),'C:/Users/中文 目录')
        self.assertEqual(str(rt.normalize_path('/Users/mac',platform='posix')),'/Users/mac')
    def test_discover_existing_tk_without_python_in_path(self):
        def probe(n):return {'python_exe':n,'python_version':[3,12,1],'gui':n=='codex'}
        with patch.object(rt,'python_candidates',return_value=iter(['workbuddy','codex'])),patch.object(rt,'_executable',side_effect=lambda x:x),patch.object(rt,'probe_python',side_effect=probe),patch.object(rt,'git_candidates',return_value=iter(['portablegit'])),patch.object(rt,'probe_git',side_effect=lambda x:x):
            r=rt.discover_runtime();self.assertEqual(r['python_exe'],'codex');self.assertEqual(r['git_exe'],'portablegit')
    def test_windows_launcher_absolute_paths(self):
        meta={'skills_dir':'C:/用户 空格/skills','shortcut_dir':'C:/用户 空格/Desktop','runtime':{'gui':True,'python_exe':'C:/Runtime Space/python.exe','git_exe':'C:/Portable Git/cmd/git.exe'}}
        _,text=b.launcher_content('windows-test',meta,windows=True)
        self.assertIn('"%PYTHON_EXE%"',text);self.assertNotIn('py -3',text);self.assertIn('SKILL_SYNC_GIT',text);self.assertIn('chcp 65001',text)
    @unittest.skipUnless(os.name=='nt','Needs a real Windows command processor')
    def test_windows_batch_without_python_or_py_in_path(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);target=base/'中文 skills';target.mkdir();short=base/'中文 shortcut';short.mkdir()
            state=base/'state';state.mkdir()
            old_base,old_registry=b.BASE,b.REGISTRY
            try:
                b.BASE=state;b.REGISTRY=state/'profiles.json'
                source=Path(__file__).resolve().parents[1]
                shutil.copytree(source,target/'codex-skill-sync',ignore=shutil.ignore_patterns('__pycache__'))
                git_exe=shutil.which('git')
                meta={'name':'test','skills_dir':str(target),'shortcut_dir':str(short),'state_dir':str(state/'profiles/test'),'variant':'shared','runtime':{'gui':False,'python_exe':sys.executable,'git_exe':git_exe}}
                launcher,text=b.launcher_content('test',meta,windows=True)
                launcher.write_text(text,encoding='utf-8')
                e.save(b.REGISTRY,{'active':'test','profiles':{'test':meta}})
                env=dict(os.environ);env['PATH']='';env.pop('PYTHONPATH',None)
                cmd=str(Path(os.environ['SystemRoot'])/'System32/cmd.exe')
                p=subprocess.run([cmd,'/d','/c',str(launcher)],input='0\n',capture_output=True,encoding='utf-8',errors='replace',env=env,timeout=30)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                self.assertIn('Skills',p.stdout)
            finally:b.BASE,b.REGISTRY=old_base,old_registry
    def test_errors_do_not_overclaim_404(self):
        self.assertIn('无法区分',e.git_error('404 Repository not found'))
        self.assertIn('网络',e.git_error('Could not resolve host'))


if __name__=='__main__':unittest.main()
