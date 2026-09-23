#!/usr/bin/env python3
"""Checkbox UI with isolated target-agent environments."""
import argparse
import os
from pathlib import Path
import queue
import sys
sys.dont_write_bytecode = True
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import skill_sync as engine
import bootstrap
import catalog


class App:
    def __init__(self, root, profile=None):
        self.root=root;self.events=queue.Queue();self.busy=False;self.vars={};self.catalog=[];self.visible=[]
        self.profile=profile or bootstrap.registry().get('active')
        if self.profile:bootstrap.activate(self.profile)
        root.title('Skills 同步助手');root.geometry('1080x850');root.protocol('WM_DELETE_WINDOW',self.close)
        top=ttk.Frame(root,padding=16);top.pack(fill='x')
        ttk.Label(top,text='勾选哪些，就同步哪些',font=('',20,'bold')).pack(anchor='w')
        ttk.Label(top,text='先选择目标智能体。目录、勾选名单、版本记录和备份分别保存。').pack(anchor='w',pady=6)
        bar=ttk.Frame(top);bar.pack(fill='x',pady=5)
        ttk.Label(bar,text='当前环境  ').pack(side='left')
        self.env=tk.StringVar()
        self.selector=ttk.Combobox(bar,textvariable=self.env,state='readonly',width=40)
        self.selector.pack(side='left');self.selector.bind('<<ComboboxSelected>>',self.switch)
        self.buttons=[]
        b=ttk.Button(bar,text='添加智能体 / 首次初始化',command=self.onboard);b.pack(side='left',padx=8);self.buttons.append(b)
        self.info=ttk.Label(top,text='');self.info.pack(anchor='w',pady=4)
        toolbar=ttk.Frame(top);toolbar.pack(fill='x',pady=8)
        for label,command in [('连接 GitHub',self.configure),('刷新清单',self.refresh_remote),('差异与冲突处理',self.conflicts),('认证检查',self.auth_check),('全选当前结果',lambda:self.select(True)),('取消当前结果',lambda:self.select(False)),('清空全部勾选',lambda:self.select(False,True))]:
            b=ttk.Button(toolbar,text=label,command=command);b.pack(side='left',padx=3);self.buttons.append(b)
        search=ttk.Frame(top);search.pack(fill='x',pady=4)
        self.query=tk.StringVar();self.search_mode=tk.StringVar(value='名称')
        self.status_filter=tk.StringVar(value='全部');self.selection_filter=tk.StringVar(value='全部');self.origin_filter=tk.StringVar(value='全部')
        ttk.Label(search,text='搜索 ').pack(side='left')
        ttk.Entry(search,textvariable=self.query,width=32).pack(side='left',padx=4)
        self.filters=[]
        def combo(parent,var,values,width):
            box=ttk.Combobox(parent,textvariable=var,values=values,state='readonly',width=width)
            box.pack(side='left',padx=4);self.filters.append(box)
        combo(search,self.search_mode,['名称','功能'],8)
        filters=ttk.Frame(top);filters.pack(fill='x',pady=4)
        for label,var,values,width in [
            ('同步状态',self.status_filter,['全部','尚未上传','本机有更新','GitHub 有更新','两边一致','有冲突 / 需比较','未连接 / 未核验','无法检查'],19),
            ('勾选',self.selection_filter,['全部','已勾选','未勾选'],9),
            ('来源',self.origin_filter,['全部','仅本机有','仅 GitHub 有','两边都有'],13)]:
            ttk.Label(filters,text=label).pack(side='left');combo(filters,var,values,width)
        self.counts=ttk.Label(top,text='');self.counts.pack(anchor='w',pady=4)
        ttk.Label(top,text='状态依据上次获取的仓库内容；点击“刷新清单”检查 GitHub 最新变化。').pack(anchor='w')
        for var in [self.query,self.search_mode,self.status_filter,self.selection_filter,self.origin_filter]:
            var.trace_add('write',lambda *_:self.render())
        area=ttk.Frame(root);area.pack(fill='both',expand=True,padx=16)
        canvas=tk.Canvas(area,highlightthickness=0)
        scroll=ttk.Scrollbar(area,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        self.rows=ttk.Frame(canvas);window=canvas.create_window((0,0),window=self.rows,anchor='nw')
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        self.rows.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        actions=ttk.Frame(root,padding=12);actions.pack(fill='x')
        for label,direction,preview in [('预览上传','upload',True),('上传／提交更新','upload',False),('预览接收','download',True),('从 GitHub 更新','download',False)]:
            b=ttk.Button(actions,text=label,command=lambda d=direction,p=preview:self.run_sync(d,p));b.pack(side='left',padx=4);self.buttons.append(b)
        self.log=tk.Text(root,height=12,wrap='word',state='disabled');self.log.pack(fill='x',padx=16,pady=(0,12))
        self.refresh();root.after(100,self.poll)
        if not self.profile:self.append('首次使用：请让当前智能体确认目录并完成初始化，或点击“添加智能体”。\n')

    def write(self,text):self.events.put(('log',text))
    def flush(self):pass
    def append(self,text):
        self.log.configure(state='normal');self.log.insert('end',text);self.log.see('end');self.log.configure(state='disabled')
    def poll(self):
        while not self.events.empty():
            kind,data=self.events.get()
            if kind=='log':self.append(data)
            elif kind=='confirm':
                event,answer,prompt=data
                answer.append(messagebox.askyesno('确认操作',prompt))
                event.set()
            elif kind=='done':
                self.busy=False
                for b in self.buttons:b.configure(state='normal')
                self.selector.configure(state='readonly')
                self.refresh()
        self.root.after(100,self.poll)
    def confirm(self,prompt='确认仅处理当前环境中勾选的 skills？变更已列在日志中，覆盖旧文件会保留备份。'):
        event=threading.Event();answer=[];self.events.put(('confirm',(event,answer,prompt)));event.wait();return answer[0]
    def work(self,fn):
        if self.busy:return
        self.busy=True;self.selector.configure(state='disabled')
        for b in self.buttons:b.configure(state='disabled')
        for b in self.rows.winfo_children():
            if isinstance(b,ttk.Checkbutton):b.configure(state='disabled')
        def task():
            old=sys.stdout;sys.stdout=self
            # One app-wide lock prevents concurrent self-updates across profiles.
            lock=bootstrap.BASE/'running.lock';owned=False
            try:
                bootstrap.BASE.mkdir(parents=True,exist_ok=True)
                fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd);owned=True
                fn()
            except FileExistsError:print('未完成：已有同步操作运行，或上次异常退出留有锁。请当前智能体检查。')
            except Exception as e:print('未完成：',e)
            finally:
                if owned:lock.unlink(missing_ok=True)
                sys.stdout=old;self.events.put(('done',None))
        threading.Thread(target=task,daemon=True).start()
    def state(self):
        if engine.CONFIG.exists():return engine.load()
        selected=engine.read_selection()
        default=engine.DEFAULT_ROOT or str(Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'skills')
        return {'root':default,'repo':str(engine.HOME/'repository'),'selected':selected,'variant':engine.DEFAULT_VARIANT}
    def persist(self):
        if self.busy or not self.profile:return
        chosen=[n for n,v in self.vars.items() if v.get()]
        engine.set_selection(chosen)
        self.render()
    def select(self,value,all_items=False):
        if self.busy:return
        for n in (self.vars if all_items else self.visible):self.vars[n].set(value)
        self.persist()
    def switch(self,event=None):
        if self.busy:return
        chosen=self.ids[self.selector.current()]
        bootstrap.activate(chosen);self.profile=chosen;self.refresh()
    def refresh_remote(self):
        if not engine.CONFIG.exists():self.refresh();return
        self.work(lambda:engine.repo_check(engine.load()))
    def refresh(self):
        if self.busy:return
        r=bootstrap.registry();self.ids=list(r['profiles'])
        self.selector.configure(values=[r['profiles'][p]['name']+'  ['+p+']' for p in self.ids])
        if self.profile in self.ids:self.selector.current(self.ids.index(self.profile))
        for b in self.rows.winfo_children():b.destroy()
        self.vars={}
        try:
            c=self.state()
            self.info.configure(text='Skills：'+c['root']+'  |  版本：'+c.get('variant','shared')+('' if engine.CONFIG.exists() else '  |  GitHub 未连接')+'\n状态根：'+str(bootstrap.BASE)+'  |  当前状态：'+str(engine.HOME))
            local=Path(c['root']);repo=Path(c['repo'])
            names=engine.available(c,repo)
            self.catalog=[catalog.entry(c,repo,n) for n in names]
            # Retain selections even when a missing skill is not currently listed.
            for n in sorted(set(names)|set(c['selected'])):
                self.vars[n]=tk.BooleanVar(value=n in c['selected'])
            self.render()
        except Exception as e:self.append(str(e)+'\n')
    def render(self):
        if self.busy:return
        for widget in self.rows.winfo_children():widget.destroy()
        self.visible=[]
        for row in self.catalog:
            n=row['name']
            if not catalog.matches(row,self.query.get(),self.search_mode.get(),self.status_filter.get(),self.selection_filter.get(),self.origin_filter.get(),self.vars[n].get()):continue
            self.visible.append(n)
            ttk.Checkbutton(self.rows,text=n+'   ·   '+row['status']+'   ·   '+row['origin'],variable=self.vars[n],command=self.persist).pack(anchor='w',pady=(7,0))
            ttk.Label(self.rows,text=row['description'],wraplength=930).pack(anchor='w',padx=24,pady=(0,4))
            if row.get('error'):ttk.Label(self.rows,text=row['error'],wraplength=930).pack(anchor='w',padx=24)
        chosen={n for n,v in self.vars.items() if v.get()}
        shown=chosen&set(self.visible)
        self.counts.configure(text=f'显示 {len(self.visible)} / {len(self.catalog)} 项；已勾选 {len(chosen)} 项，其中 {len(chosen-shown)} 项隐藏')
    def run_sync(self,direction,preview):
        if self.busy:return
        if not engine.CONFIG.exists():messagebox.showinfo('尚未连接','请先初始化环境并连接 GitHub。');return
        self.persist()
        selected=[n for n,v in self.vars.items() if v.get()]
        visible=list(self.visible)
        shown=catalog.scope_names(selected,visible,'visible')
        dialog=tk.Toplevel(self.root);dialog.title('选择本次操作范围');dialog.geometry('650x340');dialog.grab_set()
        ttk.Label(dialog,text='每次操作都重新选择范围，取消则不执行。').pack(anchor='w',padx=18,pady=14)
        scope=tk.StringVar(value='')
        ttk.Radiobutton(dialog,text=f'全部勾选项：{len(selected)} 项（含隐藏的 {len(selected)-len(shown)} 项）',variable=scope,value='all').pack(anchor='w',padx=18,pady=6)
        ttk.Radiobutton(dialog,text=f'当前可见且已勾选的项：{len(shown)} 项',variable=scope,value='visible').pack(anchor='w',padx=18,pady=6)
        message=tk.StringVar()
        if direction=='upload':
            ttk.Label(dialog,text='更新说明（可选，留空自动生成）').pack(anchor='w',padx=18,pady=(14,4))
            ttk.Entry(dialog,textvariable=message,width=70).pack(fill='x',padx=18)
        def proceed():
            if not scope.get():messagebox.showinfo('请选择范围','请选择本次操作范围。',parent=dialog);return
            names=catalog.scope_names(selected,visible,scope.get())
            if not names:messagebox.showinfo('没有选中项','该范围内没有已勾选的 skill。',parent=dialog);return
            note=message.get();dialog.destroy()
            prompt=f'本次处理 {len(names)} 项：\n'+', '.join(names)+'\n变更见日志；覆盖旧版会备份。'
            self.work(lambda:engine.sync(direction,preview,lambda:self.confirm(prompt),selected=names,message=note))
        buttons=ttk.Frame(dialog);buttons.pack(pady=18)
        ttk.Button(buttons,text='继续预览' if preview else '查看变更并继续',command=proceed).pack(side='left',padx=8)
        ttk.Button(buttons,text='取消',command=dialog.destroy).pack(side='left',padx=8)
    def onboard(self):
        if self.busy:return
        dialog=tk.Toplevel(self.root);dialog.title('初始化智能体环境');dialog.geometry('720x450');dialog.grab_set()
        fields={}
        defaults={'环境 ID':'','显示名称':'','Skills 目录':'','快捷方式目录':'','专用版本（默认 shared）':'shared'}
        for label,value in defaults.items():
            ttk.Label(dialog,text=label).pack(anchor='w',padx=14,pady=(8,0))
            row=ttk.Frame(dialog);row.pack(fill='x',padx=14)
            var=tk.StringVar(value=value);fields[label]=var
            ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
            if '目录' in label:
                def browse(v=var):
                    p=filedialog.askdirectory(parent=dialog)
                    if p:v.set(p)
                ttk.Button(row,text='选择',command=browse).pack(side='right')
        ttk.Label(dialog,text='目录由当前智能体核实。初始化会安装本工具并生成启动入口；可以暂不连接 GitHub。').pack(padx=14,pady=10)
        def create():
            args=[fields[k].get().strip() for k in defaults]
            if not all(args):messagebox.showinfo('信息不完整','请填写环境名称和已确认的目录。',parent=dialog);return
            dialog.destroy()
            def init():
                bootstrap.initialize(*args)
                bootstrap.activate(args[0]);self.profile=args[0]
            self.work(init)
        ttk.Button(dialog,text='初始化',command=create).pack(pady=8)
    def configure(self):
        if not self.profile:self.onboard();return
        if engine.CONFIG.exists():messagebox.showinfo('已连接','该环境已连接仓库。需要更换时，请当前智能体保留现有改动后处理。');return
        dialog=tk.Toplevel(self.root);dialog.title('连接 GitHub 仓库');dialog.geometry('700x180');dialog.grab_set()
        ttk.Label(dialog,text='你的 skills 数据仓库地址（建议私有，不是工具源码仓库）').pack(anchor='w',padx=14,pady=8)
        url=ttk.Entry(dialog,width=80);url.pack(fill='x',padx=14)
        c=self.state();ttk.Label(dialog,text='当前 Skills 目录：'+c['root']).pack(anchor='w',padx=14,pady=8)
        def connect():
            u=url.get().strip()
            if not u:return
            selected=c['selected'];dialog.destroy()
            def initialize():
                engine.setup(u,c['root'])
                engine.set_selection(selected)
            self.work(initialize)
        ttk.Button(dialog,text='连接',command=connect).pack()
    def auth_check(self):
        if not engine.CONFIG.exists():
            messagebox.showinfo('尚未连接','请先连接你的 skills 数据仓库，再检查访问权限。');return
        self.work(lambda:engine.auth_status())
    def conflicts(self):
        if not engine.CONFIG.exists():messagebox.showinfo('尚未连接','请先连接仓库。');return
        dialog=tk.Toplevel(self.root);dialog.title('差异与冲突处理');dialog.geometry('740x390');dialog.grab_set()
        c=engine.load();names=engine.available(c,Path(c['repo']))
        chosen=tk.StringVar(value=next(iter(c['selected']),next(iter(names),'')))
        ttk.Label(dialog,text='选择一个 skill；采用本机/合并版仅登记明确决策，随后还需点击上传。').pack(padx=12,pady=12)
        ttk.Combobox(dialog,textvariable=chosen,values=names,state='readonly',width=60).pack(padx=12,pady=6)
        def run(choice):
            name=chosen.get()
            if not name:return
            merged=None
            if choice=='merge':
                merged=filedialog.askdirectory(parent=dialog,title='选择已由智能体合并好的完整 skill 目录')
                if not merged:return
            dialog.destroy()
            def action():
                if choice=='diff':
                    fresh=engine.load();repo=engine.repo_check(fresh);print(engine.support.diff(fresh,name,repo))
                else:engine.support.resolve(name,choice,merged,confirm=lambda:self.confirm('对 '+name+' 执行 '+choice+'？双方副本将保留；不会在此步骤推送 GitHub。'))
            self.work(action)
        for label,choice in [('逐文件比较','diff'),('保存双方冲突副本','export'),('采用本机版','local'),('采用 GitHub 版','remote'),('登记已合并目录','merge')]:
            ttk.Button(dialog,text=label,command=lambda v=choice:run(v)).pack(pady=3)
        def policy():
            fresh=engine.load();fresh['comparison']='lf';engine.save(engine.CONFIG,fresh)
            self.append('当前环境启用 UTF-8 文本 CRLF/LF 等价比较；二进制仍按字节比较。\n');dialog.destroy()
        ttk.Button(dialog,text='启用文本行尾等价比较',command=policy).pack(pady=4)
    def close(self):
        if self.busy:messagebox.showinfo('正在同步','请等待当前操作完成后关闭。');return
        self.root.destroy()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--profile');args=parser.parse_args()
    root=tk.Tk()
    try:App(root,args.profile);root.mainloop()
    except Exception as error:
        messagebox.showerror('启动失败',str(error));root.destroy()
