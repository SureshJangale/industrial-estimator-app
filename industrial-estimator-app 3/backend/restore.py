"""Restore SQLite backup ONLY while the server is stopped; replacement is explicit."""
import argparse
from pathlib import Path
from zipfile import ZipFile
from .app import PRIVATE_DIR, DB_URL

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('archive',type=Path)
    parser.add_argument('--confirm-overwrite',action='store_true')
    a=parser.parse_args()
    if not a.confirm_overwrite:raise SystemExit('Pass --confirm-overwrite, and stop the server first')
    if not DB_URL.startswith('sqlite:///'):raise SystemExit('This tool restores SQLite only')
    db=Path(DB_URL.removeprefix('sqlite:///'))
    if not a.archive.is_file():raise SystemExit('Backup not found')
    with ZipFile(a.archive) as archive:
        if 'estimator.db' not in archive.namelist():raise SystemExit('Invalid backup: no database')
        for name in archive.namelist():
            if name!='estimator.db' and not (name.startswith('files/') and Path(name).name==name.removeprefix('files/') and name.count('/')==1):
                raise SystemExit(f'Unexpected backup entry {name}')
        db.parent.mkdir(parents=True,exist_ok=True)
        db.write_bytes(archive.read('estimator.db'))
        PRIVATE_DIR.mkdir(parents=True,exist_ok=True)
        for name in archive.namelist():
            if name.startswith('files/'):
                (PRIVATE_DIR/Path(name).name).write_bytes(archive.read(name))
    print('Restored database and private files. Restart server after checking permissions.')

if __name__=='__main__':main()
