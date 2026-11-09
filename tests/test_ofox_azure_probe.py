"""Azure v3 tests use synthetic v1/v2 incidents and temporary stores only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import sqlite3

import httpx
import pytest

from rag_app import demo_budget as b, ofox_probe as v2, ofox_azure_probe as a
from rag_app.config import Settings
from rag_app.ofox_demo import GuardedTransport
from test_ofox_probe import prior as v1


@pytest.fixture
def prior(v1,monkeypatch):
    consent=v2.approval_template();consent['approved']=True
    ledger=v2.ProbeLedger.provision(v2.PROBE_PATH,consent)
    claim=ledger.begin(b.questions()['EXP11'])
    ledger.record(ledger.reserve(claim,'selection'),False,diagnostic={
        'http_status':400,'provider_error_type':'provider_type_unavailable','http_response_received':True})
    monkeypatch.setattr(a,'V2_PATH',v2.PROBE_PATH)
    monkeypatch.setattr(a,'V2_SHA256',sha256(v2.PROBE_PATH.read_bytes()).hexdigest())
    monkeypatch.setattr(a,'V2_SOURCE',b.fingerprint())
    monkeypatch.setattr(a,'PROBE_PATH',v1.parent/'azure_v3.sqlite3')
    return v1,v2.PROBE_PATH


def activate():
    approval=a.approval_template();approval['approved']=True
    return a.ProbeLedger.provision(a.PROBE_PATH,approval)


def test_prepare_no_approval_or_registry(prior):
    info=a.prepare()
    assert info['approval']['approved'] is False
    assert info['approval']['max_attempts']==1 and info['provider_type']=='azure_foundry'
    assert len(info['prior_incidents'])==2
    assert not info['registry_exists'] and not info['fence_exists']


@pytest.mark.parametrize('status,error_type',[(200,None),(400,'invalid_request_error'),(400,'provider_type_unavailable')])
def test_azure_only_once_and_both_prior_files_unchanged(prior,status,error_type):
    before=[(p.read_bytes(),p.stat().st_mtime_ns) for p in prior]
    activate();calls=[]
    def respond(request):
        calls.append(1);body=json.loads(request.content)
        assert request.method=='POST' and str(request.url)==b.PROVIDER+'/chat/completions'
        assert body['extra_body']=={'provider':{'type':'azure_foundry','fallback':[]}}
        assert body['model']==b.MODEL and body['max_completion_tokens']==1200
        assert body['reasoning_effort']=='low' and body['response_format']=={'type':'json_object'}
        assert body['stream'] is False and len(body['messages'])==2
        if status!=200:
            return httpx.Response(status,json={'error':{'type':error_type,'message':'SYNTHETIC_PRIVATE'}})
        payload=json.loads(body['messages'][1]['content'])
        content={'parts':[{'part_id':p['part_id'],'supported':False,'unit_ids':[]} for p in payload['question_parts']]}
        return httpx.Response(200,json={'model':b.MODEL,'usage':{'total_tokens':10},
            'choices':[{'finish_reason':'stop','message':{'content':json.dumps(content)}}]})
    result=a.run_once(settings=Settings(api_key='SYNTHETIC_KEY'),transport=httpx.MockTransport(respond))
    assert result['status']==('planning_valid' if status==200 else 'failed')
    if error_type:assert result['diagnostics'][0]['provider_error_type']==error_type
    ledger=a.ProbeLedger(a.PROBE_PATH)
    assert len(ledger.snapshot()['attempts'])==1 and ledger.snapshot()['state']=='stopped'
    assert ledger.first_result('EXP11')==result
    with pytest.raises(b.BudgetBlocked):a.run_once(settings=Settings(api_key='synthetic'),transport=httpx.MockTransport(respond))
    assert calls==[1]
    assert [(p.read_bytes(),p.stat().st_mtime_ns) for p in prior]==before
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(result) and 'SYNTHETIC_KEY' not in json.dumps(result)


@pytest.mark.parametrize('route',['openai','bedrock','auto'])
def test_wrong_route_fails_before_factory(prior,route):
    ledger=activate();claim=ledger.begin(b.questions()['EXP11'])
    body=dict(model=b.MODEL,messages=v2.selection_messages(),max_completion_tokens=1200,
        reasoning_effort='low',response_format={'type':'json_object'},stream=False,
        extra_body={'provider':{'type':route,'fallback':[]}})
    with pytest.raises(b.BudgetBlocked):
        asyncio.run(GuardedTransport(ledger,claim,lambda:pytest.fail('No transport')).handle_async_request(
            httpx.Request('POST',b.PROVIDER+'/chat/completions',json=body)))
    assert ledger.snapshot()['attempts']==[]


@pytest.mark.parametrize('field,value',[('max_attempts',6),('source_sha256','v2'),('session_id',v2.SESSION_ID),
    ('authorized_registry',str(v2.PROBE_PATH)),('statement','previous approval'),('approved',False)])
def test_old_or_changed_consent_cannot_initialize(prior,field,value):
    consent=a.approval_template();consent['approved']=True;consent[field]=value
    with pytest.raises(b.BudgetBlocked):a.ProbeLedger.provision(a.PROBE_PATH,consent)
    assert not a.PROBE_PATH.exists() and not b._provision_marker(a.PROBE_PATH).exists()


def test_prior_v1_and_v2_controllers_cannot_spend_v3(prior):
    ledger=activate();claim=ledger.begin(b.questions()['EXP11'])
    with pytest.raises(b.BudgetBlocked):b.SessionLedger(a.PROBE_PATH).reserve(claim,'selection')
    with pytest.raises(b.BudgetBlocked):v2.ProbeLedger(a.PROBE_PATH)
    with pytest.raises(b.BudgetBlocked):ledger.reserve(claim,'generation')
    assert ledger.snapshot()['attempts']==[]


@pytest.mark.parametrize('which',[0,1])
def test_each_prior_drift_blocks_before_credentials(prior,which,monkeypatch):
    activate();path=prior[which];path.write_bytes(path.read_bytes()+b'synthetic drift')
    import dotenv
    monkeypatch.setattr(dotenv,'dotenv_values',lambda *a,**k:pytest.fail('No credential read'))
    with pytest.raises(b.BudgetBlocked):a.run_once(credential_file=path.parent/'private.env')


def test_single_concurrent_reservation_and_no_restart(prior):
    ledger=activate();claim=ledger.begin(b.questions()['EXP11'])
    def reserve(_):
        try:return a.ProbeLedger(a.PROBE_PATH).reserve(claim,'selection')
        except b.BudgetBlocked:return None
    with ThreadPoolExecutor(max_workers=8) as pool:values=list(pool.map(reserve,range(8)))
    assert sum(v is not None for v in values)==1
    with pytest.raises(b.BudgetBlocked):a.ProbeLedger(a.PROBE_PATH).check()
    with pytest.raises(b.BudgetBlocked):activate()


@pytest.mark.parametrize('phase',['initialize','activate'])
def test_provisioning_failures_keep_fence(prior,monkeypatch,phase):
    original=b._provision_commit
    def fail(db,current):
        original(db,current)
        if current==phase:raise sqlite3.OperationalError('SYNTHETIC_FAULT')
    monkeypatch.setattr(b,'_provision_commit',fail)
    with pytest.raises(b.BudgetBlocked):activate()
    assert b._provision_marker(a.PROBE_PATH).exists()
    with pytest.raises(b.BudgetBlocked):a.ProbeLedger(a.PROBE_PATH).check()
    with pytest.raises(b.BudgetBlocked):activate()


def test_changed_frozen_evidence_blocks_before_reservation(prior):
    ledger=activate();claim=ledger.begin(b.questions()['EXP11'])
    messages=v2.selection_messages();payload=json.loads(messages[1]['content'])
    payload['source_units']=[];messages[1]['content']=json.dumps(payload)
    body=dict(model=b.MODEL,messages=messages,max_completion_tokens=1200,reasoning_effort='low',
        response_format={'type':'json_object'},stream=False,extra_body={'provider':{'type':'azure_foundry','fallback':[]}})
    with pytest.raises(b.BudgetBlocked):
        asyncio.run(GuardedTransport(ledger,claim,lambda:pytest.fail('No transport')).handle_async_request(
            httpx.Request('POST',b.PROVIDER+'/chat/completions',json=body)))
    assert ledger.snapshot()['attempts']==[]


@pytest.mark.parametrize('header',['openai','azure_foundry','auto'])
def test_routing_headers_are_not_an_approved_alternate_route(prior,header):
    ledger=activate();claim=ledger.begin(b.questions()['EXP11'])
    body=dict(model=b.MODEL,messages=v2.selection_messages(),max_completion_tokens=1200,reasoning_effort='low',
        response_format={'type':'json_object'},stream=False,extra_body={'provider':{'type':'azure_foundry','fallback':[]}})
    with pytest.raises(b.BudgetBlocked):
        asyncio.run(GuardedTransport(ledger,claim,lambda:pytest.fail('No transport')).handle_async_request(
            httpx.Request('POST',b.PROVIDER+'/chat/completions',json=body,headers={'X-OfoxAI-Provider-Type':header})))
    assert ledger.snapshot()['attempts']==[]
