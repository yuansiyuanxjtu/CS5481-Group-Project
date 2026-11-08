"""Provisioning safety boundaries; all consent and state are synthetic test data."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import patch

import pytest

from rag_app import demo_budget as b


def consent(path):
    return dict(approved=True, statement='SYNTHETIC PROVISIONING TEST ONLY', session_id='synthetic',
                authorized_registry=str(path.resolve()), source_sha256=b.fingerprint(),
                provider=b.PROVIDER, model=b.MODEL, profile=b.PROFILE, max_attempts=6)


def assert_unusable_after_reopen(path):
    with pytest.raises(b.BudgetBlocked):
        b.SessionLedger(path).check()
    with pytest.raises(b.BudgetBlocked):
        b.SessionLedger(path).begin(b.questions()['EXP11'])
    code = "from rag_app.demo_budget import SessionLedger,BudgetBlocked; import sys\ntry:SessionLedger(sys.argv[1]).check()\nexcept BudgetBlocked:print('blocked')\nelse:raise AssertionError('Failed provisioning reopened active')"
    child = subprocess.run([sys.executable, '-c', code, str(path)], capture_output=True, text=True)
    assert child.returncode == 0 and child.stdout.strip() == 'blocked', child.stderr


@pytest.mark.parametrize('phase', ['before_persistence', 'before_activation', 'after_activation_commit'])
def test_source_drift_does_not_replace_approved_fingerprint(tmp_path, phase):
    path = tmp_path/'registry'
    approval = consent(path)
    expected = approval['source_sha256']
    values = {'before_persistence':[expected, 'changed'],
              'before_activation':[expected, expected, 'changed'],
              'after_activation_commit':[expected, expected, expected, 'changed']}[phase]
    with patch.object(b, 'fingerprint', side_effect=values):
        with pytest.raises(b.BudgetBlocked):
            b.SessionLedger.provision(path, approval)
    # Even if the source later returns to the approved version, the failed
    # operation cannot become active by reopening or changing session labels.
    assert_unusable_after_reopen(path)
    if phase != 'before_persistence':
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT fingerprint FROM meta').fetchone() == (expected,)
    with pytest.raises(b.BudgetBlocked):
        b.SessionLedger.provision(path, {**approval, 'session_id':'renamed'})


@pytest.mark.parametrize('phase', ['initialize', 'activate'])
@pytest.mark.parametrize('when', ['before', 'after'])
def test_commit_failures_remain_blocked_after_restart(tmp_path, monkeypatch, phase, when):
    path = tmp_path/'registry'
    original = b._provision_commit
    def fail(db, current):
        if current == phase and when == 'before':
            raise sqlite3.OperationalError('SYNTHETIC_PRE_COMMIT_FAILURE')
        original(db, current)
        if current == phase and when == 'after':
            raise sqlite3.OperationalError('SYNTHETIC_POST_COMMIT_FAILURE')
    monkeypatch.setattr(b, '_provision_commit', fail)
    with pytest.raises(b.BudgetBlocked):
        b.SessionLedger.provision(path, consent(path))
    assert_unusable_after_reopen(path)


@pytest.mark.parametrize('ordinal', [1, 2, 3, 4])
def test_each_provisioning_fsync_boundary_fails_closed(tmp_path, monkeypatch, ordinal):
    path = tmp_path/'registry'
    original = os.fsync
    count = 0
    def fail(fd):
        nonlocal count
        count += 1
        if count == ordinal:
            raise OSError('SYNTHETIC_FSYNC_FAILURE')
        return original(fd)
    monkeypatch.setattr(os, 'fsync', fail)
    with pytest.raises(b.BudgetBlocked):
        b.SessionLedger.provision(path, consent(path))
    assert count == ordinal
    assert_unusable_after_reopen(path)


@pytest.mark.parametrize('which', ['marker', 'database'])
def test_file_flush_failure_leaves_a_readiness_fence(tmp_path, monkeypatch, which):
    path = tmp_path/'registry'
    target = b._provision_marker(path) if which == 'marker' else path
    original_open = Path.open
    class FlushFault:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def flush(self):
            raise OSError('SYNTHETIC_FLUSH_FAILURE')
    @contextmanager
    def open_with_fault(self, *args, **kwargs):
        with original_open(self, *args, **kwargs) as stream:
            yield FlushFault(stream) if self == target and args and args[0] == 'xb' else stream
    monkeypatch.setattr(Path, 'open', open_with_fault)
    with pytest.raises(b.BudgetBlocked):
        b.SessionLedger.provision(path, consent(path))
    assert_unusable_after_reopen(path)


def test_final_activation_release_failure_is_not_usable(tmp_path, monkeypatch):
    path = tmp_path/'registry'
    marker = b._provision_marker(path)
    original_unlink = Path.unlink
    def fail(self, *args, **kwargs):
        if self == marker:
            raise OSError('SYNTHETIC_RELEASE_FAILURE')
        return original_unlink(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', fail)
    with pytest.raises(b.BudgetBlocked):
        b.SessionLedger.provision(path, consent(path))
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT state FROM meta').fetchone() == ('active',)
    # SQL state alone is insufficient: the durable fence remains authoritative.
    assert_unusable_after_reopen(path)


def test_incomplete_marker_blocks_other_profiles_without_creating_a_database(tmp_path, monkeypatch):
    path = tmp_path/'registry'
    b._provision_marker(path).write_text('incomplete')
    monkeypatch.setattr(b, 'DEFAULT_LEDGER', path)
    assert_unusable_after_reopen(path)
    assert not path.exists()
    for profile in ['baseline', 'joint_pairs8']:
        with pytest.raises(b.BudgetBlocked):
            b.enforce_profile(profile)
    with pytest.raises(b.BudgetBlocked):
        b.SessionLedger.provision(path, consent(path))


@pytest.mark.parametrize('phase', ['initialize', 'activate'])
def test_process_interruption_during_provisioning_remains_blocked(tmp_path, phase):
    path = tmp_path/'registry'
    record = consent(path)
    code = """import json,sys,os,signal
from rag_app import demo_budget as b
original=b._provision_commit
def interrupt(db,phase):
    original(db,phase)
    if phase==sys.argv[3]:os.kill(os.getpid(),signal.SIGKILL)
b._provision_commit=interrupt
b.SessionLedger.provision(sys.argv[1],json.loads(sys.argv[2]))
"""
    child = subprocess.run([sys.executable, '-c', code, str(path), json.dumps(record), phase], capture_output=True)
    assert child.returncode == -9
    assert_unusable_after_reopen(path)


def test_concurrent_provisioners_cannot_replace_the_winner(tmp_path):
    path = tmp_path/'registry'; record = consent(path)
    code = """from rag_app import demo_budget as b
import json,sys
try:b.SessionLedger.provision(sys.argv[1],json.loads(sys.argv[2]));print('created')
except b.BudgetBlocked:print('blocked')
"""
    children = [subprocess.Popen([sys.executable, '-c', code, str(path), json.dumps(record)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    outputs = [c.communicate() for c in children]
    assert all(c.returncode == 0 for c in children), outputs
    assert [stdout.strip() for stdout,_ in outputs].count('created') == 1
    ledger = b.SessionLedger(path); ledger.check()
    assert ledger.snapshot()['attempts'] == []
    assert not b._provision_marker(path).exists()


def test_success_persists_the_exact_approved_value_and_reopens(tmp_path):
    path = tmp_path/'registry'; record = consent(path)
    ledger = b.SessionLedger.provision(path, record)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT state,fingerprint FROM meta').fetchone() == ('active', record['source_sha256'])
    assert not b._provision_marker(path).exists()
    ledger.check(); b.SessionLedger(path).check()
