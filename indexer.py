"""SQLite snapshots and literal, ASCII-case-insensitive substring search."""
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import threading

from extraction import MAX_PDF_BYTES, MAX_TEXT_BYTES, MAX_DOCX_BYTES, extract

KINDS = {'.md': 'md', '.markdown': 'md', '.txt': 'txt', '.pdf': 'pdf', '.docx': 'docx'}
FOLD_TABLE = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')
EXCLUDED_DIRS = {'.git', '.venv', 'node_modules', '__pycache__'}


def fold(value):
    return value.translate(FOLD_TABLE)


def now():
    return datetime.now(timezone.utc).isoformat()


def is_link(path):
    s = path.lstat()
    return stat.S_ISLNK(s.st_mode) or bool(getattr(s, 'st_file_attributes', 0) & 0x400)


def fingerprint(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)


def safe_path(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or ':' in str(rel):
        raise ValueError('无效文档路径')
    path = root
    for part in rel.parts:
        path = path / part
        if is_link(path):
            raise OSError('路径已变为符号链接或目录联接，请更新索引')
    if not path.resolve().is_relative_to(root.resolve()):
        raise OSError('文件已经移出资料目录')
    return path


def segments(text, terms):
    ranges = []
    lowered = fold(text)
    for term in terms:
        start = 0
        while (start := lowered.find(term, start)) >= 0:
            ranges.append((start, start + len(term)))
            start += max(1, len(term))
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    result, cursor = [], 0
    for start, end in merged:
        if start > cursor:
            result.append({'text': text[cursor:start], 'hit': False})
        result.append({'text': text[start:end], 'hit': True})
        cursor = end
    if cursor < len(text) or not result:
        result.append({'text': text[cursor:], 'hit': False})
    return result


def snippets(text, terms):
    lowered = fold(text)
    hits = sorted({lowered.find(t) for t in terms if t in lowered})
    result, end_before = [], -1
    for hit in hits:
        if hit < end_before:
            continue
        start, end = max(0, hit - 65), min(len(text), hit + 155)
        excerpt = text[start:end]
        result.append({'segments': segments(excerpt, terms), 'prefix': start > 0, 'suffix': end < len(text)})
        end_before = end
        if len(result) == 3:
            break
    return result


class Index:
    def __init__(self, database):
        self.database = Path(database).resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.update_lock = threading.Lock()
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS roots(id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, updated TEXT);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS documents(
                    id INTEGER PRIMARY KEY, root_id INTEGER NOT NULL REFERENCES roots(id),
                    relative TEXT NOT NULL, name TEXT NOT NULL, name_fold TEXT NOT NULL, kind TEXT NOT NULL,
                    digest TEXT, size INTEGER, mtime_ns INTEGER, status TEXT NOT NULL, message TEXT NOT NULL,
                    UNIQUE(root_id,relative));
                CREATE TABLE IF NOT EXISTS pages(
                    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    number INTEGER NOT NULL, text TEXT NOT NULL, text_fold TEXT NOT NULL,
                    PRIMARY KEY(doc_id,number));
                CREATE INDEX IF NOT EXISTS doc_roots ON documents(root_id);
                CREATE TABLE IF NOT EXISTS issues(root_id INTEGER, relative TEXT, message TEXT);
            ''')
            if 'location' not in {row['name'] for row in db.execute('PRAGMA table_info(pages)')}:
                db.execute('ALTER TABLE pages ADD COLUMN location TEXT')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def choose(self, folder):
        if not str(folder).strip():
            raise ValueError('请先输入或选择资料目录')
        root = Path(folder).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError('资料路径必须是目录')
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO roots(path) VALUES(?)', (str(root),))
            identifier = db.execute('SELECT id FROM roots WHERE path=?', (str(root),)).fetchone()[0]
            db.execute("INSERT OR REPLACE INTO settings VALUES('current_root',?)", (str(identifier),))
        return identifier

    def current(self):
        with self.connect() as db:
            return db.execute("SELECT r.* FROM roots r JOIN settings s ON r.id=CAST(s.value AS INTEGER) WHERE s.key='current_root'").fetchone()

    def snapshot(self):
        with self.connect() as db:
            root = self.current()
            roots = [dict(r) for r in db.execute('SELECT * FROM roots ORDER BY id DESC')]
            if not root:
                return dict(root=None, roots=roots, documents=0, searchable=0, warnings=0, issues=[])
            counts = db.execute("SELECT COUNT(*),SUM(EXISTS(SELECT 1 FROM pages p WHERE p.doc_id=documents.id AND trim(p.text)!='')),SUM(status!='indexed') FROM documents WHERE root_id=?", (root['id'],)).fetchone()
            issues = [dict(r) for r in db.execute('SELECT relative,message FROM issues WHERE root_id=? ORDER BY rowid LIMIT 500', (root['id'],))]
            issue_count = db.execute('SELECT COUNT(*) FROM issues WHERE root_id=?', (root['id'],)).fetchone()[0]
            return dict(root=dict(root), roots=roots, documents=counts[0], searchable=counts[1] or 0,
                        warnings=counts[2] or 0, issues=issues, issue_count=issue_count)

    def update(self, root_id, progress=lambda _: None, cancel=None):
        if not self.update_lock.acquire(blocking=False):
            raise ValueError('已有索引任务在运行')
        try:
            return self._update(root_id, progress, cancel or threading.Event())
        finally:
            self.update_lock.release()

    def _update(self, root_id, progress, cancel):
        stats = dict(scanned=0, added=0, modified=0, unchanged=0, deleted=0, failed=0, skipped=0)
        with self.connect() as db:
            row = db.execute('SELECT path FROM roots WHERE id=?', (root_id,)).fetchone()
            if not row:
                raise ValueError('资料目录不存在')
            root = Path(row['path'])
            # Verify root accessibility before beginning replacement/deletion.
            with os.scandir(root) as entries:
                list(entries)
            db.execute('BEGIN IMMEDIATE')
            old = {r['relative']: r for r in db.execute('SELECT * FROM documents WHERE root_id=?', (root_id,))}
            seen, blocked, issues = set(), [], []
            stack = [root]
            while stack:
                if cancel.is_set():
                    raise ValueError('已取消；本次更新未提交，原索引保持不变')
                directory = stack.pop()
                try:
                    with os.scandir(directory) as iterator:
                        entries = sorted(iterator, key=lambda e: e.name.lower())
                except OSError as exc:
                    prefix = directory.relative_to(root).as_posix()
                    blocked.append(prefix)
                    issues.append((prefix, f'目录读取失败：{exc}；该子目录的旧正文暂不参与搜索'))
                    continue
                for entry in entries:
                    if cancel.is_set():
                        raise ValueError('已取消；本次更新未提交，原索引保持不变')
                    path = Path(entry.path)
                    relative = path.relative_to(root).as_posix()
                    try:
                        if is_link(path):
                            stats['skipped'] += 1
                            blocked.append(relative)
                            issues.append((relative, '已跳过符号链接或目录联接，不跟随目录外的文件'))
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name in EXCLUDED_DIRS or path.resolve() == self.database.parent:
                                stats['skipped'] += 1
                                blocked.append(relative)
                            else:
                                stack.append(path)
                            continue
                        if path.suffix.lower() not in KINDS:
                            stats['skipped'] += 1
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            raise OSError('不是普通文件')
                    except OSError as exc:
                        blocked.append(relative)
                        issues.append((relative, f'无法检查文件类型：{exc}'))
                        continue
                    seen.add(relative)
                    stats['scanned'] += 1
                    kind, previous = KINDS[path.suffix.lower()], old.get(relative)
                    progress({**stats, 'current': relative})
                    size, mtime, digest = None, None, None
                    try:
                        safe_path(root, relative)
                        before = path.stat()
                        limit = MAX_PDF_BYTES if kind == 'pdf' else MAX_DOCX_BYTES if kind == 'docx' else MAX_TEXT_BYTES
                        if before.st_size > limit:
                            raise ValueError(f'文件超过 {limit // 1024**2} MiB 上限，未建立正文索引')
                        with path.open('rb') as stream:
                            data = stream.read(limit + 1)
                        if len(data) > limit:
                            raise ValueError('读取期间文件增长，超出大小上限')
                        after = path.stat()
                        if fingerprint(before) != fingerprint(after):
                            raise ValueError('读取期间文件发生变化，请稍后重新更新索引')
                        size, mtime = after.st_size, after.st_mtime_ns
                        digest = hashlib.sha256(data).hexdigest()
                        if previous and previous['digest'] == digest and previous['status'] in {'indexed', 'warning'}:
                            stats['unchanged'] += 1
                            db.execute('UPDATE documents SET size=?,mtime_ns=? WHERE id=?', (size, mtime, previous['id']))
                            if previous['message']:
                                issues.append((relative, previous['message']))
                            progress({**stats, 'current': relative})
                            continue
                        pages, warnings = extract(data, kind)
                        if fingerprint(path.stat()) != fingerprint(after):
                            raise ValueError('提取期间文件发生变化，请稍后重新更新索引')
                        status = 'warning' if warnings else 'indexed'
                        message = '\n'.join(warnings)
                    except (OSError, ValueError, UnicodeError) as exc:
                        pages, status = [], 'error'
                        message = f'读取或提取失败：{exc}'
                        stats['failed'] += 1
                    if message:
                        issues.append((relative, message))
                    db.execute('''INSERT INTO documents(root_id,relative,name,name_fold,kind,digest,size,mtime_ns,status,message)
                        VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(root_id,relative) DO UPDATE SET
                        name=excluded.name,name_fold=excluded.name_fold,kind=excluded.kind,digest=excluded.digest,
                        size=excluded.size,mtime_ns=excluded.mtime_ns,status=excluded.status,message=excluded.message''',
                        (root_id, relative, path.name, fold(path.name), kind, digest, size, mtime, status, message))
                    doc_id = db.execute('SELECT id FROM documents WHERE root_id=? AND relative=?', (root_id, relative)).fetchone()[0]
                    db.execute('DELETE FROM pages WHERE doc_id=?', (doc_id,))
                    db.executemany('INSERT INTO pages(doc_id,number,text,text_fold,location) VALUES(?,?,?,?,?)',
                                   [(doc_id, unit[0], unit[1], fold(unit[1]), unit[2] if len(unit) == 3 else None) for unit in pages])
                    stats['modified' if previous else 'added'] += 1
                    progress({**stats, 'current': relative})
            for relative, previous in old.items():
                if relative in seen:
                    continue
                if any(relative == p or relative.startswith(p + '/') or p == '.' for p in blocked):
                    db.execute("UPDATE documents SET status='error',digest=NULL,message=? WHERE id=?",
                               ('上级目录不可访问或已跳过，旧正文暂不参与搜索', previous['id']))
                    db.execute('DELETE FROM pages WHERE doc_id=?', (previous['id'],))
                else:
                    db.execute('DELETE FROM documents WHERE id=?', (previous['id'],))
                    stats['deleted'] += 1
            if cancel.is_set():
                raise ValueError('已取消；本次更新未提交，原索引保持不变')
            db.execute('DELETE FROM issues WHERE root_id=?', (root_id,))
            db.executemany('INSERT INTO issues VALUES(?,?,?)', [(root_id, p, m) for p, m in issues])
            db.execute('UPDATE roots SET updated=? WHERE id=?', (now(), root_id))
        return stats

    def search(self, query, kind='all', offset=0, limit=20):
        if len(query) > 200:
            raise ValueError('搜索内容最多 200 个字符')
        terms = list(dict.fromkeys(fold(query).split()))
        if len(terms) > 12:
            raise ValueError('最多输入 12 个关键词')
        if kind not in {'all', 'md', 'txt', 'pdf', 'docx'}:
            raise ValueError('未知文档类型')
        offset, limit = max(0, int(offset)), max(1, min(100, int(limit)))
        root = self.current()
        if not root or not terms:
            return dict(results=[], total=0, terms=terms, offset=offset, limit=limit)
        where, params = ['d.root_id=?'], [root['id']]
        if kind != 'all':
            where.append('d.kind=?')
            params.append(kind)
        for term in terms:
            where.append('(instr(d.name_fold,?)>0 OR EXISTS(SELECT 1 FROM pages p WHERE p.doc_id=d.id AND instr(p.text_fold,?)>0))')
            params.extend((term, term))
        clause = ' AND '.join(where)
        with self.connect() as db:
            total = db.execute('SELECT COUNT(*) FROM documents d WHERE ' + clause, params).fetchone()[0]
            rows = db.execute('SELECT d.* FROM documents d WHERE ' + clause + ' ORDER BY d.relative COLLATE NOCASE LIMIT ? OFFSET ?', params + [limit, offset]).fetchall()
            results = []
            for doc in rows:
                excerpts, matched_pages = [], []
                for page in db.execute('SELECT * FROM pages WHERE doc_id=? ORDER BY number', (doc['id'],)):
                    if any(t in page['text_fold'] for t in terms):
                        if doc['kind'] == 'pdf' and page['number']:
                            matched_pages.append(page['number'])
                        if len(excerpts) < 8:
                            for snippet in snippets(page['text'], terms):
                                excerpts.append({**snippet, 'page': page['number'] if doc['kind'] == 'pdf' else None,
                                                 'location': page['location'],
                                                 'block': page['number'] if doc['kind'] == 'docx' else None})
                                if len(excerpts) == 8:
                                    break
                results.append(dict(id=doc['id'], name=doc['name'], relative=doc['relative'], kind=doc['kind'],
                                    status=doc['status'], message=doc['message'], snippets=excerpts,
                                    matched_pages=matched_pages, name_segments=segments(doc['name'], terms),
                                    filename_match=any(t in doc['name_fold'] for t in terms)))
        return dict(results=results, total=total, terms=terms, offset=offset, limit=limit)

    def original(self, identifier):
        with self.connect() as db:
            row = db.execute('SELECT d.*,r.path FROM documents d JOIN roots r ON d.root_id=r.id WHERE d.id=?', (identifier,)).fetchone()
        if not row:
            raise FileNotFoundError('索引中没有该文件')
        path = safe_path(Path(row['path']), row['relative'])
        limit = MAX_PDF_BYTES if row['kind'] == 'pdf' else MAX_DOCX_BYTES if row['kind'] == 'docx' else MAX_TEXT_BYTES
        with path.open('rb') as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('原文超过大小上限，请更新索引')
        if not row['digest'] or hashlib.sha256(data).hexdigest() != row['digest']:
            raise ValueError('原文件已变化或未成功读取，请先更新索引')
        return row['name'], row['kind'], data
