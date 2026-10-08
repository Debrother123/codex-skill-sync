"""OS-owned operation lock; legacy sentinel retained for older clients."""
import json
import os
from pathlib import Path

class OperationLock:
    def __init__(self,base):
        self.base=Path(base);self.file=None;self.owned=False
    def acquire(self):
        self.base.mkdir(parents=True,exist_ok=True)
        self.file=(self.base/'operation.lock').open('a+b')
        self.file.seek(0,2)
        if self.file.tell()==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();self.file=None
            raise RuntimeError('另一个同步操作正在运行，请等待完成后重试。') from None
        legacy=self.base/'running.lock'
        try:
            if legacy.exists():
                try:record=json.loads(legacy.read_text())
                except (ValueError,OSError):record={}
                if record.get('protocol')!=2:
                    raise RuntimeError('发现旧版遗留锁 running.lock。请先确认没有旧版同步任务，再由智能体备份移走该文件。')
                # OS lock is exclusively held: a v2 sentinel cannot have a live owner.
                legacy.unlink()
            with legacy.open('x') as f:json.dump({'protocol':2,'pid':os.getpid()},f)
            self.owned=True
        except Exception:
            self.release();raise
        return self
    def release(self):
        if self.owned:
            (self.base/'running.lock').unlink(missing_ok=True);self.owned=False
        if self.file:
            if os.name=='nt':
                import msvcrt
                self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
            self.file.close();self.file=None
    def __enter__(self):return self.acquire()
    def __exit__(self,*args):self.release()
