"""V4 full pipeline: all incident stores and HTTP responses are synthetic."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import asyncio,json,sqlite3

import httpx
import pytest

from rag_app import demo_budget as b, ofox_probe as v2, ofox_azure_probe as v3, ofox_v4 as p
from rag_app.ofox_demo import GuardedTransport
from test_ofox_probe import prior as v1
from test_ofox_azure_probe import prior as v2_chain
from test_ofox_demo import setup


@pytest.fixture
def prior(v2_chain,monkeypatch):
    consent=v3.approval_template();consent['approved']=True
    ledger=v3.ProbeLedger.provision(v3.PROBE_PATH,consent)
    claim=ledger.begin(b.questions()['EXP11'])
    ledger.record(ledger.reserve(claim,'selection'),True,diagnostic={'http_status':200})
    monkeypatch.setattr(p,'V3_PATH',v3.PROBE_PATH)
    monkeypatch.setattr(p,'V3_SHA256',sha256(v3.PROBE_PATH.read_bytes()).hexdigest())
    monkeypatch.setattr(p,'V3_SOURCE',b.fingerprint())
    monkeypatch.setattr(p,'PROBE_PATH',v3.PROBE_PATH.parent/'full_v4.sqlite3')
    return [*v2_chain,v3.PROBE_PATH]


@pytest.fixture
def env(prior,setup):
    _,_,cases,_,_,cfg=setup
    consent=p.approval_template();consent['approved']=True
    ledger=p.AcceptanceLedger.provision(p.PROBE_PATH,consent)
    calls=[];mode={'value':'ok'}
    def respond(request):
        body=json.loads(request.content)
        assert body['extra_body']=={'provider':{'type':'azure_foundry','fallback':[]}}
        assert body['model']==b.MODEL and body['max_completion_tokens']==1200 and body['reasoning_effort']=='low'
        payload=json.loads(body['messages'][1]['content'])
        stage='generation' if 'evidence_plan' in payload else 'selection'
        calls.append(stage);value=mode['value']
        if value=='http_first' or value=='http_second' and stage=='generation':return httpx.Response(400,json={'error':{'type':'provider_type_unavailable','message':'SYNTHETIC_PRIVATE'}})
        if value=='wrong_model':return httpx.Response(200,json={'model':'SYNTHETIC_PRIVATE'})
        if value=='timeout':raise httpx.ReadTimeout('SYNTHETIC_PRIVATE')
        if stage=='selection':
            uid=next(u['unit_id'] for u in payload['source_units'] if 'from a longer-term perspective' in u['text'])
            content={'parts':[{'part_id':part['part_id'],'supported':value!='planning_refusal',
                'unit_ids':[] if value=='planning_refusal' else [uid]} for part in payload['question_parts']]}
        else:
            assert payload['evidence_plan']['selection']['parts'][0]['supported']
            content={'status':'answered','claims':[{'text':'SYNTHETIC_GENERATED_SENTENCE','evidence':u['evidence']}
                for u in payload['evidence_plan']['selected_units']]}
            if value=='bad_quote':content['claims'][0]['evidence'][0]['quote']='FABRICATED_PRIVATE_QUOTE'
            if value=='generation_refusal':content={'status':'insufficient_evidence','claims':[]}
            if value=='key_echo':content['claims'][0]['text']='SYNTHETIC_ONLY'
        if value=='invalid_plan' and stage=='selection':content={'secret':'SYNTHETIC_PRIVATE'}
        text='SYNTHETIC_PRIVATE' if value=='invalid_json' else json.dumps(content)
        return httpx.Response(200,json={'model':b.MODEL,'usage':{'prompt_tokens':10,'completion_tokens':3,'total_tokens':13,
            'prompt_tokens_details':{'cache_write_tokens':8,'secret':'SYNTHETIC_PRIVATE'}},
            'choices':[{'finish_reason':'length' if value=='length' else 'stop','message':{'content':text}}]})
    cfg=replace(cfg,api_key='SYNTHETIC_ONLY')
    service=p.create_service(cfg,transport=httpx.MockTransport(respond))
    return service,ledger,calls,mode,cfg,prior


def test_full_two_stage_llm_answer_citations_and_two_attempt_stop(env):
    service,ledger,calls,_,cfg,prior=env
    before=[(x.read_bytes(),x.stat().st_mtime_ns) for x in prior]
    result=service.answer_question(b.questions()['EXP11'])
    assert result['status']=='answered' and result['answer'].startswith('SYNTHETIC_GENERATED_SENTENCE')
    assert calls==['selection','generation']
    assert result['usage']['total_tokens']==26
    assert {c['document_id'] for c in result['citations']}=={'fsb_20241114_ai_stability'}
    assert {c['page_number'] for c in result['citations']}=={6}
    assert all(c['page_url'].endswith('#page=6') for c in result['citations'])
    assert ledger.snapshot()['state']=='stopped'
    assert len(ledger.snapshot()['attempts'])==2
    assert [r['stage'] for r in ledger.responses()]==['selection','generation']
    assert ledger.responses()[0]['validation']=='accepted'
    assert ledger.responses()[1]['validated']['citations']==result['citations']
    assert ledger.first_result('EXP11')['answer']==result['answer']
    assert service.answer_question(b.questions()['EXP11'])['status']=='acceptance_blocked'
    with pytest.raises(b.BudgetBlocked):p.create_service(cfg,transport=httpx.MockTransport(lambda r:pytest.fail('Third request')))
    with ledger.transaction() as db:token=db.execute("SELECT token FROM cases WHERE id='EXP11'").fetchone()[0]
    with pytest.raises(b.BudgetBlocked,match='Two provider attempts'):
        ledger.reserve(('EXP11',token),'generation')
    assert calls==['selection','generation']
    assert before==[(x.read_bytes(),x.stat().st_mtime_ns) for x in prior]


@pytest.mark.parametrize('value,count',[
    ('planning_refusal',1),('invalid_plan',1),('invalid_json',1),('http_first',1),('wrong_model',1),('timeout',1),('length',1),
    ('http_second',2),('bad_quote',2),('generation_refusal',2),('key_echo',2)])
def test_refusal_failures_stop_and_preserve_first_evidence(env,value,count):
    service,ledger,calls,mode,cfg,_=env;mode['value']=value
    result=service.answer_question(b.questions()['EXP11'])
    assert result['status'] in {'invalid_output','llm_error','acceptance_blocked'}
    assert not result['answer'] and not result['citations']
    assert len(calls)==count and len(ledger.snapshot()['attempts'])==count
    assert ledger.snapshot()['state']=='stopped'
    saved=json.dumps(result)+json.dumps(ledger.responses())+ledger.path.read_bytes().decode(errors='ignore')
    for secret in ['SYNTHETIC_PRIVATE','SYNTHETIC_ONLY','FABRICATED_PRIVATE_QUOTE']:assert secret not in saved
    assert ledger.first_result('EXP11') is not None
    assert service.answer_question(b.questions()['EXP11'])['status']=='acceptance_blocked'
    assert len(calls)==count


def test_generation_without_fresh_plan_blocked(env):
    _,ledger,calls,_,_,_=env
    claim=ledger.begin(b.questions()['EXP11'])
    messages=v2.selection_messages();payload=json.loads(messages[1]['content']);payload['evidence_plan']={}
    messages[1]['content']=json.dumps(payload)
    body=dict(model=b.MODEL,messages=messages,max_completion_tokens=1200,reasoning_effort='low',response_format={'type':'json_object'},
        stream=False,extra_body={'provider':{'type':'azure_foundry','fallback':[]}})
    with pytest.raises(b.BudgetBlocked):
        asyncio.run(GuardedTransport(ledger,claim,lambda:pytest.fail('No generation')).handle_async_request(httpx.Request('POST',b.PROVIDER+'/chat/completions',json=body)))
    assert ledger.snapshot()['attempts']==[] and not calls


def test_prior_controllers_cannot_spend_v4(env):
    _,ledger,_,_,_,_=env
    with pytest.raises(b.BudgetBlocked):b.SessionLedger(p.PROBE_PATH).check()
    with pytest.raises(b.BudgetBlocked):v2.ProbeLedger(p.PROBE_PATH)
    with pytest.raises(b.BudgetBlocked):v3.ProbeLedger(p.PROBE_PATH)
    claim=ledger.begin(b.questions()['EXP11'])
    with pytest.raises(b.BudgetBlocked):b.SessionLedger(p.PROBE_PATH).reserve(claim,'selection')
    assert ledger.snapshot()['attempts']==[]


@pytest.mark.parametrize('which',[0,1,2])
def test_prior_drift_blocks_credentials(env,monkeypatch,which):
    _,_,_,_,cfg,prior=env
    prior[which].write_bytes(prior[which].read_bytes()+b'synthetic drift')
    import dotenv
    monkeypatch.setattr(dotenv,'dotenv_values',lambda *a,**k:pytest.fail('No credential read'))
    with pytest.raises(b.BudgetBlocked):p.create_service(cfg,credential_file=prior[0].parent/'private.env')


def test_source_drift_blocks_credentials(env,monkeypatch):
    _,_,calls,_,cfg,_=env
    monkeypatch.setattr(b,'fingerprint',lambda:'changed')
    import dotenv
    monkeypatch.setattr(dotenv,'dotenv_values',lambda *a,**k:pytest.fail('No credential read'))
    with pytest.raises(b.BudgetBlocked):p.create_service(cfg,credential_file='private.env')
    assert calls==[]


def test_first_response_audit_fault_blocks_without_second_dispatch(env):
    service,ledger,calls,_,_,_=env
    with sqlite3.connect(ledger.path) as db:
        db.execute("CREATE TRIGGER fail_response BEFORE INSERT ON stage_responses BEGIN SELECT RAISE(ABORT,'synthetic fault'); END")
    result=service.answer_question(b.questions()['EXP11'])
    assert result['status'] in {'llm_error','acceptance_blocked'}
    assert calls==['selection'] and len(ledger.snapshot()['attempts'])==1
    assert service.answer_question(b.questions()['EXP11'])['status']=='acceptance_blocked'


def test_only_one_concurrent_claim_and_uncertain_restart_blocked(env):
    _,ledger,_,_,cfg,_=env
    def begin(_):
        try:return p.AcceptanceLedger(p.PROBE_PATH).begin(b.questions()['EXP11'])
        except b.BudgetBlocked:return None
    with ThreadPoolExecutor(max_workers=6) as pool:claims=list(pool.map(begin,range(6)))
    claim=next(c for c in claims if c)
    assert sum(c is not None for c in claims)==1
    ledger.reserve(claim,'selection')
    with pytest.raises(b.BudgetBlocked):p.create_service(cfg,transport=httpx.MockTransport(lambda r:pytest.fail('Resume')))


@pytest.mark.parametrize('phase',['initialize','activate'])
def test_provision_fence_failures(prior,monkeypatch,phase):
    consent=p.approval_template();consent['approved']=True;original=b._provision_commit
    def fail(db,current):
        original(db,current)
        if current==phase:raise sqlite3.OperationalError('synthetic fault')
    monkeypatch.setattr(b,'_provision_commit',fail)
    with pytest.raises(b.BudgetBlocked):p.AcceptanceLedger.provision(p.PROBE_PATH,consent)
    assert b._provision_marker(p.PROBE_PATH).exists()
    with pytest.raises(b.BudgetBlocked):p.AcceptanceLedger(p.PROBE_PATH).check()
    with pytest.raises(b.BudgetBlocked):p.AcceptanceLedger.provision(p.PROBE_PATH,consent)


def test_escaped_credential_echo_is_blocked_before_persistence(env):
    service,ledger,calls,_,cfg,_=env
    original=service.factory()
    async def escaped(request):
        response=await original.handle_async_request(request)
        payload=json.loads(json.loads(request.content)['messages'][1]['content'])
        if 'evidence_plan' in payload:
            data=response.json()
            content=json.loads(data['choices'][0]['message']['content'])
            content['claims'][0]['text']=cfg.api_key
            encoded=json.dumps(content)
            encoded=encoded.replace(cfg.api_key,''.join('\\u%04x'%ord(c) for c in cfg.api_key))
            data['choices'][0]['message']['content']=encoded
            return httpx.Response(200,json=data)
        return response
    service.factory=lambda:httpx.MockTransport(escaped)
    result=service.answer_question(b.questions()['EXP11'])
    assert result['status']=='invalid_output' and not result['answer']
    assert calls==['selection','generation'] and ledger.snapshot()['state']=='stopped'
    assert cfg.api_key not in json.dumps(result)+ledger.path.read_bytes().decode(errors='ignore')


@pytest.mark.parametrize('delta,accepted',[(1e-8,True),(1e-3,False)])
def test_existing_retrieval_distance_tolerance_preserved(env,delta,accepted):
    service,ledger,calls,_,_,_=env
    original=service.retriever.retrieve
    def retrieve(*a,**k):
        from copy import deepcopy
        hits=deepcopy(original(*a,**k));hits[0]['distance']+=delta
        return hits
    service.retriever.retrieve=retrieve
    result=service.answer_question(b.questions()['EXP11'])
    assert (result['status']=='answered') is accepted
    assert len(calls)==(2 if accepted else 0)
    assert ledger.snapshot()['state']=='stopped'


@pytest.mark.parametrize('outer',[False,True])
def test_duplicate_request_keys_rejected_before_reservation(env,outer):
    _,ledger,_,_,_,_=env
    messages=p.v2.selection_messages()
    if not outer:
        messages[1]['content']='{"question":"unauthorized",'+messages[1]['content'][1:]
    body=json.dumps(dict(model=b.MODEL,messages=messages,max_completion_tokens=1200,
        reasoning_effort='low',response_format={'type':'json_object'},stream=False,
        extra_body={'provider':{'type':'azure_foundry','fallback':[]}}))
    if outer:body='{"model":"unauthorized",'+body[1:]
    request=httpx.Request('POST',b.PROVIDER+'/chat/completions',content=body)
    with pytest.raises(b.BudgetBlocked,match='Duplicate'):
        ledger.validate_request(request)
    assert ledger.snapshot()['attempts']==[]
