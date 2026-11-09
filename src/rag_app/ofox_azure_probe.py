"""V3 Azure-only one-request successor; v1/v2 incidents remain immutable."""
from contextlib import closing, contextmanager
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import stat

from . import demo_budget as b, ofox_probe as v2

V2_PATH = b._account_home()/'.local/state/cs5481/ofox-exp11-selection-v2.sqlite3'
V2_SHA256 = 'c482083f4d23085f1247f1b1a1b1037bc8ebf42f1b94e2e05e4da0b949014bdb'
V2_SESSION = 'cs5481_ofox_exp11_selection_v2_01'
V2_SOURCE = '87ade3df13c7a8d4e8739c154791ba5a9a0dcea41627dd3dcfa81eeef3836f0a'
PROBE_PATH = b._account_home()/'.local/state/cs5481/ofox-exp11-azure-v3.sqlite3'
SESSION_ID = 'cs5481_ofox_exp11_azure_v3_01'


def prior_incidents():
    prior = v2.prior_incident()
    try:
        if (not stat.S_ISREG(V2_PATH.lstat().st_mode) or V2_PATH.resolve() != V2_PATH.absolute()
                or any(b._exists(Path(str(V2_PATH)+suffix)) for suffix in ('-wal','-shm','-journal','.provisioning'))
                or sha256(V2_PATH.read_bytes()).hexdigest() != V2_SHA256):
            raise b.BudgetBlocked('V2 incident binding differs.')
        with closing(sqlite3.connect(V2_PATH.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            meta = db.execute('SELECT state,session_id,fingerprint,registry FROM meta').fetchall()
            attempts = db.execute('SELECT ordinal,case_id,stage,state FROM attempts ORDER BY ordinal').fetchall()
            policy = db.execute('SELECT controller,max_attempts FROM guard_policy').fetchall()
            diagnostics = db.execute('SELECT record FROM attempt_diagnostics_v1 WHERE ordinal=1').fetchall()
            if (meta != [('stopped',V2_SESSION,V2_SOURCE,str(V2_PATH))]
                    or attempts != [(1,'EXP11','selection','error')]
                    or policy != [('exp11_selection_v2',1)] or len(diagnostics) != 1):
                raise b.BudgetBlocked('V2 is not the approved stopped one-request incident.')
            observed = json.loads(diagnostics[0][0])
            if (observed.get('http_status') != 400 or observed.get('provider_error_type') != 'provider_type_unavailable'
                    or observed.get('http_response_received') is not True):
                raise b.BudgetBlocked('V2 route-rejection evidence differs.')
        if sha256(V2_PATH.read_bytes()).hexdigest() != V2_SHA256:
            raise b.BudgetBlocked('V2 incident changed during inspection.')
    except (OSError,sqlite3.Error,ValueError,TypeError):
        raise b.BudgetBlocked('Cannot verify original v2 incident.') from None
    return [prior, dict(registry=str(V2_PATH),sha256=V2_SHA256,session_id=V2_SESSION,
                        source_sha256=V2_SOURCE,consumed_attempts=1)]


def consent_statement():
    return (f'I authorize exactly one Azure Foundry EXP11 evidence-planning dispatch, no generation, retries or fallback; '
        f'acknowledge immutable prior sessions {v2.PRIOR_SESSION} SHA256 {v2.PRIOR_SHA256} at {v2.PRIOR_PATH} '
        f'and {V2_SESSION} SHA256 {V2_SHA256} at {V2_PATH}, each with one consumed attempt; '
        f'authorize successor {SESSION_ID} at {PROBE_PATH}, provider.type=azure_foundry. '
        'I accept USD 0.50 financial tolerance, not a guaranteed monetary cap, and provider billing uncertainty.')


def approval_template():
    return dict(approved=False,statement=consent_statement(),session_id=SESSION_ID,
        authorized_registry=str(PROBE_PATH),source_sha256=b.fingerprint(),provider=b.PROVIDER,
        model=b.MODEL,profile=b.PROFILE,max_attempts=1)


class ProbeLedger(v2.ProbeLedger):
    CONTROLLER = 'exp11_azure_selection_v3'
    ROUTE = 'azure_foundry'

    def __init__(self,path):
        b.SessionLedger.__init__(self,path)
        if self.path != PROBE_PATH or PROBE_PATH.resolve() != PROBE_PATH.absolute():
            raise b.BudgetBlocked('Only the fixed canonical v3 path is permitted.')
        prior_incidents()

    @classmethod
    def provision(cls,path,approval):
        prior_incidents()
        expected = approval_template();expected['approved'] = True
        if Path(path).absolute() != PROBE_PATH or approval != expected:
            raise b.BudgetBlocked('Fresh explicit Azure v3 scope/source/path consent required.')
        return b.SessionLedger.provision.__func__(cls,path,approval)

    @contextmanager
    def transaction(self):
        prior_incidents()
        with b.SessionLedger.transaction(self) as db:
            if db.execute('SELECT session_id FROM meta').fetchone() != (SESSION_ID,):
                raise b.BudgetBlocked('V3 session binding differs.')
            yield db


def prepare():
    return dict(prior_incidents=prior_incidents(),approval=approval_template(),
        registry_exists=b._exists(PROBE_PATH),fence_exists=b._exists(b._provision_marker(PROBE_PATH)),
        endpoint=b.PROVIDER+'/chat/completions',provider_type=ProbeLedger.ROUTE,
        selection_messages_sha256=sha256(json.dumps(v2.selection_messages(),ensure_ascii=False).encode()).hexdigest())


def run_once(*,settings=None,transport=None,credential_file=None):
    return v2._run_once(ProbeLedger(PROBE_PATH),settings=settings,transport=transport,credential_file=credential_file)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Prepare, explicitly activate, or execute one Azure v3 selection request.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true')
    group.add_argument('--approval-file',type=Path)
    group.add_argument('--execute',action='store_true')
    parser.add_argument('--env-file',type=Path)
    args = parser.parse_args()
    if args.prepare:
        print(json.dumps(prepare(),indent=2))
    elif args.approval_file:
        ProbeLedger.provision(PROBE_PATH,json.loads(args.approval_file.read_bytes()))
        print('V3 activated; zero provider requests.')
    else:
        print(json.dumps(run_once(credential_file=args.env_file),indent=2))
