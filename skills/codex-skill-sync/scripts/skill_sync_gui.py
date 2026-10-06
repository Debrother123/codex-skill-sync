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
import local_sources


class App:
    def __init__(self, root, profile=None):
        self.root=root;self.events=queue.Queue();self.busy=False;self.vars={};self.catalog=[];self.visible=[]
        self.profile=profile or bootstrap.registry().get('active')
        if self.profile:bootstrap.activate(self.profile)
        root.title('Skills 同步助手');root.geometry('1120x820');root.minsize(900,680);root.protocol('WM_DELETE_WINDOW',self.close)
        self.style_ui()
        top=ttk.Frame(root,padding=(24,18,24,10));top.pack(fill='x')
        ttk.Label(top,text='Skills 同步助手',style='Title.TLabel').pack(anchor='w')
        ttk.Label(top,text='找到你的 skill，查看变化，再选择同步范围。',style='Muted.TLabel').pack(anchor='w',pady=6)
        bar=ttk.Frame(top);bar.pack(fill='x',pady=5)
        ttk.Label(bar,text='当前环境  ').pack(side='left')
        self.env=tk.StringVar()
        self.selector=ttk.Combobox(bar,textvariable=self.env,state='readonly',width=30)
        self.selector.pack(side='left');self.selector.bind('<<ComboboxSelected>>',self.switch)
        self.buttons=[]
        b=ttk.Button(bar,text='添加环境',command=self.onboard);b.pack(side='left',padx=8);self.buttons.append(b)
        self.info=ttk.Label(top,text='',style='Muted.TLabel');self.info.pack(anchor='w',pady=4)
        toolbar=ttk.Frame(top);toolbar.pack(fill='x',pady=8)
        for label,command in [('连接 GitHub',self.configure),('刷新清单',self.refresh_remote),('差异与冲突处理',self.conflicts),('认证检查',self.auth_check)]:
            b=ttk.Button(toolbar,text=label,command=command);b.pack(side='left',padx=3);self.buttons.append(b)
        search=ttk.Frame(top);search.pack(fill='x',pady=4)
        self.query=tk.StringVar();self.search_mode=tk.StringVar(value='名称')
        self.status_filter=tk.StringVar(value='全部');self.selection_filter=tk.StringVar(value='全部');self.origin_filter=tk.StringVar(value='全部')
        ttk.Label(search,text='搜索 ').pack(side='left')
        self.search_entry=ttk.Entry(search,textvariable=self.query,width=36);self.search_entry.pack(side='left',padx=4)
        self.filters=[]
        def combo(parent,var,values,width):
            box=ttk.Combobox(parent,textvariable=var,values=values,state='readonly',width=width)
            box.pack(side='left',padx=4);self.filters.append(box)
        for mode in ['名称','功能']:
            ttk.Radiobutton(search,text='按'+mode,variable=self.search_mode,value=mode).pack(side='left',padx=6)
        filters=ttk.Frame(top);filters.pack(fill='x',pady=4)
        for label,var,values,width in [
            ('同步状态',self.status_filter,['全部','尚未上传','本机有更新','GitHub 有更新','两边一致','有冲突 / 需比较','未连接 / 未核验','待确认目录','链接失效','无法检查'],19),
            ('勾选',self.selection_filter,['全部','已勾选','未勾选'],9),
            ('来源',self.origin_filter,['全部','仅本机有','仅 GitHub 有','两边都有'],13)]:
            ttk.Label(filters,text=label).pack(side='left');combo(filters,var,values,width)
        selections=ttk.Frame(top);selections.pack(fill='x',pady=(10,4))
        self.counts=ttk.Label(selections,text='',style='Muted.TLabel');self.counts.pack(side='left')
        for label,command in [('全选当前结果',lambda:self.select(True)),('取消当前结果',lambda:self.select(False)),('清空全部勾选',lambda:self.select(False,True))]:
            button=ttk.Button(selections,text=label,command=command);button.pack(side='right',padx=3);self.buttons.append(button)
        ttk.Button(filters,text='清除筛选',command=self.clear_filters).pack(side='left',padx=6)
        ttk.Label(top,text='仓库状态来自上次刷新 · 链接目录首次同步需确认',style='Muted.TLabel').pack(anchor='w')
        for var in [self.query,self.search_mode,self.status_filter,self.selection_filter,self.origin_filter]:
            var.trace_add('write',lambda *_:self.render())
        area=ttk.Frame(root);area.pack(fill='both',expand=True,padx=24)
        canvas=tk.Canvas(area,highlightthickness=1,highlightbackground='#D6DEE4',background='#FFFFFF');self.canvas=canvas
        scroll=ttk.Scrollbar(area,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        self.rows=ttk.Frame(canvas,style='Content.TFrame');window=canvas.create_window((0,0),window=self.rows,anchor='nw')
        def resize(event):
            canvas.itemconfigure(window,width=event.width)
            self.info.configure(wraplength=max(260,self.root.winfo_width()-64))
            for label in getattr(self,'wrap_labels',[]):label.configure(wraplength=max(260,event.width-80))
        canvas.bind('<Configure>',resize)
        def wheel(event):
            if not str(event.widget).startswith(str(self.canvas)):return
            if event.num in (4,5):delta=-1 if event.num==4 else 1
            else:delta=-int(event.delta/120) if abs(event.delta)>=120 else -int(event.delta)
            canvas.yview_scroll(delta,'units')
        root.bind('<MouseWheel>',wheel,add='+');root.bind('<Button-4>',wheel,add='+');root.bind('<Button-5>',wheel,add='+')
        self.rows.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        actions=ttk.Frame(root,padding=(24,12,24,8));actions.pack(fill='x')
        for label,direction,preview in [('预览上传','upload',True),('上传／提交更新','upload',False),('预览接收','download',True),('从 GitHub 更新','download',False)]:
            b=ttk.Button(actions,text=label,style='Primary.TButton' if direction=='upload' and not preview else 'TButton',command=lambda d=direction,p=preview:self.run_sync(d,p));b.pack(side='left',padx=4);self.buttons.append(b)
        self.activity=ttk.Label(root,text='就绪 · 勾选名单自动保存',style='Muted.TLabel');self.activity.pack(anchor='w',padx=24,pady=(0,4))
        self.progress=ttk.Progressbar(root,mode='indeterminate');self.progress.pack(fill='x',padx=24)
        logarea=ttk.Frame(root);logarea.pack(fill='x',padx=24,pady=(6,16))
        self.log=tk.Text(logarea,height=5,wrap='word',state='disabled',background='#F3F5F7',foreground='#52616D',relief='flat',font=('TkDefaultFont',10))
        logscroll=ttk.Scrollbar(logarea,command=self.log.yview);self.log.configure(yscrollcommand=logscroll.set)
        logscroll.pack(side='right',fill='y');self.log.pack(fill='x',expand=True)
        root.bind('<Command-f>',lambda event:self.search_entry.focus_set())
        root.bind('<Control-f>',lambda event:self.search_entry.focus_set())
        self.refresh();root.after(100,self.poll)
        if not self.profile:self.append('首次使用：请让当前智能体确认目录并完成初始化，或点击“添加智能体”。\n')

    def style_ui(self):
        style=ttk.Style(self.root);style.theme_use('clam')
        self.root.configure(background='#F3F5F7')
        style.configure('.',font=('TkDefaultFont',11),background='#F3F5F7',foreground='#182734')
        style.configure('TButton',padding=(10,7))
        style.map('TButton',background=[('active','#E4EBF0')],foreground=[('disabled','#7B8790')])
        style.configure('Primary.TButton',background='#245C8A',foreground='white')
        style.map('Primary.TButton',background=[('disabled','#D6DEE4'),('active','#19486E')],foreground=[('disabled','#52616D'),('!disabled','white')])
        style.configure('Title.TLabel',font=('TkDefaultFont',22,'bold'))
        style.configure('Muted.TLabel',foreground='#52616D',font=('TkDefaultFont',10))
        style.configure('Content.TFrame',background='white')
        style.configure('Row.TCheckbutton',background='white',font=('TkDefaultFont',12,'bold'),padding=(0,3))
        style.map('Row.TCheckbutton',background=[('active','#EDF3F8')])
        style.configure('Row.TLabel',background='white',foreground='#52616D',font=('TkDefaultFont',10))
        style.configure('State.TLabel',background='white',foreground='#245C8A',font=('TkDefaultFont',10,'bold'))
        style.configure('TCombobox',padding=5)
    def clear_filters(self):
        if self.busy:return
        self.query.set('');self.status_filter.set('全部');self.selection_filter.set('全部');self.origin_filter.set('全部')
    def descendants(self,widget):
        for child in widget.winfo_children():
            yield child
            yield from self.descendants(child)
    def focus_row(self,event,frame):
        total=max(self.rows.winfo_height(),1);top=frame.winfo_y();bottom=top+frame.winfo_height()
        first,last=self.canvas.yview()
        if top<first*total:self.canvas.yview_moveto(top/total)
        elif bottom>last*total:self.canvas.yview_moveto(max(0,(bottom-self.canvas.winfo_height())/total))
    def manage_link(self,name,callback=None):
        if self.busy:return
        if not engine.CONFIG.exists():
            self.append('先连接个人 skills 仓库，再登记链接目录。\n');return
        info=local_sources.inspect(engine.load(),name)
        dialog=tk.Toplevel(self.root);dialog.title('管理链接目录');dialog.geometry('740x380');dialog.transient(self.root);dialog.grab_set()
        dialog.bind('<Escape>',lambda event:dialog.destroy())
        ttk.Label(dialog,text=name,style='Title.TLabel').pack(anchor='w',padx=20,pady=(20,10))
        ttk.Label(dialog,text='入口：'+info['entry']+'\n\n真实目录：'+info['target'],wraplength=690).pack(anchor='w',padx=20)
        ttk.Label(dialog,text='上传读取真实内容；接收更新会备份并替换真实目录，保留入口链接。\n只登记该目录，不会立即上传。目标变化后需要重新确认。',wraplength=690).pack(anchor='w',padx=20,pady=16)
        error=ttk.Label(dialog,text=info['problem'] or '',wraplength=690);error.pack(anchor='w',padx=20)
        def apply():
            try:local_sources.approve(name,info['target'])
            except (RuntimeError,OSError) as exc:error.configure(text=str(exc));return
            dialog.destroy();self.refresh()
            if callback:callback()
        actions=ttk.Frame(dialog);actions.pack(fill='x',padx=20,pady=16)
        button=ttk.Button(actions,text='管理此真实目录',style='Primary.TButton',command=apply);button.pack(side='left')
        if info['problem']:button.configure(state='disabled')
        if info['linked'] and info['approved']:
            def revoke():
                local_sources.revoke(name);dialog.destroy();self.refresh();self.append('已撤销目录授权，文件和链接保留。\n')
            ttk.Button(actions,text='撤销目录授权',command=revoke).pack(side='left',padx=8)
        ttk.Button(actions,text='取消',command=dialog.destroy).pack(side='right');button.focus_set()
    def prepare_links(self,names,callback):
        c=engine.load()
        for name in names:
            info=local_sources.inspect(c,name)
            if info['problem']:
                self.append(name+'：'+info['problem']+'\n');self.activity.configure(text='未开始同步 · 请修复失效链接后刷新');return
            if not info['approved']:
                self.manage_link(name,lambda:self.prepare_links(names,callback));return
        callback()

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
                self.progress.stop();self.activity.configure(text=data)
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
        self.activity.configure(text='正在处理当前环境 · 完成前请保持窗口打开');self.progress.start(12)
        for b in self.buttons:b.configure(state='disabled')
        for b in self.descendants(self.rows):
            if isinstance(b,(ttk.Checkbutton,ttk.Button)):b.configure(state='disabled')
        def task():
            old=sys.stdout;sys.stdout=self
            # One app-wide lock prevents concurrent self-updates across profiles.
            lock=bootstrap.BASE/'running.lock';owned=False
            outcome='操作已结束 · 结果与备份位置见日志'
            try:
                bootstrap.BASE.mkdir(parents=True,exist_ok=True)
                fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd);owned=True
                fn()
            except FileExistsError:
                outcome='未完成 · 请检查已有操作或遗留锁，再重试'
                print('未完成：已有同步操作运行，或上次异常退出留有锁。请当前智能体检查。')
            except Exception as e:
                outcome='未完成 · 查看日志中的原因，修复后重试'
                print('未完成：',e)
            finally:
                if owned:lock.unlink(missing_ok=True)
                sys.stdout=old;self.events.put(('done',outcome))
        threading.Thread(target=task,daemon=True).start()
    def state(self):
        if engine.CONFIG.exists():return engine.load()
        selected=engine.read_selection()
        default=engine.DEFAULT_ROOT or str(Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'skills')
        return {'root':default,'repo':str(engine.HOME/'repository'),'selected':selected,'variant':engine.DEFAULT_VARIANT}
    def persist(self):
        if self.busy or not self.profile:return
        focused=self.root.focus_get()
        focus_name=next((n for n,w in getattr(self,'row_checks',{}).items() if w==focused),None)
        chosen=[n for n,v in self.vars.items() if v.get()]
        engine.set_selection(chosen)
        self.render()
        if focus_name:
            self.row_checks.get(focus_name,self.search_entry).focus_set()
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
            self.info.configure(text='Skills：'+c['root']+'  |  版本：'+c.get('variant','shared')+('' if engine.CONFIG.exists() else '  |  GitHub 未连接')+'\n状态目录：'+str(engine.HOME))
            local=Path(c['root']);repo=Path(c['repo'])
            names=engine.available(c,repo)
            sources=local_sources.inventory(c)
            self.catalog=[catalog.entry(c,repo,n) for n in names]
            for row in self.catalog:row['aliases']=sources.get(row['name'],{}).get('aliases',[])
            # Retain selections even when a missing skill is not currently listed.
            for n in sorted(set(names)|set(c['selected'])):
                self.vars[n]=tk.BooleanVar(value=n in c['selected'])
            self.render()
        except Exception as e:self.append(str(e)+'\n')
    def render(self):
        if self.busy:return
        for widget in self.rows.winfo_children():widget.destroy()
        self.visible=[];self.wrap_labels=[];self.row_checks={}
        for row in self.catalog:
            n=row['name']
            if not catalog.matches(row,self.query.get(),self.search_mode.get(),self.status_filter.get(),self.selection_filter.get(),self.origin_filter.get(),self.vars[n].get()):continue
            self.visible.append(n)
            frame=ttk.Frame(self.rows,style='Content.TFrame',padding=(16,12));frame.pack(fill='x')
            header=ttk.Frame(frame,style='Content.TFrame');header.pack(fill='x')
            check=ttk.Checkbutton(header,text=n,style='Row.TCheckbutton',variable=self.vars[n],command=self.persist);check.pack(side='left');self.row_checks[n]=check
            ttk.Label(header,text=row['status']+' · '+row['origin'],style='State.TLabel').pack(side='right',padx=4)
            def label(text):
                item=ttk.Label(frame,text=text,style='Row.TLabel',wraplength=max(260,self.canvas.winfo_width()-80));item.pack(anchor='w',padx=(23,0),pady=(4,0));self.wrap_labels.append(item)
            label(row['description'])
            info=row['source'];label(('链接到 ' if info['linked'] else '目录 ')+info['target'])
            if row.get('aliases'):label('其他入口已合并：'+', '.join(row['aliases']))
            if info['linked']:
                button=ttk.Button(frame,text='目录已授权 · 查看' if info['approved'] else '管理此目录',command=lambda name=n:self.manage_link(name))
                button.pack(anchor='w',padx=(23,0),pady=(7,0));button.bind('<FocusIn>',lambda event,f=frame:self.focus_row(event,f))
            if row.get('error'):label(row['error'])
            check.bind('<FocusIn>',lambda event,f=frame:self.focus_row(event,f))
            ttk.Separator(self.rows).pack(fill='x',padx=16)
        if not self.visible:
            empty=ttk.Frame(self.rows,style='Content.TFrame',padding=32);empty.pack(fill='x')
            ttk.Label(empty,text='没有匹配的 skill' if self.catalog else '这个环境还没有可识别的 skill',style='Row.TLabel').pack(anchor='w')
            ttk.Button(empty,text='清除筛选' if self.catalog else '刷新清单',command=self.clear_filters if self.catalog else self.refresh_remote).pack(anchor='w',pady=12)
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
        dialog=tk.Toplevel(self.root);dialog.title('选择本次操作范围');dialog.geometry('650x370');dialog.transient(self.root);dialog.grab_set();dialog.bind('<Escape>',lambda event:dialog.destroy())
        ttk.Label(dialog,text='每次操作都重新选择范围，取消则不执行。').pack(anchor='w',padx=18,pady=14)
        scope=tk.StringVar(value='')
        ttk.Radiobutton(dialog,text=f'全部勾选项：{len(selected)} 项（含隐藏的 {len(selected)-len(shown)} 项）',variable=scope,value='all').pack(anchor='w',padx=18,pady=6)
        ttk.Radiobutton(dialog,text=f'当前可见且已勾选的项：{len(shown)} 项',variable=scope,value='visible').pack(anchor='w',padx=18,pady=6)
        message=tk.StringVar()
        if direction=='upload':
            ttk.Label(dialog,text='更新说明（可选，留空自动生成）').pack(anchor='w',padx=18,pady=(14,4))
            ttk.Entry(dialog,textvariable=message,width=70).pack(fill='x',padx=18)
        validation=ttk.Label(dialog,text='');validation.pack(anchor='w',padx=18,pady=4)
        def proceed():
            if not scope.get():validation.configure(text='请选择本次操作范围。');return
            names=catalog.scope_names(selected,visible,scope.get())
            if not names:validation.configure(text='该范围内没有已勾选的 skill。');return
            note=message.get();dialog.destroy()
            prompt=f'本次处理 {len(names)} 项：\n'+', '.join(names)+'\n变更见日志；覆盖旧版会备份。'
            self.prepare_links(names,lambda:self.work(lambda:engine.sync(direction,preview,lambda:self.confirm(prompt),selected=names,message=note)))
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
