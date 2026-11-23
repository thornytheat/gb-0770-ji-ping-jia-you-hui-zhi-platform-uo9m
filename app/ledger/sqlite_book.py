import sqlite3
from contextlib import contextmanager
from pathlib import Path


class ShiftBook:
    def __init__(self, db_file):
        self.path = Path(db_file)
        self.path.parent.mkdir(exist_ok=True,parents=True)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS shifts (digest TEXT PRIMARY KEY, manifest TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS stage_rows (digest TEXT NOT NULL REFERENCES shifts(digest), phase TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(digest,phase))')
            self._signatures(db)

    @staticmethod
    def _signatures(db):
        """签发记录按批次和分册归属记账：整班一份，各航司各一份，重签同份不新增行。"""
        columns = {row[1] for row in db.execute('PRAGMA table_info(signatures)')}
        legacy = columns=={'digest','checksum'}
        if legacy:
            db.execute('ALTER TABLE signatures RENAME TO signatures_legacy')
        db.execute('CREATE TABLE IF NOT EXISTS signatures (batch TEXT NOT NULL REFERENCES shifts(digest), '
                   'scope TEXT NOT NULL, checksum TEXT NOT NULL, PRIMARY KEY(batch,scope))')
        if legacy:
            db.execute("INSERT INTO signatures (batch,scope,checksum) SELECT digest,'',checksum FROM signatures_legacy")
            db.execute('DROP TABLE signatures_legacy')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path,timeout=12)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()
