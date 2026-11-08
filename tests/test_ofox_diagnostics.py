"""Synthetic failure diagnostics: no network, real approval or operator ledger."""
import asyncio
from hashlib import sha256
import json
import socket
import sqlite3
import ssl

import httpx
import pytest

from rag_app import demo_budget as b
from rag_app.ofox_diagnostics import Diagnostic, exception_category, sanitize
from test_ofox_demo import setup  # shared synthetic registry/frozen-context fixture

SECRET = 'SYNTHETIC_OFFLINE_ONLY'
PRIVATE = 'RAW_PRIVATE_BODY_OR_PROXY_PASSWORD'


def run_failure(setup, response=None, exc=None, *, factory_error=None):
    service, ledger, cases, calls, _, _ = setup
    def respond(request):
        calls.append('selection')
        if exc:
            raise exc
        return response
    def factory():
        if factory_error:
            raise factory_error
        return httpx.MockTransport(respond)
    service.factory = factory
    result = service.answer_question(cases['EXP11']['question'])
    assert not result['answer'] and not result['citations']
    assert len(ledger.snapshot()['attempts']) == 1
    assert ledger.snapshot()['attempts'][0]['state'] == 'error'
    assert ledger.snapshot()['state'] == 'stopped'
    diagnostic = ledger.diagnostics()[0]
    assert result['diagnostics'] == [diagnostic]
    assert ledger.first_result('EXP11')['diagnostics'] == [diagnostic]
    assert diagnostic['attempt_ordinal'] == 1 and diagnostic['stage'] == 'selection'
    assert diagnostic['started_at_utc'] <= diagnostic['finished_at_utc']
    assert len(json.dumps(diagnostic)) < 1600
    raw = json.dumps(result) + ledger.path.read_bytes().decode(errors='ignore')
    for value in (SECRET, PRIVATE, 'Authorization', 'Bearer '):
        assert value not in raw
    before = len(calls)
    assert service.answer_question(cases['EXP30']['question'])['status'] == 'acceptance_blocked'
    assert len(calls) == before
    return diagnostic


@pytest.mark.parametrize('status', [400, 401, 403, 429, 503])
def test_http_errors_persist_safe_fields(setup, status):
    rid = 'req_synthetic12345'
    response = httpx.Response(status, headers={'x-request-id': rid, 'Authorization': SECRET},
        json={'error': {'type': 'invalid_request_error', 'code': 'unsupported_parameter', 'message': PRIVATE}})
    d = run_failure(setup, response)
    assert d['category'] == 'http_error' and d['http_status'] == status
    assert d['http_response_received'] and d['body_read_complete']
    assert d['request_id_sha256'] == sha256(rid.encode()).hexdigest()
    assert rid not in json.dumps(d)
    assert d['provider_error_type'] == 'invalid_request_error'
    assert d['provider_error_code'] == 'unsupported_parameter'


@pytest.mark.parametrize('body', [None, [], {'error': []}, {'error': {'type': {}, 'code': []}},
    {'error': {'type': PRIVATE, 'code': SECRET}}, {'error': SECRET}])
def test_malformed_error_bodies_and_secret_headers(setup, body):
    response = httpx.Response(403, json=body, headers={'x-request-id': 'req_' + SECRET})
    d = run_failure(setup, response)
    assert d['category'] == 'http_error' and d['http_status'] == 403
    assert d['provider_error_type'] is None and d['provider_error_code'] is None
    assert d['request_id_sha256'] is None


def test_non_json_http_error(setup):
    d = run_failure(setup, httpx.Response(502, text=PRIVATE))
    assert d['category'] == 'http_error' and d['http_status'] == 502


def caused(exc, cause):
    exc.__cause__ = cause
    return exc


@pytest.mark.parametrize('kind,category', [
    ('dns', 'dns_failure'), ('tls', 'tls_failure'), ('timeout', 'timeout'),
    ('connect', 'connect_failure'), ('reset', 'network_failure'), ('proxy', 'proxy_failure')])
def test_network_failure_classes(setup, kind, category):
    exceptions = {
        'dns': caused(httpx.ConnectError(PRIVATE), socket.gaierror(8, PRIVATE)),
        'tls': caused(httpx.ConnectError(PRIVATE), ssl.SSLCertVerificationError(PRIVATE)),
        'timeout': httpx.ConnectTimeout(PRIVATE), 'connect': httpx.ConnectError(PRIVATE),
        'reset': caused(httpx.ReadError(PRIVATE), ConnectionResetError(PRIVATE)),
        'proxy': httpx.ProxyError(PRIVATE),
    }
    d = run_failure(setup, exc=exceptions[kind])
    assert d['category'] == category and d['failure_stage'] == 'transport'
    assert d['transport_constructed'] and d['dispatch_started']
    assert not d['http_response_received'] and d['http_status'] is None


def test_factory_failure_is_reserved_before_transport(setup):
    d = run_failure(setup, factory_error=httpx.ConnectError(PRIVATE))
    assert d['failure_stage'] == 'transport_factory'
    assert not d['transport_constructed'] and not d['dispatch_started']


@pytest.mark.parametrize('value,category', [
    ('invalid_json', 'invalid_json'), ('wrong_model', 'model_mismatch'),
    ('schema', 'invalid_schema'), ('length', 'non_stop_finish'),
    ('finish_object', 'non_stop_finish'), ('empty', 'invalid_content')])
def test_response_rejections(setup, value, category):
    data = {'model': b.MODEL, 'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}
    if value == 'wrong_model': data['model'] = PRIVATE
    if value == 'schema': data['choices'] = [{'message': PRIVATE}]
    if value == 'length': data['choices'][0]['finish_reason'] = 'length'
    if value == 'finish_object': data['choices'][0]['finish_reason'] = {'secret': SECRET}
    if value == 'empty': data['choices'][0]['message']['content'] = ''
    response = httpx.Response(200, text=PRIVATE) if value == 'invalid_json' else httpx.Response(200, json=data)
    d = run_failure(setup, response)
    assert d['category'] == category and d['http_status'] == 200
    if value == 'finish_object': assert d['finish_reason'] == 'other'


def test_timeout_after_headers_retains_response_status(setup):
    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise httpx.ReadTimeout(PRIVATE)
            yield b''
    d = run_failure(setup, httpx.Response(200, stream=Broken()))
    assert d['category'] == 'timeout' and d['failure_stage'] == 'response_body'
    assert d['http_response_received'] and not d['body_read_complete']


def test_two_success_stages_persist_separate_diagnostics(setup):
    service, ledger, cases, _, _, _ = setup
    result = service.answer_question(cases['EXP11']['question'])
    assert result['status'] == 'answered'
    assert [d['stage'] for d in ledger.diagnostics()] == ['selection', 'generation']
    assert all(d['category'] == 'ok' for d in result['diagnostics'])
    assert result['diagnostics'] == ledger.diagnostics() == ledger.first_result('EXP11')['diagnostics']
    assert [d['attempt_ordinal'] for d in result['diagnostics']] == [1, 2]


def test_reservation_failure_never_constructs_transport(setup, monkeypatch):
    service, ledger, cases, _, _, _ = setup
    monkeypatch.setattr(service.ledger, 'reserve', lambda *a: (_ for _ in ()).throw(b.BudgetBlocked(PRIVATE)))
    service.factory = lambda: pytest.fail('No construction allowed')
    result = service.answer_question(cases['EXP11']['question'])
    assert result['diagnostics'][0]['category'] == 'budget_failure'
    assert result['diagnostics'][0]['attempt_ordinal'] is None
    assert ledger.snapshot()['attempts'] == []
    assert PRIVATE not in json.dumps(result)


def test_audit_insert_failure_rolls_back_and_preserves_reservation(setup):
    service, ledger, cases, _, _, _ = setup
    # Synthetic store only: fail diagnostic persistence after network response.
    with sqlite3.connect(ledger.path) as db:
        db.execute("CREATE TRIGGER fail_diag BEFORE INSERT ON attempt_diagnostics_v1 BEGIN SELECT RAISE(ABORT, 'synthetic disk fault'); END")
    result = service.answer_question(cases['EXP11']['question'])
    assert result['status'] in {'llm_error', 'acceptance_blocked'}
    assert result['diagnostics'][0]['category'] == 'audit_failure'
    assert len(ledger.snapshot()['attempts']) == 1
    assert ledger.snapshot()['attempts'][0]['state'] == 'reserved'
    assert ledger.diagnostics() == []
    # Uncertain reserved attempt still consumes budget and prevents replay.
    with pytest.raises(b.BudgetBlocked): ledger.begin(cases['EXP11']['question'])
    with pytest.raises(b.BudgetBlocked): ledger.begin(cases['EXP30']['question'])


def test_result_audit_failure_returns_safe_memory_diagnostic(setup, monkeypatch):
    service, ledger, cases, _, _, _ = setup
    monkeypatch.setattr(service.ledger, 'finish', lambda *a: (_ for _ in ()).throw(b.BudgetBlocked(PRIVATE)))
    result = service.answer_question(cases['EXP11']['question'])
    assert result['status'] == 'acceptance_blocked'
    assert result['diagnostics'][-1]['category'] == 'audit_failure'
    assert len(ledger.diagnostics()) == 2
    assert PRIVATE not in json.dumps(result)
    with pytest.raises(b.BudgetBlocked): ledger.begin(cases['EXP30']['question'])


def test_sanitizer_rebuilds_fixed_bounded_schema():
    d = sanitize({'schema_version': 99, 'category': SECRET, 'failure_stage': {},
        'http_status': True, 'attempt_ordinal': 7, 'stage': PRIVATE,
        'provider_error_code': [SECRET], 'request_id_sha256': SECRET,
        'raw_body': PRIVATE, 'headers': {'Authorization': SECRET},
        'started_at_utc': 'Z' * 10000, 'finished_at_utc': []})
    assert d['category'] == 'unknown_failure' and d['attempt_ordinal'] is None
    assert SECRET not in json.dumps(d) and PRIVATE not in json.dumps(d)
    assert len(json.dumps(d)) < 1000
    assert exception_category(asyncio.CancelledError()) == 'cancelled'


def test_persistence_sanitizes_again_and_does_not_overwrite_first_record(setup):
    _, ledger, cases, _, _, _ = setup
    claim = ledger.begin(cases['EXP11']['question']); ordinal = ledger.reserve(claim, 'selection')
    ledger.record(ordinal, False, diagnostic={'category': 'http_error', 'raw_body': PRIVATE, 'attempt_ordinal': 6})
    d = ledger.diagnostics()[0]
    assert d['attempt_ordinal'] == ordinal
    assert PRIVATE not in json.dumps(d)
    with pytest.raises(b.BudgetBlocked): ledger.record(ordinal, True, diagnostic={'category': 'ok'})
    assert ledger.diagnostics() == [d]


def test_total_timeout_persists_consumed_attempt(setup):
    from dataclasses import replace
    service, ledger, cases, calls, _, _ = setup
    async def slow(request):
        calls.append('selection')
        await asyncio.sleep(3600)  # cancelled by the existing total request timeout
    service.factory = lambda: httpx.MockTransport(slow)
    service.settings = replace(service.settings, timeout=1)
    result = service.answer_question(cases['EXP11']['question'])
    assert result['status'] == 'llm_error'
    assert ledger.diagnostics()[0]['category'] == 'timeout'
    assert len(calls) == 1 and ledger.snapshot()['state'] == 'stopped'
    assert ledger.snapshot()['attempts'][0]['state'] == 'error'


def test_missing_usage_remains_unknown_not_zero_billing(setup):
    service, ledger, cases, _, _, _ = setup
    original = service.factory
    inner = original()
    async def without_usage(request):
        response = await inner.handle_async_request(request)
        data = response.json()
        data.pop('usage', None)
        return httpx.Response(200, json=data)
    service.factory = lambda: httpx.MockTransport(without_usage)
    result = service.answer_question(cases['EXP11']['question'])
    assert result['status'] == 'answered'
    assert result['usage'] == {} and result['usage_completeness'] == 'partial_or_unknown'
    assert all(d['category'] == 'ok' for d in ledger.diagnostics())


def test_no_schema_migration_on_read(setup):
    _, ledger, cases, _, _, _ = setup
    # Synthetic legacy shape; production never opens a legacy source-bound store.
    with sqlite3.connect(ledger.path) as db:
        db.execute('DROP TABLE attempt_diagnostics_v1')
    with pytest.raises(b.BudgetBlocked): ledger.diagnostics()
    with sqlite3.connect(ledger.path) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='attempt_diagnostics_v1'").fetchall()
