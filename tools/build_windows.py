"""Build a Python-free Windows bundle and verify the frozen runtime."""
import hashlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile
import json

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.1.0'


def icon_file(path):
    pixels = bytearray()
    for y in reversed(range(32)):
        for x in range(32):
            color = (115, 40, 63)
            radius = (x - 13) ** 2 + (y - 13) ** 2
            if 35 <= radius <= 65 or (19 <= x <= 26 and abs(x-y) <= 1):
                color = (246, 233, 221)
            pixels.extend((*reversed(color), 255))
    dib = struct.pack('<IiiHHIIiiII', 40, 32, 64, 1, 32, 0, len(pixels), 0, 0, 0, 0) + pixels + bytes(128)
    path.write_bytes(struct.pack('<HHH',0,1,1)+struct.pack('<BBBBHHII',32,32,0,0,1,32,len(dib),22)+dib)


def build():
    if os.name != 'nt' or struct.calcsize('P') != 8:
        raise RuntimeError('Build on 64-bit Windows with 64-bit Python')
    work = ROOT / 'build'
    work.mkdir(exist_ok=True)
    icon = work / 'icon.ico'
    icon_file(icon)
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed','--noupx',
                    '--name','LocalDocFinder','--icon',str(icon), '--add-data',str(ROOT/'static')+os.pathsep+'static',
                    '--workpath',str(work/'pyinstaller'),'--specpath',str(work),'--distpath',str(ROOT/'dist'),
                    str(ROOT/'desktop.py')], cwd=ROOT, check=True)
    folder = ROOT / 'dist/LocalDocFinder'
    shutil.copy2(ROOT / 'LICENSE', folder / 'LICENSE')
    shutil.copy2(ROOT / 'docs/桌面版使用说明.txt', folder / '使用说明.txt')
    notices = ['Local Doc Finder: MIT. See LICENSE.', '',
               'Third-party components retain their own licenses.',
               'Python runtime: https://docs.python.org/3/license.html',
               'pypdf: BSD-3-Clause. https://github.com/py-pdf/pypdf',
               'PyInstaller bootloader: GPL with distribution exception. https://pyinstaller.org/en/stable/license.html', '']
    notices.append((Path(sys.base_prefix) / 'LICENSE.txt').read_text(encoding='utf-8'))
    for name in ('pyinstaller','pypdf'):
        distribution = importlib.metadata.distribution(name)
        for item in distribution.files:
            if '/licenses/' in str(item).lower() and str(item).lower().endswith(('.txt','license')):
                notices.extend(['\n--- '+str(item)+' ---\n', distribution.locate_file(item).read_text(encoding='utf-8',errors='replace')])
    for path in folder.rglob('license.terms'):
        notices.extend(['\n--- '+str(path.relative_to(folder))+' ---\n', path.read_text(encoding='utf-8', errors='replace')])
    (folder / 'THIRD-PARTY-NOTICES.txt').write_text('\n'.join(notices), encoding='utf-8')
    report = work / 'frozen-check.json'
    report.unlink(missing_ok=True)
    env = dict(os.environ)
    env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)
    result = subprocess.run([str(folder/'LocalDocFinder.exe'),'--self-test',str(report)],
                            cwd=work, env=env, timeout=120)
    if result.returncode != 0 or not report.is_file():
        raise RuntimeError('Frozen EXE failed to complete self-test')
    data = json.loads(report.read_text(encoding='utf-8'))
    if not data['ok']:
        raise RuntimeError(str(data))
    print(json.dumps(data, ensure_ascii=True))
    output = ROOT / 'releases'
    output.mkdir(exist_ok=True)
    archive_path = output / f'LocalDocFinder-{VERSION}-windows-x64.zip'
    with zipfile.ZipFile(archive_path,'w',zipfile.ZIP_DEFLATED) as z:
        for path in folder.rglob('*'):
            if path.is_file():
                z.write(path, str(Path('LocalDocFinder') / path.relative_to(folder)))
    with zipfile.ZipFile(archive_path) as z:
        assert z.testzip() is None
        assert z.read('LocalDocFinder/LICENSE') == (ROOT / 'LICENSE').read_bytes()
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(checksum+'  '+archive_path.name+'\n',encoding='utf-8')
    print(json.dumps({'zip':str(archive_path),'size':archive_path.stat().st_size,'sha256':checksum},ensure_ascii=True))


if __name__ == '__main__':
    build()
