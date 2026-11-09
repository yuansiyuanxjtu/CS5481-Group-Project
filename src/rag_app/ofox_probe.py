"""Version 2: one lifetime EXP11 selection dispatch, never answer generation.

No activation on import. The original v1 incident is read-only and immutable.
"""
from contextlib import contextmanager, closing
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import stat
import time

import httpx

from . import demo_budget as b
from .ofox_demo import OfoxChatClient
from .ofox_diagnostics import Diagnostic

PRIOR_PATH = b.DEFAULT_LEDGER
PRIOR_SHA256 = '8e48af9ec8958c1f86d0ac86c23902a0458ccd544b4711dfb5c6da9c0e69da23'
PRIOR_SESSION = 'cs5481_ofox_20261108_01'
PRIOR_SOURCE = '000266d6a0b31447c9bc47c72cfbbf8712ef8f70945877a528c473ae54952eee'
PROBE_PATH = b._account_home()/'.local/state/cs5481/ofox-exp11-selection-v2.sqlite3'
SESSION_ID = 'cs5481_ofox_exp11_selection_v2_01'


def prior_incident():
    """Never use v1's write-capable transaction API; reject WAL/aliases/drift."""
    try:
        if (not stat.S_ISREG(PRIOR_PATH.lstat().st_mode)
                or PRIOR_PATH.resolve() != PRIOR_PATH.absolute()
                or any(b._exists(Path(str(PRIOR_PATH)+suffix)) for suffix in ('-wal','-shm','-journal','.provisioning'))
                or sha256(PRIOR_PATH.read_bytes()).hexdigest() != PRIOR_SHA256):
            raise b.BudgetBlocked('Original incident binding differs.')
        with closing(sqlite3.connect(PRIOR_PATH.as_uri()+'?mode=ro&immutable=1', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            meta = db.execute('SELECT state,session_id,fingerprint,registry FROM meta').fetchall()
            rows = db.execute('SELECT ordinal,case_id,stage,state FROM attempts ORDER BY ordinal').fetchall()
            if (meta != [('stopped', PRIOR_SESSION, PRIOR_SOURCE, str(PRIOR_PATH))]
                    or rows != [(1,'EXP11','selection','error')]):
                raise b.BudgetBlocked('Original incident is not the approved stopped record.')
        if sha256(PRIOR_PATH.read_bytes()).hexdigest() != PRIOR_SHA256:
            raise b.BudgetBlocked('Original incident changed during inspection.')
    except (OSError, sqlite3.Error):
        raise b.BudgetBlocked('Cannot verify original stopped incident.') from None
    return {'registry': str(PRIOR_PATH), 'sha256': PRIOR_SHA256,
            'session_id': PRIOR_SESSION, 'source_sha256': PRIOR_SOURCE, 'consumed_attempts': 1}


def selection_messages():
    from .demo import _load_experiment, JOINT
    _load_experiment()
    from selection_adapter import messages_for_selection
    records = json.loads((JOINT/'model_inputs40.json').read_bytes())['requests']
    row = next(r for r in records if r['id'] == 'EXP11')
    payload = json.loads(row['messages'][1]['content'])
    return messages_for_selection(payload['question'], payload['evidence'])


def consent_statement():
    return (f'I authorize exactly one EXP11 evidence-planning dispatch, no generation, retries or fallback; '
            f'acknowledge immutable prior session {PRIOR_SESSION} at {PRIOR_PATH} SHA256 {PRIOR_SHA256} '
            f'with one consumed attempt; authorize successor {SESSION_ID} at {PROBE_PATH}. '
            'I accept USD 0.50 financial tolerance, not a guaranteed monetary cap, and provider billing uncertainty.')


def approval_template():
    return dict(approved=False, statement=consent_statement(), session_id=SESSION_ID,
        authorized_registry=str(PROBE_PATH), source_sha256=b.fingerprint(), provider=b.PROVIDER,
        model=b.MODEL, profile=b.PROFILE, max_attempts=1)


class ProbeLedger(b.SessionLedger):
    CONTROLLER = 'exp11_selection_v2'
    ROUTE = 'openai'
    MAX_ATTEMPTS = 1
    STOP_AFTER_RECORD = True

    def __init__(self, path):
        super().__init__(path)
        if self.path != PROBE_PATH or PROBE_PATH.resolve() != PROBE_PATH.absolute():
            raise b.BudgetBlocked('Only the fixed canonical v2 registry is permitted.')
        prior_incident()

    @classmethod
    def provision(cls, path, approval):
        prior_incident()
        if Path(path).absolute() != PROBE_PATH:
            raise b.BudgetBlocked('Provision only the fixed canonical v2 path.')
        expected = approval_template()
        expected['approved'] = True
        if approval != expected:
            raise b.BudgetBlocked('A fresh explicit v2 approval must bind the one-request scope.')
        return super().provision(path, approval)

    @contextmanager
    def transaction(self):
        prior_incident()
        with super().transaction() as db:
            if db.execute('SELECT session_id FROM meta').fetchone() != (SESSION_ID,):
                raise b.BudgetBlocked('Successor session binding differs.')
            yield db

    def check(self):
        super().check()
        if self.snapshot()['attempts']:
            raise b.BudgetBlocked('V2 attempt already consumed; no resume.')

    def begin(self, question):
        if question != b.questions()['EXP11']:
            raise b.BudgetBlocked('Only EXP11 is authorized.')
        return super().begin(question)

    def reserve(self, claim, stage):
        if claim[0] != 'EXP11' or stage != 'selection':
            raise b.BudgetBlocked('Only EXP11 selection is authorized; generation is forbidden.')
        return super().reserve(claim, stage)

    def validate_request(self, request):
        if 'x-ofoxai-provider-type' in request.headers:
            raise b.BudgetBlocked('Routing headers are not part of the approved exact request.')
        expected = dict(model=b.MODEL, messages=selection_messages(), max_completion_tokens=1200,
            reasoning_effort='low', response_format={'type':'json_object'}, stream=False,
            extra_body={'provider':{'type':self.ROUTE,'fallback':[]}})
        if request.method != 'POST' or str(request.url) != b.PROVIDER+'/chat/completions' or json.loads(request.content) != expected:
            raise b.BudgetBlocked('V2 request differs from the frozen selection request.')

    def save_first(self, result):
        # The caller supplies only reconstructed, bounded fields, never raw errors.
        with self.transaction() as db:
            db.execute('INSERT INTO results VALUES(?,?)', ('EXP11', json.dumps(result, allow_nan=False)))
            db.execute("UPDATE meta SET state='stopped'")


def prepare():
    prior = prior_incident()
    return {'prior_incident': prior, 'approval': approval_template(),
        'registry_exists': b._exists(PROBE_PATH),
        'fence_exists': b._exists(b._provision_marker(PROBE_PATH)),
        'endpoint': b.PROVIDER+'/chat/completions', 'request_sha256': sha256(json.dumps(
            selection_messages(), ensure_ascii=False).encode()).hexdigest()}


def run_once(*, settings=None, transport=None, credential_file=None):
    """Call only after fresh approval/provisioning. No CLI/env registry override."""
    return _run_once(ProbeLedger(PROBE_PATH), settings=settings, transport=transport, credential_file=credential_file)


def _run_once(ledger, *, settings=None, transport=None, credential_file=None):
    """Shared response preservation; caller supplies its fixed versioned controller."""
    from dataclasses import replace
    from .config import Settings
    ledger.check()  # before dotenv, credential loading, real transport or dispatch
    if transport is not None and not isinstance(transport, httpx.MockTransport):
        raise b.BudgetBlocked('Only MockTransport injection is supported.')
    if credential_file is not None:
        if settings is not None:
            raise b.BudgetBlocked('Do not combine injected settings with a credential file.')
        from dotenv import dotenv_values
        # No environment export/interpolation and no legacy LLM configuration.
        key = dotenv_values(Path(credential_file), interpolate=False).get('OFOX_API_KEY') or ''
    else:
        key = os.environ.get('OFOX_API_KEY', '').strip() if settings is None else settings.api_key
    cfg = replace(settings or Settings(), api_key=key.strip(), base_url=b.PROVIDER,
        model=b.MODEL, timeout=120, max_tokens=1200, thinking='', json_mode=True)
    claim = ledger.begin(b.questions()['EXP11'])
    factory = (lambda: transport) if transport is not None else (lambda: httpx.AsyncHTTPTransport(retries=0, trust_env=False))
    chat = OfoxChatClient(cfg, ledger, claim, factory)
    result = dict(status='failed', requested_model=b.MODEL, returned_model=None,
        usage={}, usage_details={}, usage_completeness='partial_or_unknown', response_sha256=None,
        plan=None, diagnostics=[], elapsed_seconds=0)
    started = time.monotonic()
    phase = 'provider'
    try:
        response = chat.generate(selection_messages())
        result['returned_model'] = response['model']  # adapter permits exact expected identity only
        result['response_sha256'] = sha256(response['content'].encode()).hexdigest()
        usage = response.get('usage')
        if isinstance(usage, dict):
            result['usage'] = {k:v for k,v in usage.items() if k in {'prompt_tokens','completion_tokens','total_tokens'} and type(v) is int and v >= 0}
        if isinstance(usage, dict):
            for group, fields in {'prompt_tokens_details':('cached_tokens','cache_write_tokens'),
                                  'completion_tokens_details':('reasoning_tokens',)}.items():
                values = usage.get(group)
                if isinstance(values, dict):
                    result['usage_details'][group] = {k:v for k,v in values.items() if k in fields and type(v) is int and v >= 0}
        if result['usage']:
            result['usage_completeness'] = 'reported'
        phase = 'plan_json'
        plan = json.loads(response['content'])
        phase = 'plan_contract'
        from coverage_contract import render_selection
        payload = json.loads(selection_messages()[1]['content'])
        render_selection(plan, payload['question'], payload['evidence'])  # validation only, no provider call
        # Persist only exact known part/unit identifiers and booleans, not extra provider strings.
        result['plan'] = {'parts': [{k:p[k] for k in ('part_id','supported','unit_ids')} for p in plan['parts']]}
        result['status'] = 'planning_valid'
    except Exception:
        if phase != 'provider':
            observation = dict(chat.diagnostics[-1]) if chat.diagnostics else {}
            observation.update(category='invalid_json' if phase == 'plan_json' else 'invalid_schema',
                failure_stage='content', finished_at_utc=Diagnostic().started_at_utc)
            chat._remember(observation)
        # Never copy raw planning content or exception text into the failure result.
    finally:
        result['diagnostics'] = chat.diagnostics
        attempts = ledger.snapshot()['attempts']
        if attempts and not result['usage']:
            result['usage'] = attempts[0]['usage'] or {}
            if result['usage']:
                result['usage_completeness'] = 'reported'
        if any(d['category'] == 'ok' for d in chat.diagnostics):
            result['returned_model'] = b.MODEL
        result['elapsed_seconds'] = round(time.monotonic()-started,3)
        ledger.save_first(result)  # INSERT-only, also on cancellation; audit failure propagates
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='One-request v2 preparation/explicit activation/execution.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--approval-file', type=Path)
    group.add_argument('--execute', action='store_true')
    parser.add_argument('--env-file', type=Path, help='Existing private dotenv; read only after execution authorization checks.')
    args = parser.parse_args()
    if args.prepare:
        print(json.dumps(prepare(), indent=2))
    elif args.approval_file:
        ProbeLedger.provision(PROBE_PATH, json.loads(args.approval_file.read_bytes()))
        print('V2 activated; zero provider requests.')
    else:
        print(json.dumps(run_once(credential_file=args.env_file), indent=2))
