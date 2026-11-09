"""v2 authorization security; every prior/successor store is synthetic and temporary."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import sqlite3
from unittest.mock import patch

import httpx
import pytest

from rag_app import demo_budget as b, ofox_probe as p
from rag_app.config import Settings
from test_ofox_demo import approval


@pytest.fixture
def prior(tmp_path, monkeypatch):
    old = tmp_path/'prior.sqlite3'
    ledger = b.SessionLedger.provision(old, approval(old))
    claim = ledger.begin(b.questions()['EXP11'])
    ledger.record(ledger.reserve(claim,'selection'),False)
    monkeypatch.setattr(p,'PRIOR_PATH',old)
    monkeypatch.setattr(p,'PRIOR_SHA256',sha256(old.read_bytes()).hexdigest())
    monkeypatch.setattr(p,'PRIOR_SESSION','synthetic')
    monkeypatch.setattr(p,'PRIOR_SOURCE',b.fingerprint())
    monkeypatch.setattr(p,'PROBE_PATH',tmp_path/'probe.sqlite3')
    return old


def activate():
    consent = p.approval_template();consent['approved']=True
    return p.ProbeLedger.provision(p.PROBE_PATH,consent)


def test_prepare_is_unapproved_and_does_not_create_files(prior):
    info=p.prepare()
    assert info['approval']['approved'] is False
    assert info['approval']['max_attempts']==1
    assert not info['registry_exists'] and not info['fence_exists']
    assert not p.PROBE_PATH.exists()


@pytest.mark.parametrize('field,value',[('approved',False),('max_attempts',6),('statement','old consent'),
    ('session_id','renamed'),('source_sha256','old'),('authorized_registry','another'),
    ('provider','https://other.invalid'),('model','other'),('profile','baseline')])
def test_wrong_approval_no_registry_or_fence(prior,field,value):
    consent=p.approval_template();consent['approved']=True;consent[field]=value
    with pytest.raises(b.BudgetBlocked):p.ProbeLedger.provision(p.PROBE_PATH,consent)
    assert not p.PROBE_PATH.exists() and not b._provision_marker(p.PROBE_PATH).exists()


def test_one_selection_success_no_generation_and_preserved_prior(prior):
    initial=prior.read_bytes();mtime=prior.stat().st_mtime_ns
    activate();calls=[]
    def respond(request):
        calls.append(1)
        payload=json.loads(json.loads(request.content)['messages'][1]['content'])
        plan={'parts':[{'part_id':q['part_id'],'supported':False,'unit_ids':[]} for q in payload['question_parts']]}
        return httpx.Response(200,json={'model':b.MODEL,'usage':{'total_tokens':10,'secret':'SYNTHETIC_PRIVATE'},
            'choices':[{'finish_reason':'stop','message':{'content':json.dumps(plan)}}]})
    result=p.run_once(settings=Settings(api_key='SYNTHETIC_OFFLINE_ONLY'),transport=httpx.MockTransport(respond))
    assert result['status']=='planning_valid'
    assert len(calls)==1
    ledger=p.ProbeLedger(p.PROBE_PATH)
    assert ledger.snapshot()['state']=='stopped' and len(ledger.snapshot()['attempts'])==1
    assert ledger.first_result('EXP11')==result
    with pytest.raises(b.BudgetBlocked):p.run_once(settings=Settings(api_key='synthetic'),transport=httpx.MockTransport(respond))
    assert len(calls)==1 and prior.read_bytes()==initial and prior.stat().st_mtime_ns==mtime
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('mode',['401','timeout','wrong_model','invalid_json'])
def test_failed_attempt_stays_consumed(prior,mode):
    activate();calls=[]
    def respond(r):
        calls.append(1)
        if mode=='timeout':raise httpx.ReadTimeout('SYNTHETIC_PRIVATE')
        if mode=='401':return httpx.Response(401,text='SYNTHETIC_PRIVATE')
        if mode=='invalid_json':return httpx.Response(200,text='SYNTHETIC_PRIVATE')
        return httpx.Response(200,json={'model':'SYNTHETIC_PRIVATE'})
    result=p.run_once(settings=Settings(api_key='synthetic'),transport=httpx.MockTransport(respond))
    assert result['status']=='failed' and len(calls)==1
    ledger=p.ProbeLedger(p.PROBE_PATH)
    assert len(ledger.snapshot()['attempts'])==1 and ledger.snapshot()['state']=='stopped'
    with pytest.raises(b.BudgetBlocked):ledger.begin(b.questions()['EXP11'])
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(result)


def test_generation_other_questions_and_changed_payload_block(prior):
    ledger=activate()
    with pytest.raises(b.BudgetBlocked):ledger.begin(b.questions()['EXP30'])
    claim=ledger.begin(b.questions()['EXP11'])
    with pytest.raises(b.BudgetBlocked):ledger.reserve(claim,'generation')
    with pytest.raises(b.BudgetBlocked):ledger.validate_request(httpx.Request('POST',b.PROVIDER+'/chat/completions',json={}))
    assert ledger.snapshot()['attempts']==[]


def test_concurrency_one_claim_and_one_reservation(prior):
    activate()
    def begin(_):
        try:return p.ProbeLedger(p.PROBE_PATH).begin(b.questions()['EXP11'])
        except b.BudgetBlocked:return None
    with ThreadPoolExecutor(max_workers=6) as pool:claims=list(pool.map(begin,range(6)))
    claim=next(c for c in claims if c)
    assert sum(c is not None for c in claims)==1
    def reserve(_):
        try:return p.ProbeLedger(p.PROBE_PATH).reserve(claim,'selection')
        except b.BudgetBlocked:return None
    with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(reserve,range(6)))
    assert sum(r is not None for r in results)==1
    with pytest.raises(b.BudgetBlocked):p.ProbeLedger(p.PROBE_PATH).check()


def test_prior_drift_blocks_before_credentials(prior,monkeypatch):
    activate()
    prior.write_bytes(prior.read_bytes()+b'drift')  # synthetic fixture only
    monkeypatch.setattr(Settings,'from_env',lambda:pytest.fail('Credential loading forbidden'))
    with pytest.raises(b.BudgetBlocked):p.run_once()


def test_missing_successor_blocks_before_credentials(prior,monkeypatch):
    monkeypatch.setattr(Settings,'from_env',lambda:pytest.fail('Credential loading forbidden'))
    with pytest.raises(b.BudgetBlocked):p.run_once()
    assert not p.PROBE_PATH.exists()


def test_alias_and_reprovision_block(prior,tmp_path):
    consent=p.approval_template();consent['approved']=True
    ledger=activate()
    with pytest.raises(b.BudgetBlocked):p.ProbeLedger.provision(p.PROBE_PATH,consent)
    alias=tmp_path/'alias';alias.symlink_to(p.PROBE_PATH)
    with pytest.raises(b.BudgetBlocked):p.ProbeLedger(alias)
    other=tmp_path/'other'
    with pytest.raises(b.BudgetBlocked):p.ProbeLedger.provision(other,consent)
    assert not other.exists()


@pytest.mark.parametrize('phase',['initialize','activate'])
def test_failed_provision_keeps_fence(prior,monkeypatch,phase):
    original=b._provision_commit
    def fail(db,current):
        original(db,current)
        if current==phase:raise sqlite3.OperationalError('synthetic fault')
    monkeypatch.setattr(b,'_provision_commit',fail)
    with pytest.raises(b.BudgetBlocked):activate()
    assert b._provision_marker(p.PROBE_PATH).exists()
    with pytest.raises(b.BudgetBlocked):p.ProbeLedger(p.PROBE_PATH).check()
    with pytest.raises(b.BudgetBlocked):activate()


def test_source_drift_during_provision_stays_blocked(prior,monkeypatch):
    consent=p.approval_template();consent['approved']=True
    original=b._provision_commit
    def drift(db,current):
        original(db,current)
        if current=='initialize':monkeypatch.setattr(b,'fingerprint',lambda:'changed')
    monkeypatch.setattr(b,'_provision_commit',drift)
    with pytest.raises(b.BudgetBlocked):p.ProbeLedger.provision(p.PROBE_PATH,consent)
    assert b._provision_marker(p.PROBE_PATH).exists()


def test_request_mutation_blocks_factory_before_reservation(prior):
    import asyncio
    from rag_app.ofox_demo import GuardedTransport
    ledger=activate();claim=ledger.begin(b.questions()['EXP11'])
    messages=p.selection_messages()
    payload=json.loads(messages[1]['content']);payload['source_units']=[]
    messages[1]['content']=json.dumps(payload)
    body=dict(model=b.MODEL,messages=messages,max_completion_tokens=1200,reasoning_effort='low',
        response_format={'type':'json_object'},stream=False,extra_body={'provider':{'type':'openai','fallback':[]}})
    with pytest.raises(b.BudgetBlocked):
        asyncio.run(GuardedTransport(ledger,claim,lambda:pytest.fail('No transport')).handle_async_request(
            httpx.Request('POST',b.PROVIDER+'/chat/completions',json=body)))
    assert ledger.snapshot()['attempts']==[]


def test_cancelled_dispatch_stays_consumed(prior):
    import asyncio
    activate()
    def respond(request):raise asyncio.CancelledError('SYNTHETIC_PRIVATE')
    with pytest.raises(asyncio.CancelledError):
        p.run_once(settings=Settings(api_key='synthetic'),transport=httpx.MockTransport(respond))
    ledger=p.ProbeLedger(p.PROBE_PATH)
    assert len(ledger.snapshot()['attempts'])==1 and ledger.snapshot()['state']=='stopped'
    assert ledger.first_result('EXP11')['diagnostics'][0]['category']=='cancelled'
    with pytest.raises(b.BudgetBlocked):ledger.check()


def test_result_audit_failure_never_resets_consumed_attempt(prior,monkeypatch):
    activate()
    monkeypatch.setattr(p.ProbeLedger,'save_first',lambda *a:(_ for _ in ()).throw(b.BudgetBlocked('fault')))
    with pytest.raises(b.BudgetBlocked):
        p.run_once(settings=Settings(api_key='synthetic'),transport=httpx.MockTransport(lambda r:httpx.Response(403)))
    ledger=p.ProbeLedger(p.PROBE_PATH)
    assert len(ledger.snapshot()['attempts'])==1
    with pytest.raises(b.BudgetBlocked):ledger.check()


def test_changed_prior_after_activation_blocks_before_dispatch(prior):
    ledger=activate()
    claim=ledger.begin(b.questions()['EXP11'])
    original=prior.read_bytes()
    prior.write_bytes(original+b'changed')
    with pytest.raises(b.BudgetBlocked):ledger.reserve(claim,'selection')
    # Synthetic prior alone may be restored by the test, never a production recovery path.
    prior.write_bytes(original)
    assert ledger.snapshot()['attempts']==[]


def test_base_controller_cannot_consume_probe_store(prior):
    ledger=activate()
    with pytest.raises(b.BudgetBlocked):b.SessionLedger(p.PROBE_PATH).check()
    with pytest.raises(b.BudgetBlocked):b.SessionLedger(p.PROBE_PATH).begin(b.questions()['EXP11'])
    claim=ledger.begin(b.questions()['EXP11'])
    with pytest.raises(b.BudgetBlocked):b.SessionLedger(p.PROBE_PATH).reserve(claim,'selection')
    assert ledger.snapshot()['attempts']==[]


@pytest.mark.parametrize('content',['SYNTHETIC_PRIVATE','{"secret":"SYNTHETIC_PRIVATE"}'])
def test_invalid_planning_content_has_separate_sanitized_diagnostic(prior,content):
    activate()
    result=p.run_once(settings=Settings(api_key='synthetic'),transport=httpx.MockTransport(lambda r:
        httpx.Response(200,json={'model':b.MODEL,'choices':[{'finish_reason':'stop','message':{'content':content}}]})))
    assert result['status']=='failed'
    assert result['diagnostics'][0]['category']=='ok'
    assert result['diagnostics'][-1]['category'] in {'invalid_json','invalid_schema'}
    assert result['diagnostics'][-1]['failure_stage']=='content'
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(result)
    assert p.ProbeLedger(p.PROBE_PATH).first_result('EXP11')==result


def test_credential_file_not_loaded_without_authorization(prior,monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv,'dotenv_values',lambda *a,**k:pytest.fail('No credential read'))
    with pytest.raises(b.BudgetBlocked):p.run_once(credential_file=prior.parent/'private.env')


def test_explicit_credential_file_loads_only_after_check(prior,monkeypatch):
    import dotenv
    activate();loaded=[]
    def load(path,**kwargs):
        assert p.ProbeLedger(p.PROBE_PATH).snapshot()['attempts']==[]
        loaded.append(path)
        assert kwargs == {'interpolate':False}
        return {'OFOX_API_KEY':'SYNTHETIC_ONLY','LLM_API_KEY':'SYNTHETIC_UNRELATED'}
    monkeypatch.setattr(dotenv,'dotenv_values',load)
    monkeypatch.setattr(Settings,'from_env',lambda:Settings())
    result=p.run_once(credential_file=prior.parent/'private.env',transport=httpx.MockTransport(lambda r:httpx.Response(403)))
    assert loaded==[prior.parent/'private.env'] and result['status']=='failed'
    with pytest.raises(b.BudgetBlocked):p.run_once(credential_file=prior.parent/'private.env')
    assert len(loaded)==1
