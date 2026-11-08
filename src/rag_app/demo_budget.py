"""One operator-controlled acceptance registry, independent of full40 trials.

SQLite serializes claims/reservations across processes. No automatic creation,
reset or resume; an interrupted case remains locked. Filesystem tampering by the
operator and other programs using the key are outside this local guard.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
PROFILE = 'ofox_joint_pairs8'
PROVIDER = 'https://api.ofox.ai/v1'
MODEL = 'openai/gpt-6-luna'
def _account_home():
    # On POSIX use the OS account, not a caller-controlled HOME/session variable.
    import os
    if os.name == 'posix':
        import pwd
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    return Path.home()


DEFAULT_LEDGER = _account_home() / '.local/state/cs5481/ofox-acceptance.sqlite3'
CASE_IDS = ('EXP11', 'EXP30', 'EXP-R07')


class BudgetBlocked(RuntimeError):
    pass


def fingerprint():
    try:
        lock_path = ROOT/'experiments/joint_pairs8/candidate_lock.json'
        manifest_path = ROOT/'experiments/generative40/runtime/runtime_manifest.json'
        lock = json.loads(lock_path.read_bytes())
        manifest = json.loads(manifest_path.read_bytes())
        paths = {ROOT/'app.py', *list((ROOT/'src').rglob('*.py')), lock_path, manifest_path}
        paths.update(ROOT/name for group in ('code_sha256_lf','inputs_sha256_lf') for name in lock[group])
        paths.update(manifest_path.parent/row['path'] for row in manifest['files'])
        return sha256(b''.join(str(p.relative_to(ROOT)).encode()+b'\0'+p.read_bytes() for p in sorted(paths))).hexdigest()
    except (OSError, ValueError, KeyError, TypeError):
        raise BudgetBlocked('Cannot verify application and frozen-input fingerprints.') from None


def questions():
    rows = json.loads((ROOT/'experiments/joint_pairs8/model_inputs40.json').read_bytes())['requests']
    return {r['id']: json.loads(r['messages'][1]['content'])['question'] for r in rows if r['id'] in CASE_IDS}


def _provision_marker(path):
    return path.with_name(path.name + '.provisioning')


def _exists(path):
    # A dangling symlink is not permission to initialize a new campaign.
    return path.exists() or path.is_symlink()


def _flush_file(stream):
    stream.flush()
    os.fsync(stream.fileno())


def _sync_directory(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _provision_commit(db, phase):
    """Separate commit boundaries permit deterministic durability fault tests."""
    db.commit()


def enforce_profile(profile):
    # Check even on cached Streamlit service hits, including terminal sessions.
    try:
        exists = _exists(DEFAULT_LEDGER) or _exists(_provision_marker(DEFAULT_LEDGER))
    except OSError:
        raise BudgetBlocked('Acceptance registry unavailable.') from None
    if exists and profile != PROFILE:
        raise BudgetBlocked('Acceptance registry locks the application to the OfoxAI profile.')


class SessionLedger:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if Path(path).absolute() != self.path:
            raise BudgetBlocked('Use the fixed canonical registry path, without symlink aliases.')

    @classmethod
    def provision(cls, path, approval):
        """Explicit local consent import only. Never called automatically by UI."""
        path = Path(path).resolve()
        required = {'approved', 'statement', 'session_id', 'authorized_registry', 'source_sha256',
                    'provider', 'model', 'profile', 'max_attempts'}
        if (not isinstance(approval, dict) or set(approval) != required
                or approval['approved'] is not True
                or not isinstance(approval['statement'], str) or not approval['statement'].strip()
                or not isinstance(approval['session_id'], str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', approval['session_id'])
                or approval['authorized_registry'] != str(path)
                or approval['source_sha256'] != fingerprint()
                or (approval['provider'], approval['model'], approval['profile']) != (PROVIDER, MODEL, PROFILE)
                or type(approval['max_attempts']) is not int or approval['max_attempts'] != 6):
            raise BudgetBlocked('Explicit approval must bind the canonical registry and current sources.')
        approved_fingerprint = approval['source_sha256']
        ledger = cls(path)  # construct before releasing the final readiness fence
        marker = _provision_marker(path)
        db = None
        try:
            if _exists(path) or _exists(marker):
                raise BudgetBlocked('Registry or incomplete provisioning already exists; no reset.')
            path.parent.mkdir(parents=True, exist_ok=True)
            # This exclusive fence survives every failure/interruption before
            # final release. Even state=active is unusable while it exists.
            with marker.open('xb') as stream:
                stream.write(b'Provisioning incomplete; do not delete or retry.\n')
                _flush_file(stream)
            _sync_directory(path.parent)
            with path.open('xb') as stream:
                _flush_file(stream)
            if fingerprint() != approved_fingerprint:
                raise BudgetBlocked('Approved sources changed before persistence.')
            db = sqlite3.connect(path)
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''
                    CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT, fingerprint TEXT, consent_hash TEXT, session_id TEXT, registry TEXT);
                    CREATE TABLE cases (id TEXT PRIMARY KEY, token TEXT UNIQUE, state TEXT);
                    CREATE TABLE attempts (ordinal INTEGER PRIMARY KEY, case_id TEXT, stage TEXT, state TEXT, created TEXT, usage TEXT, UNIQUE(case_id,stage));
                    CREATE TABLE results (case_id TEXT PRIMARY KEY, result TEXT);
                ''')
            consent = sha256(json.dumps(approval, sort_keys=True).encode()).hexdigest()
            # Persist the approved value, never a newly observed replacement.
            db.execute('INSERT INTO meta VALUES(1,?,?,?,?,?)',
                       ('initializing', approved_fingerprint, consent, approval['session_id'], str(path)))
            _provision_commit(db, 'initialize')
            _sync_directory(path.parent)
            if fingerprint() != approved_fingerprint:
                raise BudgetBlocked('Approved sources changed before activation.')
            db.execute("UPDATE meta SET state='active' WHERE id=1")
            _provision_commit(db, 'activate')
            db.close()
            db = None
            if fingerprint() != approved_fingerprint:
                raise BudgetBlocked('Approved sources changed during activation.')
            # Last fallible operation / successful activation point. Do not add
            # fsync or other I/O afterward: loss of this unlink on power failure
            # makes the fence reappear and blocks execution (safe unavailability).
            marker.unlink()
            return ledger
        except (OSError, sqlite3.Error, BudgetBlocked):
            # Never remove the fence or retry a partial initialization.
            raise BudgetBlocked('Provisioning failed or incomplete; execution is blocked. Do not reset/retry.') from None
        finally:
            if db is not None:
                db.close()

    @contextmanager
    def transaction(self):
        db = None
        try:
            if _exists(_provision_marker(self.path)):
                raise BudgetBlocked('Provisioning did not complete; no activation or resume.')
            db = sqlite3.connect(self.path.as_uri()+'?mode=rw', uri=True, timeout=2)
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            if _exists(_provision_marker(self.path)):
                raise BudgetBlocked('Provisioning fence blocks execution.')
            if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
                raise BudgetBlocked('Registry integrity check failed.')
            row = db.execute('SELECT state,fingerprint,registry FROM meta WHERE id=1').fetchone()
            if not row or row[1] != fingerprint() or row[2] != str(self.path):
                raise BudgetBlocked('Acceptance source binding differs.')
            yield db
            db.commit()
        except (OSError, sqlite3.Error):
            raise BudgetBlocked('Registry read/write failed; dispatch is blocked.') from None
        finally:
            if db is not None:
                db.close()

    def check(self):
        with self.transaction() as db:
            if db.execute('SELECT state FROM meta').fetchone()[0] != 'active':
                raise BudgetBlocked('Acceptance session is stopped or complete.')

    def begin(self, question):
        mapping = questions()
        case = next((k for k, v in mapping.items() if v == question), None)
        if case is None:
            raise BudgetBlocked('Only the three exact frozen questions are permitted.')
        with self.transaction() as db:
            if db.execute('SELECT state FROM meta').fetchone()[0] != 'active':
                raise BudgetBlocked('Session stopped or complete.')
            rows = db.execute('SELECT id,state FROM cases').fetchall()
            if any(state != 'done' for _, state in rows) or case in dict(rows):
                raise BudgetBlocked('Duplicate, concurrent or interrupted submission; no resume.')
            if case != CASE_IDS[len(rows)]:
                raise BudgetBlocked('Acceptance case order differs.')
            token = uuid4().hex
            db.execute('INSERT INTO cases VALUES(?,?,?)', (case, token, 'running'))
        return case, token

    def reserve(self, claim, stage):
        with self.transaction() as db:
            count = db.execute('SELECT count(*) FROM attempts').fetchone()[0]
            if count >= 6:
                raise BudgetBlocked('Six provider attempts exhausted.')
            if db.execute('SELECT state FROM meta').fetchone()[0] != 'active':
                raise BudgetBlocked('Session stopped.')
            if db.execute('SELECT token,state FROM cases WHERE id=?', (claim[0],)).fetchone() != (claim[1], 'running'):
                raise BudgetBlocked('Invalid case claim.')
            prior = db.execute('SELECT stage,state FROM attempts WHERE case_id=? ORDER BY ordinal', (claim[0],)).fetchall()
            if (stage == 'selection' and prior) or (stage == 'generation' and prior != [('selection','ok')]) or stage not in {'selection','generation'}:
                raise BudgetBlocked('Duplicate/unexpected stage or uncertain previous attempt.')
            ordinal = count + 1
            db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?)',
                       (ordinal, claim[0], stage, 'reserved', datetime.now(timezone.utc).isoformat(), None))
        return ordinal

    def record(self, ordinal, ok, usage=None):
        # Only nonnegative integer usage counters; no headers/body/credential fields.
        safe = {k: v for k, v in (usage or {}).items() if k in {'prompt_tokens','completion_tokens','total_tokens'} and type(v) is int and v >= 0} if isinstance(usage, dict) else {}
        with self.transaction() as db:
            changed = db.execute('UPDATE attempts SET state=?,usage=? WHERE ordinal=? AND state=?',
                ('ok' if ok else 'error', json.dumps(safe), ordinal, 'reserved')).rowcount
            if changed != 1:
                raise BudgetBlocked('Attempt audit mismatch.')
            if not ok:
                db.execute("UPDATE meta SET state='stopped'")

    def finish(self, claim, status, result=None):
        with self.transaction() as db:
            rows = db.execute('SELECT stage,state FROM attempts WHERE case_id=? ORDER BY ordinal', (claim[0],)).fetchall()
            expected = [('selection','ok')] if claim[0] == 'EXP-R07' else [('selection','ok'),('generation','ok')]
            wanted = 'insufficient_evidence' if claim[0] == 'EXP-R07' else 'answered'
            if db.execute('SELECT token,state FROM cases WHERE id=?', (claim[0],)).fetchone() != (claim[1], 'running'):
                raise BudgetBlocked('Case completion mismatch.')
            db.execute("UPDATE cases SET state='done' WHERE id=?", (claim[0],))
            if result is not None:
                fields = {'status','answer','citations','claims','retrieved','error','model','usage','elapsed_seconds',
                          'usage_completeness','provider_attempts','demo_profile','experiment_origin'}
                safe_result = {k:v for k,v in result.items() if k in fields}
                db.execute('INSERT INTO results VALUES(?,?)', (claim[0],json.dumps(safe_result,ensure_ascii=False,allow_nan=False)))
            if rows != expected or status != wanted:
                db.execute("UPDATE meta SET state='stopped'")
            elif db.execute('SELECT count(*) FROM cases').fetchone()[0] == 3:
                db.execute("UPDATE meta SET state='complete'")

    def snapshot(self):
        with self.transaction() as db:
            return {'state': db.execute('SELECT state FROM meta').fetchone()[0],
                    'attempts': [{'ordinal': a, 'case_id': b, 'stage': c, 'state': d, 'created_at_utc': e,
                                  'usage': json.loads(f) if f else None}
                                 for a,b,c,d,e,f in db.execute('SELECT * FROM attempts ORDER BY ordinal')]}

    def first_result(self, case_id):
        with self.transaction() as db:
            row = db.execute('SELECT result FROM results WHERE case_id=?',(case_id,)).fetchone()
            return json.loads(row[0]) if row else None
