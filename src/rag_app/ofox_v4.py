"""V4: one fresh EXP11 joint_pairs8 two-stage acceptance, at most two dispatches."""
from contextlib import closing, contextmanager
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3
import stat

from . import demo_budget as b, ofox_probe as v2, ofox_azure_probe as v3
from .llm import GenerationError

V3_PATH = b._account_home()/'.local/state/cs5481/ofox-exp11-azure-v3.sqlite3'
V3_SHA256 = 'cd63e23d6368c4c84106acad9815965ba82a4c56342308dc3e7901476c07ef57'
V3_SESSION = 'cs5481_ofox_exp11_azure_v3_01'
V3_SOURCE = '3bb351164b141f30a867661403683c7353c5618e42d39f6206bbd428705b19ec'
PROBE_PATH = b._account_home()/'.local/state/cs5481/ofox-exp11-full-v4.sqlite3'
SESSION_ID = 'cs5481_ofox_exp11_full_v4_01'


def _unique_json(content):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise b.BudgetBlocked('Duplicate request JSON keys are forbidden.')
            result[key] = value
        return result
    return json.loads(content, object_pairs_hook=pairs)


def prior_incidents():
    prior = v3.prior_incidents()
    try:
        if (not stat.S_ISREG(V3_PATH.lstat().st_mode) or V3_PATH.resolve() != V3_PATH.absolute()
                or any(b._exists(Path(str(V3_PATH)+s)) for s in ('-wal','-shm','-journal','.provisioning'))
                or sha256(V3_PATH.read_bytes()).hexdigest() != V3_SHA256):
            raise b.BudgetBlocked('V3 incident binding differs.')
        with closing(sqlite3.connect(V3_PATH.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            if (db.execute('SELECT state,session_id,fingerprint,registry FROM meta').fetchall()
                    != [('stopped',V3_SESSION,V3_SOURCE,str(V3_PATH))]
                    or db.execute('SELECT controller,max_attempts FROM guard_policy').fetchall()!=[('exp11_azure_selection_v3',1)]
                    or db.execute('SELECT ordinal,case_id,stage,state FROM attempts').fetchall()!=[(1,'EXP11','selection','ok')]):
                raise b.BudgetBlocked('V3 is not the approved stopped planning success.')
            rows=db.execute('SELECT record FROM attempt_diagnostics_v1 WHERE ordinal=1').fetchall()
            if len(rows)!=1 or json.loads(rows[0][0]).get('http_status')!=200:
                raise b.BudgetBlocked('V3 success evidence differs.')
        if sha256(V3_PATH.read_bytes()).hexdigest()!=V3_SHA256:
            raise b.BudgetBlocked('V3 changed during inspection.')
    except (OSError,sqlite3.Error,ValueError,TypeError):
        raise b.BudgetBlocked('Cannot verify original v3 incident.') from None
    return [*prior,dict(registry=str(V3_PATH),sha256=V3_SHA256,session_id=V3_SESSION,
                       source_sha256=V3_SOURCE,consumed_attempts=1)]


def consent_statement():
    return (f'I authorize one fresh full EXP11 joint_pairs8 acceptance, selection then generation, '
        f'maximum two total dispatches, Azure Foundry, no retries or fallback, session {SESSION_ID} at {PROBE_PATH}; '
        f'preserve stopped v1 {v2.PRIOR_SHA256}, v2 {v3.V2_SHA256}, v3 {V3_SHA256}, without reusing approvals, slots or plans. '
        'I accept USD 0.50 financial tolerance, not a guaranteed monetary cap, and cache-write/billing uncertainty.')


def approval_template():
    return dict(approved=False,statement=consent_statement(),session_id=SESSION_ID,
        authorized_registry=str(PROBE_PATH),source_sha256=b.fingerprint(),provider=b.PROVIDER,
        model=b.MODEL,profile=b.PROFILE,max_attempts=2)


class AcceptanceLedger(b.SessionLedger):
    CONTROLLER='exp11_full_azure_v4'
    ROUTE='azure_foundry'
    MAX_ATTEMPTS=2
    STOP_AFTER_FINISH=True

    @classmethod
    def create_extension(cls,db):
        db.execute('CREATE TABLE stage_responses (ordinal INTEGER PRIMARY KEY, stage TEXT UNIQUE, data TEXT NOT NULL)')

    def __init__(self,path):
        super().__init__(path)
        if self.path!=PROBE_PATH or PROBE_PATH.resolve()!=PROBE_PATH.absolute():
            raise b.BudgetBlocked('Only the fixed canonical v4 path is permitted.')
        prior_incidents()

    @classmethod
    def provision(cls,path,approval):
        prior_incidents();expected=approval_template();expected['approved']=True
        if Path(path).absolute()!=PROBE_PATH or approval!=expected:
            raise b.BudgetBlocked('Fresh exact v4 scope/source/path consent required.')
        return super().provision(path,approval)

    @contextmanager
    def transaction(self):
        prior_incidents()
        with super().transaction() as db:
            if db.execute('SELECT session_id FROM meta').fetchone()!=(SESSION_ID,):
                raise b.BudgetBlocked('V4 session binding differs.')
            yield db

    def check(self):
        super().check()
        with self.transaction() as db:
            if db.execute('SELECT count(*) FROM cases').fetchone()!=(0,) or db.execute('SELECT count(*) FROM attempts').fetchone()!=(0,):
                raise b.BudgetBlocked('V4 already started; no restart or resume.')

    def begin(self,question):
        if question!=b.questions()['EXP11']:
            raise b.BudgetBlocked('Only exact EXP11 is authorized.')
        return super().begin(question)

    def reserve(self,claim,stage):
        if claim[0]!='EXP11' or stage not in {'selection','generation'}:
            raise b.BudgetBlocked('Only fresh EXP11 selection then generation is authorized.')
        return super().reserve(claim,stage)

    def validate_request(self,request):
        if 'x-ofoxai-provider-type' in request.headers:
            raise b.BudgetBlocked('Routing headers are not approved.')
        messages=v2.selection_messages()
        actual=_unique_json(request.content)
        payload=_unique_json(actual['messages'][1]['content'])
        if 'evidence_plan' in payload:
            with self.transaction() as db:
                row=db.execute("SELECT r.data FROM stage_responses r JOIN attempts a ON a.ordinal=r.ordinal WHERE r.stage='selection' AND a.state='ok'").fetchone()
            if row is None:
                raise b.BudgetBlocked('No fresh accepted v4 plan; generation forbidden.')
            record=json.loads(row[0])
            if record['validation']!='accepted':
                raise b.BudgetBlocked('Planning did not support full EXP11.')
            from planned_generation import final_messages
            selected=json.loads(messages[1]['content'])
            messages=final_messages(selected['question'],selected['evidence'],record['plan'])
        expected=dict(model=b.MODEL,messages=messages,max_completion_tokens=1200,reasoning_effort='low',
            response_format={'type':'json_object'},stream=False,extra_body={'provider':{'type':'azure_foundry','fallback':[]}})
        # Preserve the shared retrieval interface's 1e-5 distance tolerance;
        # pin every other byte-derived field, prompt, unit, role and parameter.
        given = payload
        wanted = json.loads(messages[1]['content'])
        try:
            if len(given['evidence']) != len(wanted['evidence']):
                raise ValueError
            for got, frozen in zip(given['evidence'], wanted['evidence'], strict=True):
                d = got['distance']
                if type(d) not in (int,float) or not math.isfinite(d) or abs(d-frozen['distance']) >= 1e-5:
                    raise ValueError
                got['distance'] = frozen['distance']  # comparison copy only, never alter sent request
            if given != wanted or len(actual['messages']) != 2:
                raise ValueError
            for got, frozen in zip(actual['messages'], messages, strict=True):
                if set(got) != set(frozen) or got['role'] != frozen['role']:
                    raise ValueError
            if actual['messages'][0] != messages[0]:
                raise ValueError
        except (ValueError,TypeError,KeyError):
            raise b.BudgetBlocked('V4 request evidence/prompt differs.') from None
        actual['messages'] = messages
        if request.method!='POST' or str(request.url)!=b.PROVIDER+'/chat/completions' or actual!=expected:
            raise b.BudgetBlocked('Request differs from fresh reviewed v4 workflow.')

    def accept_response(self,ordinal,data):
        content=data['choices'][0]['message']['content']
        with self.transaction() as db:
            row=db.execute('SELECT case_id,stage,state FROM attempts WHERE ordinal=?',(ordinal,)).fetchone()
        if row is None or row[0]!='EXP11' or row[2]!='reserved':
            raise b.BudgetBlocked('Response has no live v4 reservation.')
        stage=row[1]
        payload=json.loads(v2.selection_messages()[1]['content'])
        safe=dict(model=b.MODEL,response_sha256=sha256(content.encode()).hexdigest(),validation='invalid')
        usage=data.get('usage')
        safe['usage']={k:v for k,v in usage.items() if k in {'prompt_tokens','completion_tokens','total_tokens'} and type(v) is int and v>=0} if isinstance(usage,dict) else {}
        safe['usage_details']={}
        if isinstance(usage,dict):
            for group,fields in {'prompt_tokens_details':('cached_tokens','cache_write_tokens'),'completion_tokens_details':('reasoning_tokens',)}.items():
                values=usage.get(group)
                if isinstance(values,dict):safe['usage_details'][group]={k:v for k,v in values.items() if k in fields and type(v) is int and v>=0}
        try:
            parsed=json.loads(content)
            if stage=='selection':
                from coverage_contract import render_selection
                checked=render_selection(parsed,payload['question'],payload['evidence'])
                safe['plan']={'parts':[{k:p[k] for k in ('part_id','supported','unit_ids')} for p in parsed['parts']]}
                safe['validation']='accepted' if checked['declared_coverage_complete'] else 'refused'
            else:
                from .grounding import validate_generation
                checked=validate_generation(content,payload['evidence'])
                safe['validated']=checked
                safe['validation']='accepted' if checked['status']=='answered' else 'refused'
        except (ValueError,TypeError,KeyError,GenerationError):
            pass  # no raw body or exception text, even for malformed planning/citations
        with self.transaction() as db:
            db.execute('INSERT INTO stage_responses VALUES(?,?,?)',(ordinal,stage,json.dumps(safe,allow_nan=False)))
        if safe['validation']!='accepted':
            raise GenerationError('V4 response failed coverage, refusal or citation validation.')

    def responses(self):
        with self.transaction() as db:
            return [dict(ordinal=n,stage=s,**json.loads(data)) for n,s,data in db.execute('SELECT * FROM stage_responses ORDER BY ordinal')]


def prepare():
    return dict(prior_incidents=prior_incidents(),approval=approval_template(),provider_type='azure_foundry',
        registry_exists=b._exists(PROBE_PATH),fence_exists=b._exists(b._provision_marker(PROBE_PATH)),
        endpoint=b.PROVIDER+'/chat/completions',expected_dispatches=2,maximum_dispatches=2)


def create_service(settings,*,transport=None,credential_file=None):
    from .ofox_demo import _service_for_controller
    ledger=AcceptanceLedger(PROBE_PATH)
    def key_loader():
        if credential_file is None:return settings.api_key
        from dotenv import dotenv_values
        return (dotenv_values(Path(credential_file),interpolate=False).get('OFOX_API_KEY') or '').strip()
    return _service_for_controller(settings,ledger,transport=transport,key_loader=key_loader)


def run_once(settings,*,transport=None,credential_file=None):
    service=create_service(settings,transport=transport,credential_file=credential_file)
    return service.answer_question(b.questions()['EXP11'])


if __name__=='__main__':
    import argparse
    from .config import Settings
    parser=argparse.ArgumentParser(description='V4 full EXP11 preparation/explicit activation/one submission.')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare',action='store_true');mode.add_argument('--approval-file',type=Path);mode.add_argument('--execute',action='store_true')
    parser.add_argument('--experiment-dir',type=Path);parser.add_argument('--cache-dir',type=Path);parser.add_argument('--env-file',type=Path)
    args=parser.parse_args()
    if args.prepare:print(json.dumps(prepare(),indent=2))
    elif args.approval_file:
        AcceptanceLedger.provision(PROBE_PATH,json.loads(args.approval_file.read_bytes()));print('V4 activated; zero provider attempts.')
    else:
        if args.experiment_dir is None or args.cache_dir is None:parser.error('Explicit verified experiment/cache paths required.')
        print(json.dumps(run_once(Settings(experiment_dir=args.experiment_dir,cache_dir=args.cache_dir),credential_file=args.env_file),indent=2))
