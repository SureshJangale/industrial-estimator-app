"""SQLite+private-file snapshot for local deployments. Stop writes or run at a quiet time.
PostgreSQL deployments need pg_dump and storage backups; see README.
"""
import os
import sqlite3
import tempfile
from datetime import datetime,timezone
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from .app import PRIVATE_DIR, ROOT, DB_URL

def main():
    if not DB_URL.startswith('sqlite:///'):
        raise SystemExit('This backup command supports SQLite only; for PostgreSQL use pg_dump + uploads archive.')
    source=Path(DB_URL.removeprefix('sqlite:///'))
    if not source.exists():raise SystemExit('SQLite database not found')
    target=ROOT/'backups';target.mkdir(exist_ok=True)
    path=target/('industriquote-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.zip')
    with tempfile.TemporaryDirectory() as t:
        tmpdb=Path(t)/'estimator.db'
        with sqlite3.connect(source) as src,sqlite3.connect(tmpdb) as dst:
            src.backup(dst)
        with ZipFile(path,'w',ZIP_DEFLATED) as out:
            out.write(tmpdb,'estimator.db')
            for f in PRIVATE_DIR.glob('*'):
                if f.is_file() and not f.is_symlink():
                    out.write(f,'files/'+f.name)
    print('Backup:',path)
    print('Test restore on a separate machine; store a copy outside the server.')

if __name__=='__main__':main()
