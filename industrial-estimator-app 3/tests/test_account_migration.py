"""Verify adding account features does not damage existing v0.8.3 data."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


def test_in_place_upgrade_preserves_legacy_users_and_projects():
    with tempfile.TemporaryDirectory() as tmp:
        db_path=Path(tmp)/'legacy.db'
        with sqlite3.connect(db_path) as con:
            con.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(60) NOT NULL UNIQUE, display_name VARCHAR(100) NOT NULL, password_hash VARCHAR(300) NOT NULL, role VARCHAR(40) NOT NULL, active BOOLEAN)')
            con.execute("INSERT INTO users(id,username,display_name,password_hash,role,active) VALUES(1,'existing','Existing User','legacyhash','admin',1)")
            con.execute('CREATE TABLE legacy_notes (id INTEGER PRIMARY KEY, note TEXT)')
            con.execute("INSERT INTO legacy_notes VALUES(1,'keep existing projects and documents intact')")
            con.commit()
        env={**os.environ, 'DATABASE_URL':'sqlite:///'+db_path.as_posix(),
             'PRIVATE_DIR':str(Path(tmp)/'private'), 'APP_SECRET':'TEST_SECRET_NOT_FOR_PRODUCTION_012345678901234'}
        result=subprocess.run([sys.executable, '-c',
               'from backend.app import SessionLocal,User; from sqlalchemy import select; db=SessionLocal(); u=db.scalar(select(User).where(User.username=="existing")); assert u and u.email=="" and u.phone=="" and u.auth_version==0 and not u.must_change_password; print("UPGRADE_OK")'],
               cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=40)
        assert result.returncode==0, result.stderr
        assert 'UPGRADE_OK' in result.stdout
        with sqlite3.connect(db_path) as con:
            assert con.execute('SELECT note FROM legacy_notes').fetchone()[0]=='keep existing projects and documents intact'
            assert con.execute('SELECT username FROM users WHERE id=1').fetchone()[0]=='existing'
            assert con.execute("SELECT name FROM sqlite_master WHERE name='account_recovery_codes'").fetchone() is not None
            cols={c[1] for c in con.execute('PRAGMA table_info(users)')}
            assert {'email','phone','auth_version','must_change_password'}.issubset(cols)
