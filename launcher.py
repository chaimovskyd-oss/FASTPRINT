import sys
import time
import subprocess
import tempfile
from pathlib import Path

try:
    import msvcrt
except ImportError:
    msvcrt = None

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app' / 'main.py'
QUEUE_DIR = Path(tempfile.gettempdir()) / 'hadish_smart_photo_print'
QUEUE_FILE = QUEUE_DIR / 'selected_paths.txt'
LOCK_FILE = QUEUE_DIR / 'launch.lock'


def _pythonw() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == 'python.exe':
        pyw = exe.with_name('pythonw.exe')
        if pyw.exists():
            return str(pyw)
    return str(exe)


def _valid_paths(args):
    out = []
    for arg in args:
        p = arg.strip('"')
        if p and Path(p).exists():
            out.append(str(Path(p).resolve()))
    return out


def _append_paths(paths):
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_FILE, 'a', encoding='utf-8') as f:
        if msvcrt:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            except OSError:
                pass
        for p in paths:
            f.write(p + '\n')
        f.flush()
        if msvcrt:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass


def _take_batch():
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.touch(exist_ok=True)
    with open(LOCK_FILE, 'r+b') as lock:
        if msvcrt:
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            except OSError:
                return []
        try:
            if not QUEUE_FILE.exists():
                return []
            raw = QUEUE_FILE.read_text(encoding='utf-8', errors='ignore').splitlines()
            QUEUE_FILE.write_text('', encoding='utf-8')
            seen = set()
            batch = []
            for p in raw:
                if p and p not in seen and Path(p).exists():
                    seen.add(p)
                    batch.append(p)
            return batch
        finally:
            if msvcrt:
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass


def main():
    paths = _valid_paths(sys.argv[1:])
    if not paths:
        subprocess.Popen([_pythonw(), str(APP)], cwd=str(ROOT))
        return
    _append_paths(paths)
    # Windows Explorer may invoke this command once per selected file.
    # Wait briefly so all invocations can join one batch, then only one process opens the app.
    time.sleep(1.4)
    batch = _take_batch()
    if batch:
        subprocess.Popen([_pythonw(), str(APP), *batch], cwd=str(ROOT))


if __name__ == '__main__':
    main()
