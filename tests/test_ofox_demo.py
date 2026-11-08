"""Offline OfoxAI adapter and durable acceptance guard. Synthetic consent only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from rag_app import demo, demo_budget as b
from rag_app.config import Settings
from rag_app.ofox_demo import create_ofox_service


def approval(path, **changes):
    return {'approved':True, 'statement':'SYNTHETIC TEST ONLY, NOT LIVE CONSENT',
            'session_id':'synthetic', 'authorized_registry':str(path.resolve()),
            'source_sha256':b.fingerprint(), 'provider':b.PROVIDER, 'model':b.MODEL,
            'profile':b.PROFILE, 'max_attempts':6, **changes}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path/'registry.sqlite3'
    monkeypatch.setattr(b, 'DEFAULT_LEDGER', path)
    ledger = b.SessionLedger.provision(path, approval(path))
    (tmp_path/'enhanced').mkdir()
    raw = (demo.RUNTIME/'temporal_catalog.json').read_bytes()
    (tmp_path/'temporal_catalog.json').write_bytes(raw)
    from hashlib import sha256
    (tmp_path/'enhanced/collection_context.json').write_text(json.dumps({'temporal_catalog_sha256':sha256(raw).hexdigest()}))
    candidate, _ = demo._load_experiment()
    rows = json.loads((demo.JOINT/'model_inputs40.json').read_bytes())['requests']
    cases = {r['id']:json.loads(r['messages'][1]['content']) for r in rows if r['id'] in b.CASE_IDS}
    evidence = {v['question']:v['evidence'] for v in cases.values()}
    class SnapshotRetriever:
        def __init__(self,*args):
            pass
        def retrieve(self, question, top_k, *, collection, arm):
            assert (top_k,collection,arm)==(8,'fixed_150_overlap_30','enhanced')
            return evidence[question]
    monkeypatch.setattr(candidate,'JointCandidateRetriever',SnapshotRetriever)
    monkeypatch.setenv('OFOX_API_KEY','SYNTHETIC_OFFLINE_ONLY')
    cfg = Settings(experiment_dir=tmp_path)
    calls = []
    mode = {'value':'ok'}
    def respond(request):
        assert str(request.url) == 'https://api.ofox.ai/v1/chat/completions'
        assert request.headers['authorization']=='Bearer SYNTHETIC_OFFLINE_ONLY'
        body=json.loads(request.content)
        assert body['model']=='openai/gpt-6-luna' and body['max_completion_tokens']==1200
        assert body['reasoning_effort']=='low' and body['response_format']=={'type':'json_object'}
        assert not {'temperature','thinking','max_tokens','tools'} & body.keys()
        assert body['extra_body']=={'provider':{'type':'openai','fallback':[]}}
        payload=json.loads(body['messages'][1]['content'])
        stage='generation' if 'evidence_plan' in payload else 'selection'
        calls.append(stage)
        value=mode['value']
        if value in ('401','429','503') or value == 'fail_generation' and stage == 'generation':
            return httpx.Response(int(value) if value.isdigit() else 503,text='SECRET_PROVIDER_SENTINEL')
        if value == 'timeout':
            raise httpx.ReadTimeout('SECRET_TIMEOUT_SENTINEL')
        if value == 'malformed':
            return httpx.Response(200,json={'secret':'SECRET_PROVIDER_SENTINEL'})
        if stage=='selection':
            hints=('from a longer-term perspective',)
            if payload['question']==cases['EXP30']['question']:
                hints=('The log includes intermediate decisions','records may also include prompts')
            if payload['question']==cases['EXP-R07']['question']:
                hints=('structured initial risk assessment',)
            units=[next(u['unit_id'] for u in payload['source_units'] if s in u['text']) for s in hints]
            if value=='unexpected_support' and payload['question']==cases['EXP-R07']['question']:
                units=units*len(payload['question_parts'])
            content={'parts':[{'part_id':p['part_id'],'supported':i<len(units),'unit_ids':units[i:i+1]}
                              for i,p in enumerate(payload['question_parts'])]}
        else:
            content={'status':'answered','claims':[{'text':'Synthetic new OfoxAI answer.', 'evidence':u['evidence']}
                         for u in payload['evidence_plan']['selected_units']]}
            if value=='bad_quote':
                content['claims'][0]['evidence']=[{'id':1,'quote':'FABRICATED_OFFLINE_QUOTE'}]
        return httpx.Response(200,json={'model':b.MODEL,'usage':{'total_tokens':10,'api_key':'MUST_NOT_BE_LOGGED'},
            'choices':[{'finish_reason':'stop','message':{'content':json.dumps(content)}}]})
    service = create_ofox_service(cfg,transport=httpx.MockTransport(respond))
    return service,ledger,cases,calls,mode,cfg


def test_two_stage_normal_cross_document_refusal_and_duplicate(setup):
    svc, ledger, cases, calls, mode, cfg = setup
    for id in b.CASE_IDS:
        result=svc.answer_question(cases[id]['question'])
        assert result['status']==('insufficient_evidence' if id=='EXP-R07' else 'answered')
        assert result['usage']['total_tokens']==(10 if id=='EXP-R07' else 20)
        assert result['experiment_origin']=='NEW_OFOX_GPT6_LUNA_DEMO_NOT_HISTORICAL_SCORES'
        if id=='EXP30':
            assert {c['page_number'] for c in result['citations']}=={5,59}
            assert len({c['document_id'] for c in result['citations']})==2
    assert calls==['selection','generation','selection','generation','selection']
    assert ledger.snapshot()['state']=='complete'
    assert ledger.first_result('EXP11')['status']=='answered'
    assert 'MUST_NOT_BE_LOGGED' not in ledger.path.read_bytes().decode(errors='ignore')
    before=len(calls)
    assert svc.answer_question(cases['EXP11']['question'])['status']=='acceptance_blocked'
    assert len(calls)==before


@pytest.mark.parametrize('mode_value',['401','429','503','timeout','malformed','bad_quote','fail_generation'])
def test_failures_stop_session_and_keep_attempts(setup,mode_value):
    svc,ledger,cases,calls,mode,cfg=setup
    mode['value']=mode_value
    result=svc.answer_question(cases['EXP11']['question'])
    assert result['status'] in {'llm_error','invalid_output'}
    assert not result['answer'] and not result['citations']
    assert 'SECRET_' not in json.dumps(result)
    audit=ledger.snapshot()
    assert audit['state']=='stopped'
    assert len(audit['attempts'])==len(calls)==(2 if mode_value in {'bad_quote','fail_generation'} else 1)
    if mode_value=='fail_generation':
        assert result['usage']['total_tokens']==10 and result['usage_completeness']=='partial_or_unknown'
        assert ledger.first_result('EXP11')['usage']['total_tokens']==10
    before=len(calls)
    assert svc.answer_question(cases['EXP30']['question'])['status']=='acceptance_blocked'
    assert len(calls)==before


def test_restart_uncertain_attempt_and_different_labels_cannot_reset(tmp_path):
    p=tmp_path/'registry'
    ledger=b.SessionLedger.provision(p,approval(p))
    claim=ledger.begin(b.questions()['EXP11']);ledger.reserve(claim,'selection')
    # A genuinely new interpreter observes the committed uncertain reservation.
    code="from pathlib import Path; from rag_app.demo_budget import SessionLedger,BudgetBlocked,questions; l=SessionLedger(Path(__import__('sys').argv[1])); assert len(l.snapshot()['attempts'])==1\ntry:l.begin(questions()['EXP11'])\nexcept BudgetBlocked:pass\nelse:raise AssertionError('Restart bypass')"
    result=subprocess.run([sys.executable,'-c',code,str(p)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert b.SessionLedger(p).snapshot()['attempts'][0]['state']=='reserved'
    with pytest.raises(b.BudgetBlocked):
        b.SessionLedger.provision(p,approval(p,session_id='changed_output_and_session'))
    with pytest.raises(b.BudgetBlocked):
        ledger.begin(b.questions()['EXP30'])


def test_seventh_attempt_blocks_before_dispatch(tmp_path):
    p=tmp_path/'r';ledger=b.SessionLedger.provision(p,approval(p))
    for id in b.CASE_IDS:
        claim=ledger.begin(b.questions()[id])
        for stage in ['selection','generation']:
            ordinal=ledger.reserve(claim,stage);ledger.record(ordinal,True,{'total_tokens':1})
        if id!='EXP-R07':ledger.finish(claim,'answered')
    assert len(ledger.snapshot()['attempts'])==6
    with pytest.raises(b.BudgetBlocked,match='Six'):
        ledger.reserve(claim,'generation')
    import asyncio
    from rag_app.ofox_demo import GuardedTransport
    rows=json.loads((demo.JOINT/'model_inputs40.json').read_bytes())['requests']
    messages=next(r['messages'] for r in rows if r['id']=='EXP-R07')
    body=dict(model=b.MODEL,messages=messages,max_completion_tokens=1200,reasoning_effort='low',
              response_format={'type':'json_object'},stream=False,extra_body={'provider':{'type':'openai','fallback':[]}})
    factories=[]
    def factory():factories.append(1);raise AssertionError('Seventh dispatch')
    with pytest.raises(b.BudgetBlocked,match='Six'):
        asyncio.run(GuardedTransport(ledger,claim,factory).handle_async_request(
            httpx.Request('POST',b.PROVIDER+'/chat/completions',json=body)))
    assert factories==[]


def test_unexpected_support_for_refusal_case_blocks_final_dispatch(setup):
    svc,ledger,cases,calls,mode,cfg=setup
    for id in ['EXP11','EXP30']:
        assert svc.answer_question(cases[id]['question'])['status']=='answered'
    mode['value']='unexpected_support'
    assert svc.answer_question(cases['EXP-R07']['question'])['status']=='llm_error'
    assert calls==['selection','generation','selection','generation','selection']
    assert ledger.snapshot()['state']=='stopped'


def test_atomic_claim_and_reservation_across_threads(tmp_path):
    p=tmp_path/'r';ledger=b.SessionLedger.provision(p,approval(p))
    def claim(_):
        try:return b.SessionLedger(p).begin(b.questions()['EXP11'])
        except b.BudgetBlocked:return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(claim,range(8)))
    winner=[r for r in results if r is not None]
    assert len(winner)==1
    def reserve(_):
        try:return b.SessionLedger(p).reserve(winner[0],'selection')
        except b.BudgetBlocked:return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows=list(pool.map(reserve,range(8)))
    assert [r for r in rows if r is not None]==[1]
    assert len(ledger.snapshot()['attempts'])==1


def test_only_exact_cases_and_order_no_registry_alias_reset(setup,monkeypatch):
    svc,ledger,cases,calls,mode,cfg=setup
    for q in ['unknown',cases['EXP11']['question']+' ',cases['EXP30']['question']]:
        assert svc.answer_question(q)['status']=='acceptance_blocked'
    assert not calls
    monkeypatch.setenv('OFOX_SESSION_ID','another')
    monkeypatch.setenv('OFOX_LEDGER','/does/not/override/the/fixed/registry')
    assert create_ofox_service(cfg,transport=httpx.MockTransport(lambda r:None)).ledger.path==ledger.path
    for profile in ['baseline','joint_pairs8','unknown']:
        with pytest.raises(b.BudgetBlocked):demo.create_demo_service(cfg,profile)


def test_missing_corrupt_and_write_failures_block(tmp_path,monkeypatch):
    p=tmp_path/'missing'
    with pytest.raises(b.BudgetBlocked):b.SessionLedger(p).check()
    assert not p.exists()
    p.write_text('corrupt')
    with pytest.raises(b.BudgetBlocked):b.SessionLedger(p).check()
    other=tmp_path/'other'
    with pytest.raises(b.BudgetBlocked):b.SessionLedger.provision(other,approval(other,approved=False))
    assert not other.exists()


@pytest.mark.parametrize('method',['reserve','record'])
def test_audit_failure_never_allows_following_dispatch(setup,monkeypatch,method):
    svc,ledger,cases,calls,mode,cfg=setup
    def fail(*a,**k):raise b.BudgetBlocked('SYNTHETIC_AUDIT_FAULT')
    monkeypatch.setattr(svc.ledger,method,fail)
    result=svc.answer_question(cases['EXP11']['question'])
    assert result['status'] in {'acceptance_blocked','llm_error'}
    assert len(calls)==(0 if method=='reserve' else 1)
    assert svc.answer_question(cases['EXP30']['question'])['status']=='acceptance_blocked'


def test_streamlit_profile_switch_cannot_use_cached_baseline(setup,monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    svc,ledger,cases,calls,mode,cfg=setup
    st.cache_resource.clear()
    registry=ledger.path
    monkeypatch.setattr(b,'DEFAULT_LEDGER',registry.parent/'absent_registry')
    baseline_calls=[]
    class Baseline:
        def answer_question(self,question):
            baseline_calls.append(question)
            return dict(status='answered',answer='Synthetic baseline',citations=[],claims=[],retrieved=[],
                        error=None,model='synthetic',usage={},elapsed_seconds=0)
    monkeypatch.setattr(demo,'create_demo_service',lambda *a,**k:Baseline())
    monkeypatch.setattr(Settings,'from_env',lambda:replace(cfg,api_key='SYNTHETIC_OFFLINE_ONLY'))
    monkeypatch.setenv('LLM_API_KEY','SYNTHETIC_OFFLINE_ONLY')
    monkeypatch.setenv('RAG_DEMO_PROFILE','baseline')
    app=AppTest.from_file(str(b.ROOT/'app.py')).run()
    app.text_area[0].set_value(cases['EXP11']['question']);app.button[0].click().run()
    assert app.session_state['qa_result']['status']=='answered' and len(baseline_calls)==1
    monkeypatch.setattr(b,'DEFAULT_LEDGER',registry)
    app.button[0].click().run()
    assert app.error and not app.exception and not calls
    assert len(baseline_calls)==1  # cached service was not invoked again
    monkeypatch.setenv('RAG_DEMO_PROFILE',b.PROFILE)
    monkeypatch.setattr(demo,'create_demo_service',lambda *a,**k:svc)
    monkeypatch.setattr(Settings,'from_env',lambda:cfg)
    app.text_area[0].set_value(cases['EXP11']['question']);app.button[0].click().run()
    assert app.session_state['qa_result']['status']=='answered'
    monkeypatch.setenv('RAG_DEMO_PROFILE','baseline')
    app.button[0].click().run()
    assert app.error and not app.get('link_button') and len(calls)==2
    st.cache_resource.clear()


@pytest.mark.parametrize('mutation',['url','model','output_budget'])
def test_invalid_wire_configuration_blocks_before_factory(setup,mutation):
    import asyncio
    from rag_app.ofox_demo import GuardedTransport
    svc,ledger,cases,calls,mode,cfg=setup
    claim=ledger.begin(cases['EXP11']['question'])
    rows=json.loads((demo.JOINT/'model_inputs40.json').read_bytes())['requests']
    messages=next(r['messages'] for r in rows if r['id']=='EXP11')
    body=dict(model=b.MODEL,messages=messages,max_completion_tokens=1200,reasoning_effort='low',
              response_format={'type':'json_object'},stream=False,extra_body={'provider':{'type':'openai','fallback':[]}})
    url=b.PROVIDER+'/chat/completions'
    if mutation=='url':url='https://other.invalid/v1/chat/completions'
    if mutation=='model':body['model']='other-model'
    if mutation=='output_budget':body['max_completion_tokens']=1201
    constructed=[]
    def factory():constructed.append(1);raise AssertionError('No dispatch')
    with pytest.raises(b.BudgetBlocked):
        asyncio.run(GuardedTransport(ledger,claim,factory).handle_async_request(httpx.Request('POST',url,json=body)))
    assert not constructed and not ledger.snapshot()['attempts']


def test_concurrent_process_claims_are_serialized(tmp_path):
    p=tmp_path/'registry';b.SessionLedger.provision(p,approval(p))
    code="from pathlib import Path; from rag_app.demo_budget import SessionLedger,BudgetBlocked,questions\ntry:SessionLedger(Path(__import__('sys').argv[1])).begin(questions()['EXP11']); print('won')\nexcept BudgetBlocked:print('blocked')"
    processes=[subprocess.Popen([sys.executable,'-c',code,str(p)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(4)]
    outputs=[proc.communicate() for proc in processes]
    assert all(proc.returncode==0 for proc in processes),outputs
    assert [stdout.strip() for stdout,_ in outputs].count('won')==1


def test_copy_or_symlink_cannot_relocate_approved_registry(tmp_path):
    import shutil
    p=tmp_path/'original';b.SessionLedger.provision(p,approval(p))
    copied=tmp_path/'other_session_directory'
    shutil.copyfile(p,copied)
    with pytest.raises(b.BudgetBlocked):b.SessionLedger(copied).check()
    alias=tmp_path/'alias'
    alias.symlink_to(p)
    with pytest.raises(b.BudgetBlocked):b.SessionLedger(alias).check()


def test_runtime_fingerprint_change_blocks_before_dispatch(setup,monkeypatch):
    svc,ledger,cases,calls,mode,cfg=setup
    monkeypatch.setattr(b,'fingerprint',lambda:'changed_source_or_frozen_input')
    assert svc.answer_question(cases['EXP11']['question'])['status']=='acceptance_blocked'
    assert calls==[]


@pytest.mark.parametrize('field,value', [('approved',False),('source_sha256','wrong'),
    ('authorized_registry','relative'),('max_attempts',7),('provider','https://different.invalid'),
    ('model','another-model'),('profile','baseline')])
def test_invalid_consent_never_initializes_a_registry(tmp_path,field,value):
    p=tmp_path/'r'
    with pytest.raises(b.BudgetBlocked):b.SessionLedger.provision(p,approval(p,**{field:value}))
    assert not p.exists()
