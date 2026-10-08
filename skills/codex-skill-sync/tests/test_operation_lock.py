import sys,tempfile,subprocess,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from operation_lock import OperationLock
class LockTests(unittest.TestCase):
    def test_exclusion_and_release(self):
        with tempfile.TemporaryDirectory() as td:
            with OperationLock(td):
                with self.assertRaises(RuntimeError):OperationLock(td).acquire()
            with OperationLock(td):pass
    def test_crashed_process_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            code='import sys,os;sys.path.insert(0,sys.argv[1]);from operation_lock import OperationLock;lock=OperationLock(sys.argv[2]).acquire();os._exit(0)'
            subprocess.run([sys.executable,'-c',code,str(Path(__file__).resolve().parents[1]/'scripts'),td],check=True)
            self.assertTrue((Path(td)/'running.lock').exists())
            with OperationLock(td):pass
            self.assertFalse((Path(td)/'running.lock').exists())
    def test_unknown_legacy_lock_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            sentinel=Path(td)/'running.lock';sentinel.touch()
            with self.assertRaises(RuntimeError):OperationLock(td).acquire()
            self.assertTrue(sentinel.exists())
if __name__=='__main__':unittest.main()
