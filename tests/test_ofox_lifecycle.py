"""Cleanup and cancellation regressions; synthetic stores and transports only."""
import asyncio
import json
import sqlite3

import httpx
import pytest

from rag_app import demo, demo_budget as b
from rag_app.llm import LLMError
from rag_app.ofox_demo import OfoxChatClient
from test_ofox_demo import setup

PRIVATE = 'SYNTHETIC_PRIVATE_CLEANUP'


def make_client(setup, factory=None):
    service, ledger, cases, _, _, _ = setup
    claim = service.ledger.begin(cases['EXP11']['question'])
    client = OfoxChatClient(service.settings, service.ledger, claim, factory or service.factory)
    demo._load_experiment()
    from selection_adapter import messages_for_selection
    messages = messages_for_selection(cases['EXP11']['question'], cases['EXP11']['evidence'])
    return client, ledger, cases, messages


def assert_blocked_and_private(ledger, cases, diagnostics, count=1):
    assert len(ledger.snapshot()['attempts']) == count
    with pytest.raises(b.BudgetBlocked): ledger.begin(cases['EXP11']['question'])
    with pytest.raises(b.BudgetBlocked): ledger.begin(cases['EXP30']['question'])
    raw = json.dumps(diagnostics) + ledger.path.read_bytes().decode(errors='ignore')
    assert PRIVATE not in raw and 'SYNTHETIC_OFFLINE_ONLY' not in raw
    assert 'Authorization' not in raw and 'Bearer ' not in raw


@pytest.mark.parametrize('status', [200, 403])
def test_response_then_cleanup_failure_preserves_both_durable_observations(setup, status):
    service, ledger, cases, calls, _, _ = setup
    original = service.factory()
    closed = []
    class ClosingFailure(httpx.MockTransport):
        async def aclose(self):
            closed.append(1)
            raise httpx.ReadError(PRIVATE)
    def respond(request):
        if status == 403:
            calls.append('selection')
            return httpx.Response(403, json={'error': {'message': PRIVATE}})
        return original.handler(request)
    service.factory = lambda: ClosingFailure(respond)
    result = service.answer_question(cases['EXP11']['question'])
    assert result['status'] == 'llm_error' and not result['answer']
    diagnostics = ledger.diagnostics()
    assert result['diagnostics'] == diagnostics == ledger.first_result('EXP11')['diagnostics']
    response, cleanup = diagnostics
    assert response['category'] == ('ok' if status == 200 else 'http_error')
    assert response['http_status'] == cleanup['http_status'] == status
    assert cleanup['category'] == 'network_failure' and cleanup['failure_stage'] == 'cleanup'
    assert response['attempt_ordinal'] == cleanup['attempt_ordinal'] == 1
    assert ledger.snapshot()['attempts'][0]['state'] == ('ok' if status == 200 else 'error')
    assert ledger.snapshot()['state'] == 'stopped'
    assert calls == ['selection'] and closed == [1]
    # The already committed response record remains unchanged.
    with sqlite3.connect(ledger.path) as db:
        assert json.loads(db.execute('SELECT record FROM attempt_diagnostics_v1').fetchone()[0]) == response
    assert_blocked_and_private(ledger, cases, diagnostics)


def test_cleanup_does_not_replace_original_http_exception(setup):
    class ClosingFailure(httpx.MockTransport):
        async def aclose(self): raise httpx.ReadError(PRIVATE)
    client, ledger, cases, messages = make_client(setup,
        lambda: ClosingFailure(lambda r: httpx.Response(401)))
    with pytest.raises(LLMError, match='HTTP, model or response-format'):
        asyncio.run(client._request(messages))
    assert [d['category'] for d in ledger.diagnostics()] == ['http_error', 'network_failure']
    assert_blocked_and_private(ledger, cases, client.diagnostics)


@pytest.mark.parametrize('during', ['transport', 'body'])
def test_ordinary_task_cancellation_propagates_and_keeps_consumed_attempt(setup, during):
    async def scenario():
        ready = asyncio.Event()
        class WaitingBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                ready.set()
                await asyncio.Future()
                yield b''
        async def respond(request):
            if during == 'body': return httpx.Response(200, stream=WaitingBody())
            ready.set()
            await asyncio.Future()
        client, ledger, cases, messages = make_client(setup, lambda: httpx.MockTransport(respond))
        task = asyncio.create_task(client._request(messages))
        await ready.wait()
        task.cancel(PRIVATE)
        with pytest.raises(asyncio.CancelledError) as error: await task
        assert error.value.args == (PRIVATE,)
        d = ledger.diagnostics()[0]
        assert d['category'] == 'cancelled'
        assert d['failure_stage'] == ('transport' if during == 'transport' else 'response_body')
        assert d['http_response_received'] is (during == 'body')
        assert ledger.snapshot()['attempts'][0]['state'] == 'error'
        assert ledger.snapshot()['state'] == 'stopped'
        assert_blocked_and_private(ledger, cases, client.diagnostics)
    asyncio.run(scenario())


def test_cancellation_before_reservation_does_not_invent_dispatch(setup, monkeypatch):
    client, ledger, cases, messages = make_client(setup, lambda: pytest.fail('No transport allowed'))
    cancellation = asyncio.CancelledError(PRIVATE)
    def cancel(*args): raise cancellation
    monkeypatch.setattr(client.ledger, 'reserve', cancel)
    with pytest.raises(asyncio.CancelledError) as error:
        asyncio.run(client._request(messages))
    assert error.value is cancellation
    d = client.diagnostics[0]
    assert d['category'] == 'cancelled' and d['attempt_ordinal'] is None
    assert not d['dispatch_started'] and not d['transport_constructed']
    assert ledger.diagnostics() == [] and ledger.snapshot()['attempts'] == []
    assert_blocked_and_private(ledger, cases, client.diagnostics, count=0)


@pytest.mark.parametrize('request_fails', [False, True])
def test_cancellation_during_cleanup_keeps_original_evidence(setup, request_fails):
    class CancelCleanup(httpx.MockTransport):
        async def aclose(self): raise asyncio.CancelledError(PRIVATE)
    response = httpx.Response(403) if request_fails else httpx.Response(200, json={
        'model': b.MODEL, 'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]})
    client, ledger, cases, messages = make_client(setup, lambda: CancelCleanup(lambda r: response))
    expected = LLMError if request_fails else asyncio.CancelledError
    with pytest.raises(expected): asyncio.run(client._request(messages))
    response_d, cleanup_d = ledger.diagnostics()
    assert response_d['category'] == ('http_error' if request_fails else 'ok')
    assert cleanup_d['category'] == 'cancelled' and cleanup_d['failure_stage'] == 'cleanup'
    assert ledger.snapshot()['state'] == 'stopped'
    assert_blocked_and_private(ledger, cases, client.diagnostics)


def test_actual_application_deadline_during_cleanup_is_timeout(setup):
    from dataclasses import replace
    service, ledger, cases, calls, _, _ = setup
    original = service.factory()
    class SlowCleanup(httpx.MockTransport):
        async def aclose(self): await asyncio.Future()
    service.factory = lambda: SlowCleanup(original.handler)
    service.settings = replace(service.settings, timeout=1)
    result = service.answer_question(cases['EXP11']['question'])
    assert result['status'] == 'llm_error'
    response, cleanup = ledger.diagnostics()
    assert response['category'] == 'ok' and response['http_status'] == 200
    assert cleanup['category'] == 'timeout' and cleanup['failure_stage'] == 'cleanup'
    assert calls == ['selection'] and ledger.snapshot()['state'] == 'stopped'
    assert result['diagnostics'] == ledger.first_result('EXP11')['diagnostics'] == ledger.diagnostics()
    assert_blocked_and_private(ledger, cases, result['diagnostics'])


def test_cleanup_audit_fault_keeps_response_and_blocks_resume(setup):
    service, ledger, cases, _, _, _ = setup
    original = service.factory()
    class ClosingFailure(httpx.MockTransport):
        async def aclose(self): raise httpx.ReadError(PRIVATE)
    service.factory = lambda: ClosingFailure(original.handler)
    with sqlite3.connect(ledger.path) as db:
        db.execute("CREATE TRIGGER fail_cleanup BEFORE INSERT ON cleanup_diagnostics_v1 BEGIN SELECT RAISE(ABORT, 'synthetic fault'); END")
    result = service.answer_question(cases['EXP11']['question'])
    assert result['status'] == 'llm_error'
    assert [d['category'] for d in result['diagnostics']] == ['ok', 'network_failure', 'audit_failure']
    assert len(ledger.diagnostics()) == 1 and ledger.diagnostics()[0]['category'] == 'ok'
    assert ledger.first_result('EXP11')['diagnostics'] == result['diagnostics']
    assert ledger.snapshot()['state'] == 'stopped'
    assert_blocked_and_private(ledger, cases, result['diagnostics'])
