"""Windowed Windows entry point; HTTP UI remains entirely local."""
import multiprocessing
import sys


class InstanceLock:
    def __init__(self, directory):
        self.path = directory / 'desktop.lock'
        self.stream = None

    def acquire(self):
        import os
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self.stream = stream
        return True

    def release(self):
        if self.stream:
            self.stream.close()  # OS releases the lock on close or process exit
            self.stream = None


def session_url(path):
    import json
    from urllib.parse import urlsplit
    data = json.loads(path.read_text(encoding='utf-8'))
    parsed = urlsplit(data['url'])
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.path not in {'', '/'} or parsed.username or parsed.query or parsed.fragment:
        raise ValueError('运行地址无效')
    return data['url']


def main():
    import argparse
    import json
    import os
    from pathlib import Path
    import threading
    import tkinter as tk
    from tkinter import messagebox, ttk
    import urllib.request
    import webbrowser
    from app import Server, Service

    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'LocalDocFinder')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    lock = InstanceLock(data_dir)
    session = data_dir / 'desktop-session.json'
    window = tk.Tk()
    window.withdraw()
    if not lock.acquire():
        try:
            url = session_url(session)
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status != 200 or not response.headers.get('Server', '').startswith('LocalDocFinder/'):
                    raise ValueError('服务尚未准备好')
            if not args.no_browser:
                webbrowser.open(url)
        except Exception:
            messagebox.showinfo('本地文档检索台', '软件已在启动或退出中，请稍候再打开。', parent=window)
        window.destroy()
        return 0
    server = None
    try:
        service = Service(data_dir / 'index.sqlite3')
        try:
            server = Server(('127.0.0.1', args.port), service)
        except OSError:
            if args.port != 8766:
                raise
            server = Server(('127.0.0.1', 0), service)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        session.write_text(json.dumps({'url': url, 'pid': os.getpid()}), encoding='utf-8')

        window.title('本地文档检索台 · 运行管理')
        window.geometry('570x335')
        window.resizable(False, False)
        window.configure(bg='#f6f3ee')
        icon = tk.PhotoImage(width=32, height=32)
        icon.put('#752b43', to=(1, 1, 31, 31))
        for y in range(6, 24):
            for x in range(6, 24):
                radius = (x - 14) ** 2 + (y - 14) ** 2
                if 36 <= radius <= 64 or (20 <= x <= 25 and abs(x - y) <= 1):
                    icon.put('#f6e8dd', (x, y))
        window.iconphoto(True, icon)
        label = lambda text, **kw: tk.Label(window, text=text, bg='#f6f3ee', fg='#30292c', font=('Microsoft YaHei UI', 10), **kw)
        tk.Label(window, text='本地文档检索台', bg='#f6f3ee', fg='#752b43', font=('Microsoft YaHei UI', 20, 'bold')).pack(anchor='w', padx=28, pady=(25, 8))
        status = tk.StringVar(value='● 服务运行中 · 文档和索引留在本机')
        tk.Label(window, textvariable=status, bg='#f6f3ee', fg='#667b65', font=('Microsoft YaHei UI', 10)).pack(anchor='w', padx=29)
        address = ttk.Entry(window, font=('Segoe UI', 11), state='normal')
        address.insert(0, url)
        address.configure(state='readonly')
        address.pack(fill='x', padx=29, pady=(18, 12), ipady=5)
        label('支持 Markdown、TXT、DOCX 和有文本层的 PDF').pack(anchor='w', padx=29)
        label('关闭这个窗口将停止本地服务，已建立的索引会保留。').pack(anchor='w', padx=29, pady=(5, 16))
        buttons = tk.Frame(window, bg='#f6f3ee')
        buttons.pack(fill='x', padx=29)
        open_button = tk.Button(buttons, text='打开检索网页', command=lambda: webbrowser.open(url), bg='#752b43', fg='white', activebackground='#8c3652', activeforeground='white', relief='flat', padx=22, pady=9, font=('Microsoft YaHei UI', 10))
        open_button.pack(side='left')
        closing = False

        def close():
            nonlocal closing
            if closing:
                return
            closing = True
            service.cancel.set()
            open_button.configure(state='disabled')
            exit_button.configure(state='disabled')
            status.set('正在停止服务；当前文档处理结束后会自动退出…')
            wait_for_job()

        def wait_for_job():
            with service.guard:
                busy = service.job['state'] == 'running'
            if busy:
                window.after(150, wait_for_job)
            else:
                window.quit()

        exit_button = tk.Button(buttons, text='退出软件', command=close, bg='#ebe2e4', fg='#752b43', relief='flat', padx=22, pady=9, font=('Microsoft YaHei UI', 10))
        exit_button.pack(side='left', padx=12)
        window.protocol('WM_DELETE_WINDOW', close)
        window.deiconify()
        if not args.no_browser:
            window.after(250, lambda: webbrowser.open(url))
        window.mainloop()
    except Exception as exc:
        messagebox.showerror('启动失败', str(exc), parent=window)
        return 1
    finally:
        if server:
            server.shutdown()
            server.server_close()
        session.unlink(missing_ok=True)
        lock.release()
        window.destroy()
    return 0


if __name__ == '__main__':
    multiprocessing.freeze_support()  # before argument parsing or GUI creation
    if '--pick-directory' in sys.argv:
        from app import main as picker_main
        picker_main()
    elif len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        import json
        from pathlib import Path
        try:
            from release_check import run
            run(Path(sys.argv[2]))
        except Exception as error:
            Path(sys.argv[2]).write_text(json.dumps({'ok': False, 'error': str(error)}), encoding='utf-8')
            sys.exit(1)
    else:
        sys.exit(main())
