"""Portable isolated orchestration. No credential loader, real transport fallback or paid CLI.

Call run_trial only with an explicitly supplied config and transport factory. This
module does not authorize a run; the delivered entry point is offline preflight.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json,os,re
from pathlib import Path
import sys

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(path):return sha256(path.read_bytes()).hexdigest()
def load(path):return json.loads(path.read_bytes())

class AuditFault(RuntimeError):pass
class TrialBlocked(RuntimeError):pass

class DurableAudit:
    """Any append/checkpoint failure is sticky, even when QAService catches it."""
    def __init__(self,folder,fault=None):
        self.folder=folder;self.fault=fault;self.counts=Counter();self.fatal=False;self.failure=None
        self.events=[];self.http=[];self.reservations=[]
    def trigger(self,channel):
        self.counts[channel]+=1
        if self.fault==(channel,self.counts[channel]):raise OSError('SYNTHETIC_AUDIT_FAILURE_DO_NOT_LEAK_BODY')
    def fail(self,channel):
        self.fatal=True;self.failure={'kind':'audit_write_failure','channel':channel,
            'error':'Audit persistence failed; stop, do not retry or resume.'}
    def append(self,channel,value):
        if self.fatal:raise AuditFault('Audit already failed.')
        try:
            self.trigger(channel)
            with (self.folder/(channel+'.jsonl')).open('ab') as f:
                f.write(canonical(value)+b'\n');f.flush();self.trigger(channel+'_fsync');os.fsync(f.fileno())
        except BaseException:
            self.fail(channel);raise AuditFault('Audit append failed.') from None
        if channel=='stages':self.events.append(deepcopy(value))
        elif channel=='http':self.http.append(deepcopy(value))
        elif channel=='reservations':self.reservations.append(deepcopy(value))
    def checkpoint(self,name,value):
        if self.fatal:raise AuditFault('Audit already failed.')
        try:
            self.trigger('checkpoint')
            # Per-checkpoint immutable snapshots avoid overwriting first responses.
            path=self.folder/(name+f'.checkpoint{self.counts["checkpoint"]:03}.json')
            with path.open('xb') as f:f.write(canonical(value)+b'\n');f.flush();os.fsync(f.fileno())
        except BaseException:
            self.fail('checkpoint');raise AuditFault('Checkpoint failed.') from None

class JSONLStream:
    """File-like facade: original HTTP recorder emits one JSON event per write."""
    def __init__(self,audit):self.audit=audit
    def write(self,value):
        for line in value.splitlines():
            if line.strip():self.audit.append('http',json.loads(line))
    def flush(self):pass # append already flushes + fsyncs each event.

def initialize(runtime,app_src):
    runtime=Path(runtime).resolve();app_src=Path(app_src).resolve()
    for row in load(runtime/'runtime_manifest.json')['files']:
        if digest(runtime/row['path'])!=row['sha256']:raise TrialBlocked('Runtime fingerprint differs.')
    protocol=load(runtime/'generation_protocol.json')
    for name,value in protocol['app_source_sha256'].items():
        raw=(app_src/'rag_app'/name).read_bytes().replace(b'\r\n',b'\n')
        if sha256(raw).hexdigest()!=value:raise TrialBlocked('Application fingerprint differs.')
    sys.path[:0]=[str(runtime/'method'),str(app_src)]
    import planned_generation,selection_adapter,coverage_contract,http_audit
    # Prevent an import cache from silently selecting a previous machine's method.
    for module in (planned_generation,selection_adapter,coverage_contract,http_audit):
        if Path(module.__file__).resolve().parent!=runtime/'method':raise TrialBlocked('Wrong method module layout/cache.')
    if planned_generation.PROMPT_PATH.resolve()!=runtime/'generation_prompt.txt':raise TrialBlocked('Generation prompt layout differs.')
    if not planned_generation.PROMPT_PATH.is_file():raise TrialBlocked('Missing generation prompt.')
    inputs=load(runtime/'model_inputs40.json')['requests']
    if len(inputs)!=40 or len({r['id'] for r in inputs})!=40:raise TrialBlocked('Expected exact40.')
    return inputs,protocol

class Budget80:
    def __init__(self,trial_id,expected,audit):
        self.trial_id=trial_id;self.expected=expected;self.audit=audit;self.seen=set();self.attempts=0
    def wrap(self,role,client):
        owner=self
        class Guard:
            def generate(self,messages):
                from rag_app.llm import LLMError
                from planned_generation import final_messages
                if owner.audit.fatal:raise LLMError('Audit failure blocks dispatch.')
                # Budget checked first, so attempt81 cannot become duplicate/retrieval confusion.
                if owner.attempts>=80:raise LLMError('Full40 80-attempt cap reached.')
                p=json.loads(messages[-1]['content']);q=p['question'];identity=(owner.trial_id,q,role)
                if q not in owner.expected or identity in owner.seen:raise LLMError('Unexpected or duplicate stage.')
                if role=='evidence_selection':
                    if messages!=owner.expected[q]['messages']:raise LLMError('Frozen selection messages differ.')
                elif role=='answer_generation':
                    if (owner.trial_id,q,'evidence_selection') not in owner.seen:raise LLMError('Selection must precede generation.')
                    evidence=json.loads(owner.expected[q]['messages'][1]['content'])['evidence']
                    if set(p)!={'question','evidence','evidence_plan'} or p['evidence']!=evidence:
                        raise LLMError('Frozen final evidence differs.')
                    if messages!=final_messages(q,evidence,p['evidence_plan']['selection']):raise LLMError('Final messages differ.')
                else:raise LLMError('Unknown stage.')
                reservation={'trial_id':owner.trial_id,'id':owner.expected[q]['id'],'phase':role,
                    'attempt_ordinal':owner.attempts+1,'question_sha256':sha256(q.encode()).hexdigest(),
                    'messages_sha256':sha256(canonical(messages)).hexdigest(),'state':'reserved_before_dispatch',
                    'uncertain_attempt_never_auto_resent':True}
                owner.audit.append('reservations',reservation) # fsync before the recorder/network can run.
                owner.seen.add(identity);owner.attempts+=1
                return client.generate(messages)
        return Guard()

def validate_authorization(runtime,trial_id,authorization):
    if (not isinstance(authorization,dict) or authorization.get('approved') is not True
            or not isinstance(authorization.get('user_statement'),str)
            or not authorization['user_statement'].strip()
            or authorization.get('trial_id')!=trial_id
            or authorization.get('max_provider_attempts')!=80
            or authorization.get('runtime_manifest_sha256')!=digest(Path(runtime)/'runtime_manifest.json')):
        raise TrialBlocked('Explicit full40 approval bound to this trial/runtime is required.')


def run_trial(runtime,app_src,trial_root,trial_id,output_name,cfg,transport_factory,*,fault=None,authorization=None):
    """No auto-resume; trial marker independent of output_name; supplied transports only."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',trial_id):raise TrialBlocked('Invalid trial ID.')
    if authorization is not None:validate_authorization(runtime,trial_id,authorization)
    if Path(output_name).name!=output_name or not output_name.endswith('.json'):raise TrialBlocked('Use local output filename.')
    inputs,protocol=initialize(runtime,app_src);runtime=Path(runtime).resolve()
    configured={'provider':cfg.base_url,'requested_model':cfg.model,'max_output_tokens':cfg.max_tokens,
                'timeout_seconds':cfg.timeout,'thinking':cfg.thinking,'json_mode':cfg.json_mode}
    if any(v!=protocol[k] for k,v in configured.items()):raise TrialBlocked('Frozen generation parameters differ.')
    # Caller must supply a transport, never silently fall back to production networking.
    if transport_factory is None:raise TrialBlocked('An explicitly supplied audited transport factory is required.')
    trial=Path(trial_root)/trial_id;trial.mkdir(parents=True,exist_ok=True)
    marker=trial/'TRIAL_STARTED.json'
    try:
        with marker.open('xb') as f:
            f.write(canonical({'trial_id':trial_id,'output_name':output_name,'max_attempts':80,
                'runtime_manifest_sha256':digest(runtime/'runtime_manifest.json'),
                'no_auto_restart_or_resume':True})+b'\n');f.flush();os.fsync(f.fileno())
        # Persist the directory entry where supported on the local filesystem.
        # Windows cannot open directory handles with os.open. The exclusive
        # marker file is still flushed/fsynced above; directory fsync is POSIX-only.
        if os.name != 'nt':
            fd=os.open(trial,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
    except FileExistsError:raise TrialBlocked('Trial already started; changing output filename cannot restart it.') from None
    audit=DurableAudit(trial,fault);expected={json.loads(r['messages'][1]['content'])['question']:r for r in inputs}
    from planned_generation import PlannedGenerationClient
    from selection_adapter import answer_with_trace,verify_events
    from http_audit import RecordedClient
    from rag_app.service import QAService
    from rag_ingest.temporal import load_temporal_catalog
    class Frozen:
        def retrieve(self,q,top_k,*,collection,arm):
            if (top_k,collection,arm)!=(8,'fixed_150_overlap_30','enhanced') or q not in expected:
                raise ValueError('Frozen retrieval differs.')
            return json.loads(expected[q]['messages'][1]['content'])['evidence']
    budget=Budget80(trial_id,expected,audit);shared=set();stream=JSONLStream(audit)
    selector=RecordedClient(cfg,'evidence_selection',stream,set(expected),shared,upstream_factory=transport_factory)
    generator=RecordedClient(cfg,'answer_generation',stream,set(expected),shared,upstream_factory=transport_factory)
    client=PlannedGenerationClient(budget.wrap('evidence_selection',selector),budget.wrap('answer_generation',generator),
                                   lambda e:audit.append('stages',e))
    service=QAService(Frozen(),client,load_temporal_catalog(runtime/'temporal_catalog.json'),cfg)
    run={'trial_id':trial_id,'kind':'INJECTED_TRANSPORT_ORCHESTRATION_NOT_MODEL_SCORES',
         'max_provider_attempts':80,'runtime_manifest_sha256':digest(runtime/'runtime_manifest.json'),
         'real_model_calls_asserted_by_offline_entry':0,'records':[],'candidate_scores':'pending_real_authorized_run'}
    if authorization is not None:
        # Authorized real runs must not inherit the offline entry's zero-call label.
        run.pop('real_model_calls_asserted_by_offline_entry')
        run.update(kind='AUTHORIZED_FULL40_GENERATIVE_RAG_FIRST_RESPONSES',execution_mode='paid',
            authorization_sha256=sha256(canonical(authorization)).hexdigest(),
            approval_statement=authorization['user_statement'])
    stopped=False
    for request in inputs:
        q=json.loads(request['messages'][1]['content'])['question'];result=None
        if stopped:
            result={'status':'not_run','answer':'','claims':[],'citations':[],
                    'error':'Stopped after infrastructure or audit failure.'}
        else:
            try:
                result=answer_with_trace(service,q)
            except BaseException:
                # Never expose exception bodies or turn a persistence failure into refusal.
                result={'status':'audit_error' if audit.fatal else 'orchestration_error','answer':'','claims':[],
                        'citations':[],'error':'Experimental orchestration stopped; audit separately.'}
            if audit.fatal:
                result={'status':'audit_error','answer':'','claims':[],'citations':[],
                        'error':'Audit persistence failed; first attempted requests are never retried.'}
            if result['status'] in {'llm_error','retrieval_error','audit_error','orchestration_error'}:stopped=True
        run['records'].append({'id':request['id'],'question':q,'result':result})
        run['reserved_attempts']=budget.attempts
        if authorization is not None:run['provider_client_attempts']=budget.attempts
        raw_responses=[e['generation'] for e in audit.events if e['event'] in {'selection_raw_response','generation_raw_response'}]
        run['stage_reported_usage']={k:sum(r.get('usage',{}).get(k,0) for r in raw_responses)
                                    for k in ('prompt_tokens','completion_tokens','total_tokens')}
        # HTTP is authoritative even for a billed response rejected before ChatClient
        # can return (e.g. finish_reason=length); never silently drop its usage.
        bodies=[json.loads(e['body_utf8']) for e in audit.http if e['event']=='http_response']
        run['total_usage_both_stages']={k:sum(r.get('usage',{}).get(k,0) for r in bodies)
                                      for k in ('prompt_tokens','completion_tokens','total_tokens')}
        if not audit.fatal:
            try:audit.checkpoint(Path(output_name).stem,run)
            except AuditFault:stopped=True
    tail=verify_events(audit.events,len(audit.events),audit.events[-1]['event_sha256'] if audit.events else '0'*64)
    anchors={'trial_id':trial_id,'event_count':len(audit.events),'final_event_sha256':tail,
        'persisted_reservations':len(audit.reservations),'audit_complete':not audit.fatal,
        'stopped':stopped,'audit_failure':audit.failure,
        'needs_manual_reconciliation':audit.fatal or any(e['event']=='http_error' for e in audit.http),
        'HTTP_request_events':sum(e['event']=='http_request' for e in audit.http),
        'HTTP_success_events':sum(e['event']=='http_response' for e in audit.http)}
    # Emergency summary uses a separate file, never truncates any recorded first response.
    # A genuinely unavailable disk may prevent this too; durable marker still forbids restart.
    for name,value in ((output_name,run),('anchors.json',anchors)):
        with (trial/name).open('xb') as f:f.write(canonical(value)+b'\n');f.flush();os.fsync(f.fileno())
    return run,anchors,audit,budget,client
