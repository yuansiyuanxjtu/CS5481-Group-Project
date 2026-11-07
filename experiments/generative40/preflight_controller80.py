"""Offline MockTransport suite from the actual delivery directory. No .env/real HTTP."""
import argparse,base64,contextlib,io,json,shutil,socket,subprocess,sys,tempfile
from collections import Counter,defaultdict
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch,Mock

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runtime',required=True,type=Path)
    parser.add_argument('--app-src',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();runtime=args.runtime.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    sys.dont_write_bytecode=True;sys.path[:0]=[str(runtime),str(args.app_src)]
    import controller80 as ctl
    import httpx
    from rag_app.config import Settings
    from rag_app.llm import LLMError
    inputs,protocol=ctl.initialize(runtime,args.app_src)
    from planned_generation import final_messages,PlannedGenerationClient
    from selection_adapter import verify_events
    from rag_app.grounding import validate_generation
    from http_audit import RecordedClient
    expected={json.loads(r['messages'][1]['content'])['question']:r for r in inputs}
    cfg=Settings(api_key='SYNTHETIC_TEST_KEY_ONLY_DO_NOT_LOG',timeout=120,top_k=8,
        collection='fixed_150_overlap_30',arm='enhanced')
    results=[];trials=out/'trials';dispatch_history=[]
    original_open=Path.open
    original_connect=socket.socket.connect
    def protected_connect(sock,address):
        # CPython on Windows builds asyncio's internal socketpair through a
        # loopback connection. Permit only that stdlib caller, never model I/O.
        caller=sys._getframe(1)
        if (sys.platform=='win32' and caller.f_code.co_name=='_fallback_socketpair'
                and Path(caller.f_code.co_filename).resolve()==Path(socket.__file__).resolve()
                and isinstance(address,tuple) and address[0] in {'127.0.0.1','::1'}):
            return original_connect(sock,address)
        raise AssertionError('No external sockets')
    def protected_open(p,*a,**kw):
        assert p.name not in {'.env','.env.local','labels40.json','baseline_B_review40.json',
                              'review_template40.json','baseline_source_neighbor8_first_run.json'},'No credentials/evaluator reads'
        return original_open(p,*a,**kw)
    class Server:
        def __init__(self,trial_id,scenario='success'):
            self.id=trial_id;self.scenario=scenario;self.calls=[]
        def handler(self,request):
            payload=json.loads(request.content);user=json.loads(payload['messages'][-1]['content'])
            q=user['question'];qid=expected[q]['id'];phase='answer_generation' if 'evidence_plan' in user else 'evidence_selection'
            # Reservation must already be visible on disk BEFORE dispatch.
            ledger=[json.loads(x) for x in (trials/self.id/'reservations.jsonl').read_text(encoding='utf-8').splitlines()]
            reservation=ledger[-1]
            assert reservation['id']==qid and reservation['phase']==phase
            assert reservation['attempt_ordinal']==len(self.calls)+1
            assert reservation['messages_sha256']==sha256(ctl.canonical(payload['messages'])).hexdigest()
            self.calls.append({'id':qid,'phase':phase,'ordinal':len(self.calls)+1})
            dispatch_history.append((self.id,qid,phase))
            first=qid==inputs[0]['id']
            target=self.scenario.split(':')[0]
            matches=first and ((target=='selection' and phase=='evidence_selection') or
                              (target=='generation' and phase=='answer_generation'))
            mode=self.scenario.split(':')[-1]
            if matches and mode in {'503','429'}:
                return httpx.Response(int(mode),text='SYNTHETIC_UPSTREAM_EXCEPTION_BODY_NOT_FOR_LOG',request=request)
            if matches and mode=='timeout':raise httpx.ReadTimeout('SYNTHETIC_UPSTREAM_EXCEPTION_BODY_NOT_FOR_LOG',request=request)
            if matches and mode=='network':raise httpx.ConnectError('SYNTHETIC_UPSTREAM_EXCEPTION_BODY_NOT_FOR_LOG',request=request)
            if phase=='evidence_selection':
                unit=user['source_units'][0]['unit_id']
                plan={'parts':[{'part_id':p['part_id'],'supported':True,'unit_ids':[unit]} for p in user['question_parts']]}
                if self.scenario=='unsupported' and qid=='EXP-R06':plan['parts'][-1].update(supported=False,unit_ids=[])
                content=json.dumps(plan,ensure_ascii=False)
                if matches and mode=='invalid_json':content='SYNTHETIC_NOT_JSON'
                if matches and mode=='invalid_contract':content=json.dumps({'parts':[]})
            else:
                ref=user['evidence_plan']['selected_units'][0]['evidence'][0]
                content=json.dumps({'status':'answered','claims':[{'text':'Synthetic offline test claim; not an evaluated factual answer.',
                                                                  'evidence':[ref]}]},ensure_ascii=False)
                if matches and mode=='invalid_json':content='SYNTHETIC_NOT_JSON'
                if matches and mode=='bad_quote':
                    content=json.dumps({'status':'answered','claims':[{'text':'Synthetic test only.',
                        'evidence':[{'id':1,'quote':'THIS_SYNTHETIC_QUOTE_IS_NOT_IN_THE_CHUNK'}]}]})
            n=len(self.calls);prompt=100+n;completion=10+n%7
            return httpx.Response(200,json={'id':f'OFFLINE_ONLY_{self.id}_{n}','model':'OFFLINE_STUB_ONLY',
                'system_fingerprint':'SYNTHETIC_NOT_PROVIDER_FINGERPRINT',
                'choices':[{'message':{'role':'assistant','content':content},'finish_reason':'length' if matches and mode=='truncated' else 'stop'}],
                'usage':{'prompt_tokens':prompt,'completion_tokens':completion,'total_tokens':prompt+completion,
                         'prompt_cache_hit_tokens':20,'prompt_cache_miss_tokens':prompt-20}},request=request)
        def factory(self):return httpx.MockTransport(self.handler)
    def verify(run,anchors,audit,server):
        verify_events(audit.events,anchors['event_count'],anchors['final_event_sha256'])
        success=[];groups=defaultdict(list);by_phase=defaultdict(Counter)
        for e in audit.events:groups[e['request_id']].append(e)
        for e in audit.http:
            if 'body_base64' in e:
                raw=base64.b64decode(e['body_base64']);assert raw.decode()==e['body_utf8']
                assert sha256(raw).hexdigest()==e['sha256_original'] and not e['sensitive_redaction_applied']
                payload=json.loads(raw)
            if e['event']=='http_request':
                q=json.loads(payload['messages'][1]['content'])['question'];group=groups[sha256(q.encode()).hexdigest()]
                name='selection_request' if e['phase']=='evidence_selection' else 'generation_request'
                assert payload['messages']==next(s['messages'] for s in group if s['event']==name)
                assert {k:v for k,v in payload.items() if k!='messages'}=={'model':'deepseek-flash','max_tokens':1200,
                    'temperature':0,'stream':False,'response_format':{'type':'json_object'},'thinking':{'type':'disabled'}}
            if e['event']=='http_response':
                success.append(payload)
                for k in ('prompt_tokens','completion_tokens','total_tokens'):by_phase[e['phase']][k]+=payload['usage'][k]
        usage={k:sum(r['usage'][k] for r in success) for k in ('prompt_tokens','completion_tokens','total_tokens')}
        assert run['total_usage_both_stages']==usage
        for r in run['records']:
            q=r['question'];result=r['result'];group=groups[sha256(q.encode()).hexdigest()]
            if result['status'] in {'not_run','audit_error','orchestration_error'}:continue
            payload=json.loads(expected[q]['messages'][1]['content']);evidence=payload['evidence']
            assert result['retrieved']==evidence
            request=next(s for s in group if s['event']=='selection_request')
            assert request['messages']==expected[q]['messages']
            generation=next((s for s in group if s['event']=='generation_raw_response'),None)
            if generation is not None:
                final_request=next(s for s in group if s['event']=='generation_request')
                selected=next(s['selection'] for s in group if s['event']=='selection_parsed_plan')
                # Independent reference reconstruction from immutable original source_units/prompt.
                by_id={u['unit_id']:u for u in payload['source_units']}
                ids=list(dict.fromkeys(uid for p in selected['parts'] for uid in p['unit_ids']))
                reference=[{'role':'system','content':(runtime/'generation_prompt.txt').read_text(encoding='utf-8')},
                    {'role':'user','content':json.dumps({'question':q,'evidence':evidence,'evidence_plan':{
                        'question_parts':payload['question_parts'],'selection':selected,'selected_units':[by_id[i] for i in ids],
                        'notice':'Fallible model proposal only; independently check the full question and original evidence.'}},ensure_ascii=False)}]
                assert final_request['messages']==reference==final_messages(q,evidence,selected)
                matching=[json.loads(e['body_utf8']) for e in audit.http if e['event']=='http_response' and
                          e['phase']=='answer_generation' and e['question_sha256']==sha256(q.encode()).hexdigest()]
                assert len(matching)==1 and matching[0]['choices'][0]['message']['content']==generation['generation']['content']
                if result['status']=='answered':
                    checked=validate_generation(generation['generation']['content'],evidence)
                    assert all(result[k]==v for k,v in checked.items())
                    preview=next(s['content'] for s in group if s['event']=='deterministic_rendering')
                    assert generation['generation']['content']!=preview
        for p in (trials/server.id).rglob('*'):
            if p.is_file():assert b'SYNTHETIC_UPSTREAM_EXCEPTION_BODY_NOT_FOR_LOG' not in p.read_bytes()
        return {'http_mock_dispatches':len(server.calls),'persisted_reservations':len(audit.reservations),
                'stages':len(audit.events),'reported_usage_synthetic':usage,'synthetic_usage_by_phase':dict(by_phase),
                'audit_complete':anchors['audit_complete'],'chain_and_HTTP_verified':True}
    def trial(name,scenario='success',fault=None):
        server=Server(name,scenario)
        value=ctl.run_trial(runtime,args.app_src,trials,name,'run.json',cfg,server.factory,fault=fault)
        run,anchors,audit,budget,client=value
        info=verify(run,anchors,audit,server)
        return value,server,info
    # All checks execute under hard no-credentials/no-real-transport guards.
    with patch.object(Settings,'from_env',side_effect=AssertionError('No ENV credentials')), \
         patch('dotenv.load_dotenv',side_effect=AssertionError('No dotenv')), \
         patch('httpx.AsyncHTTPTransport',side_effect=AssertionError('No real upstream transport')), \
         patch('httpx.HTTPTransport',side_effect=AssertionError('No real upstream transport')), \
         patch('socket.socket.connect',new=protected_connect), \
         patch.object(Path,'open',protected_open):
        value,server,info=trial('full40_80_success')
        run,anchors,audit,budget,client=value
        assert len(server.calls)==run['reserved_attempts']==client.actual_calls==80
        assert len(run['records'])==40 and all(r['result']['status']=='answered' for r in run['records'])
        assert len(audit.events)==360 and [server.calls[i-1]['ordinal'] for i in (24,25,79,80)]==[24,25,79,80]
        results.append({'check':'full40_mock80_and_actual_prompt_layout','pass':True,**info})
        # Three independent guards: outer durable budget, original client80 and recorder80.
        messages=inputs[0]['messages'];calls_before=len(server.calls)
        probe=Mock()
        for name,action in (
            ('outer_budget81',lambda:budget.wrap('evidence_selection',probe).generate(messages)),
            ('planned_client81',lambda:client.client.generate(messages)),
            ('recorder81',lambda:RecordedClient(cfg,'evidence_selection',io.StringIO(),set(expected),
                {(f'role{i}',f'q{i}') for i in range(80)},upstream_factory=server.factory).generate(messages))):
            try:action();raise AssertionError('Must block81')
            except LLMError:pass
            assert len(server.calls)==calls_before
            results.append({'check':name,'pass':True,'dispatches_before':80,'dispatches_after':80})
        probe.generate.assert_not_called()
        for new_output in ('run.json','another_filename.json'):
            try:
                ctl.run_trial(runtime,args.app_src,trials,'full40_80_success',new_output,cfg,server.factory)
                raise AssertionError('Restart must block')
            except ctl.TrialBlocked:pass
        assert len(server.calls)==80
        results.append({'check':'restart_same_trial_even_changed_filename_blocked','pass':True})
        # Standalone duplicate reservation: inner mock called once only.
        folder=trials/'duplicate_guard';folder.mkdir();da=ctl.DurableAudit(folder)
        b=ctl.Budget80('duplicate_guard',expected,da);inner=Mock();guard=b.wrap('evidence_selection',inner)
        guard.generate(messages)
        try:guard.generate(messages);raise AssertionError('duplicate allowed')
        except LLMError:pass
        assert b.attempts==1 and inner.generate.call_count==1
        results.append({'check':'duplicate_identity_blocked_before_dispatch','pass':True,'inner_dispatches':1})
        value,server,info=trial('missing_part_skip','unsupported')
        target=next(r for r in value[0]['records'] if r['id']=='EXP-R06')
        assert target['result']['status']=='insufficient_evidence' and target['result']['claims']==[]
        assert not any(x['id']=='EXP-R06' and x['phase']=='answer_generation' for x in server.calls)
        assert len(server.calls)==79
        results.append({'check':'unsupported_part_skips_second_stage_no_filler','pass':True,**info})
        for phase in ('selection','generation'):
            for cause in ('503','429','timeout','network'):
                name=phase+'_'+cause;value,server,info=trial(name,phase+':'+cause)
                first=value[0]['records'][0]['result'];later=value[0]['records'][1:]
                assert first['status']=='llm_error' and all(r['result']['status']=='not_run' for r in later)
                assert len(server.calls)==(1 if phase=='selection' else 2)
                if phase=='generation':assert any(e['event']=='selection_raw_response' for e in value[2].events)
                results.append({'check':name+'_stop_no_retry','pass':True,**info})
        for phase,cause in (('selection','invalid_json'),('selection','invalid_contract'),('generation','invalid_json'),
                           ('generation','bad_quote'),('selection','truncated'),('generation','truncated')):
            name=phase+'_'+cause;value,server,info=trial(name,phase+':'+cause)
            assert value[0]['records'][0]['result']['status']=='invalid_output'
            assert all(r['result']['status']=='answered' for r in value[0]['records'][1:])
            assert len(server.calls)==(79 if phase=='selection' else 80)
            results.append({'check':name+'_first_raw_retained_no_repair','pass':True,**info})
        for name,fault,expected_dispatch in (
            ('reservation_write_before_dispatch',('reservations',1),0),
            ('reservation_fsync_before_dispatch',('reservations_fsync',1),0),
            ('HTTP_write_before_dispatch',('http',1),0),
            ('HTTP_write_after_dispatch',('http',2),1),
            ('stage_write_before_dispatch',('stages',1),0),
            ('stage_write_after_dispatch',('stages',2),1),
            ('checkpoint_failure_after_answer',('checkpoint',1),2)):
            value,server,info=trial(name,fault=fault)
            assert value[1]['stopped'] and value[2].fatal and len(server.calls)==expected_dispatch
            assert all(r['result']['status']=='not_run' for r in value[0]['records'][1:])
            try:ctl.run_trial(runtime,args.app_src,trials,name,'different.json',cfg,server.factory);raise AssertionError('Restart allowed')
            except ctl.TrialBlocked:pass
            results.append({'check':name+'_stop_and_no_restart','pass':True,**info})
        # Explicit uncertain delivery, represented by a request dispatched then no response.
        unknown=ctl.load(trials/'generation_timeout/anchors.json')
        assert unknown['needs_manual_reconciliation'] and unknown['stopped']
        results.append({'check':'unknown_delivery_keeps_reservation_and_no_auto_resume','pass':True})
    # Relocation subprocess proves runtime does not depend on the old absolute prompt path.
    with tempfile.TemporaryDirectory() as folder:
        moved=Path(folder)/'relocated_runtime';shutil.copytree(runtime,moved)
        code='''import json,sys\nfrom pathlib import Path\nsys.dont_write_bytecode=True\nsys.path[:0]=[sys.argv[1],sys.argv[2]]\nimport controller80\nfrom unittest.mock import patch\nfrom rag_app.config import Settings\nwith patch.object(Settings,"from_env",side_effect=AssertionError("No ENV")),patch("httpx.AsyncHTTPTransport",side_effect=AssertionError("No network")):\n inputs,p=controller80.initialize(Path(sys.argv[1]),Path(sys.argv[2]))\n import planned_generation\n assert planned_generation.PROMPT_PATH==Path(sys.argv[1])/"generation_prompt.txt"\n for r in inputs:\n  u=json.loads(r["messages"][1]["content"]);id=u["source_units"][0]["unit_id"]\n  plan={"parts":[{"part_id":x["part_id"],"supported":True,"unit_ids":[id]} for x in u["question_parts"]]}\n  m=planned_generation.final_messages(u["question"],u["evidence"],plan)\n  assert m[0]["content"]==(Path(sys.argv[1])/"generation_prompt.txt").read_text(encoding='utf-8')\n print("Relocated40 dynamic final messages loaded verified prompt; no ENV or network.")\n'''
        relocated=subprocess.run([sys.executable,'-c',code,str(moved.resolve()),str(args.app_src.resolve())],capture_output=True,text=True)
        assert relocated.returncode==0,relocated.stderr
        # Deleting the prompt is a bounded fault in temporary copy only, not production data.
        (moved/'generation_prompt.txt').unlink()
        bad=subprocess.run([sys.executable,'-c',code,str(moved.resolve()),str(args.app_src.resolve())],capture_output=True,text=True)
        assert bad.returncode!=0 and 'Runtime fingerprint differs' in bad.stderr
    results.append({'check':'relocated_delivery40_messages_and_missing_prompt_fails_closed','pass':True,'stdout':relocated.stdout})
    summary={'status':'OFFLINE_ORCHESTRATION_PREFLIGHT_PASSED','checks':len(results),'all_passed':True,
        'results':results,'main_trial_mock_HTTP_dispatches':80,'main_trial_questions':40,'main_trial_stages':360,
        'real_model_API_calls':0,'real_upstream_HTTP_requests':0,'ENV_or_keys_read':False,
        'all_output_answers_and_usage_are_synthetic_not_accuracy_or_cost_results':True,
        'candidate40_scores':'pending','new_paid_execution_authorized':False,
        'total_mock_dispatches_all_guard_scenarios':len(dispatch_history)}
    with (out/'c_controller_preflight_results.json').open('x',encoding='utf-8') as f:json.dump(summary,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in summary.items() if k!='results'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
