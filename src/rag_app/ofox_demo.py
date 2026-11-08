"""Separate OfoxAI demonstration, not a historical DeepSeek evaluation."""
from dataclasses import replace
from hashlib import sha256
import json
import os
import time

import httpx

from . import demo_budget as budget
from .llm import ChatClient, GenerationError, LLMError
from .service import QAService


class GuardedTransport(httpx.AsyncBaseTransport):
    def __init__(self, ledger, claim, upstream_factory):
        self.ledger, self.claim = ledger, claim
        self.upstream = None
        self.factory = upstream_factory

    async def handle_async_request(self, request):
        ordinal = None
        try:
            body = json.loads(request.content)
            if (request.method != 'POST' or str(request.url) != budget.PROVIDER+'/chat/completions'
                    or set(body) != {'model','messages','max_completion_tokens','reasoning_effort','response_format','stream','extra_body'}
                    or body['model'] != budget.MODEL or body['max_completion_tokens'] != 1200
                    or body['reasoning_effort'] != 'low' or body['stream'] is not False
                    or body['response_format'] != {'type':'json_object'}
                    or body['extra_body'] != {'provider': {'type':'openai', 'fallback':[]}}):
                raise budget.BudgetBlocked('OfoxAI request configuration differs.')
            messages = body['messages']
            payload = json.loads(messages[1]['content'])
            if payload['question'] != budget.questions()[self.claim[0]]:
                raise budget.BudgetBlocked('Request question differs from the claimed case.')
            stage = 'generation' if 'evidence_plan' in payload else 'selection'
            if self.claim[0] == 'EXP-R07' and stage == 'generation':
                raise budget.BudgetBlocked('Unexpected generation for the refusal case; stop.')
            from .demo import ROOT, RUNTIME
            records = json.loads((ROOT/'experiments/joint_pairs8/model_inputs40.json').read_bytes())['requests']
            frozen = json.loads(next(r['messages'][1]['content'] for r in records if r['id'] == self.claim[0]))['evidence']
            actual = payload['evidence']
            if len(actual) != 8:
                raise budget.BudgetBlocked('Expected eight frozen evidence blocks.')
            for a,b in zip(actual, frozen, strict=True):
                if set(a) != set(b) or any(a[k] != b[k] for k in b if k != 'distance') or abs(a['distance']-b['distance']) >= 1e-5:
                    raise budget.BudgetBlocked('Evidence differs from the reviewed case.')
            prompt = RUNTIME/('generation_prompt.txt' if stage == 'generation' else 'method/selection_prompt.txt')
            if len(messages) != 2 or messages[0] != {'role':'system', 'content':prompt.read_text(encoding='utf-8')}:
                raise budget.BudgetBlocked('Frozen prompt differs.')
            ordinal = self.ledger.reserve(self.claim, stage)  # durable commit BEFORE factory/network
            self.upstream = self.factory()
            response = await self.upstream.handle_async_request(request)
            await response.aread()
            try:
                data = response.json()
                usage = data.get('usage')
                valid = (response.status_code == 200 and data.get('model') == budget.MODEL
                         and data['choices'][0]['finish_reason'] == 'stop'
                         and isinstance(data['choices'][0]['message']['content'], str))
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                valid, usage = False, None
            self.ledger.record(ordinal, valid, usage)
            if not valid:
                raise LLMError('OfoxAI returned an HTTP, model or response-format failure; session stopped.')
            return response
        except BaseException:
            if ordinal is not None:
                # Already-completed audit rows are not overwritten. A reserved
                # uncertain attempt stays consumed if recording itself fails.
                snapshot = self.ledger.snapshot()
                if snapshot['attempts'][ordinal-1]['state'] == 'reserved':
                    self.ledger.record(ordinal, False)
            raise

    async def aclose(self):
        if self.upstream is not None:
            await self.upstream.aclose()


class OfoxChatClient(ChatClient):
    def __init__(self, settings, ledger, claim, upstream_factory):
        super().__init__(settings)
        self.ledger, self.claim, self.factory = ledger, claim, upstream_factory

    async def _request(self, messages):
        if not self.settings.api_key:
            raise LLMError('Configure OFOX_API_KEY locally after explicit live authorization.')
        body = dict(model=budget.MODEL, messages=messages, max_completion_tokens=1200,
                    reasoning_effort='low', response_format={'type':'json_object'}, stream=False,
                    extra_body={'provider': {'type':'openai', 'fallback':[]}})
        try:
            transport = GuardedTransport(self.ledger, self.claim, self.factory)
            async with httpx.AsyncClient(transport=transport, timeout=120, follow_redirects=False, trust_env=False) as client:
                response = await client.post(budget.PROVIDER+'/chat/completions', json=body,
                    headers={'Authorization':'Bearer '+self.settings.api_key})
            data = response.json()
            content = data['choices'][0]['message']['content']
            if not content.strip() or len(content) > 50000:
                raise GenerationError('OfoxAI returned empty or oversized content.')
            return {'content':content, 'model':data['model'], 'usage':data.get('usage',{})}
        except httpx.TimeoutException:
            raise LLMError('OfoxAI request timed out; do not retry.') from None
        except (httpx.HTTPError, budget.BudgetBlocked):
            raise LLMError('OfoxAI request or durable budget failed; session cannot resume.') from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise GenerationError('OfoxAI response format is invalid.') from None


class OfoxAcceptanceService:
    def __init__(self, retriever, catalog, settings, ledger, planner, upstream_factory):
        self.retriever, self.catalog, self.settings = retriever, catalog, settings
        self.ledger, self.planner, self.factory = ledger, planner, upstream_factory

    def answer_question(self, question):
        started = time.monotonic()
        claim = None
        try:
            claim = self.ledger.begin(question)
            chat = OfoxChatClient(self.settings, self.ledger, claim, self.factory)
            from .demo import TwoStageDemoClient
            service = QAService(self.retriever, TwoStageDemoClient(chat, self.planner), self.catalog, self.settings)
            result = service.answer_question(question)
            # Boundary usage survives second-stage/provider errors; absent usage
            # is explicitly partial/unknown, never a claim of zero billing.
            audit = self.ledger.snapshot()
            attempts = [r for r in audit['attempts'] if r['case_id'] == claim[0]]
            totals = {}
            for row in attempts:
                for k,v in (row['usage'] or {}).items():
                    totals[k] = totals.get(k,0)+v
            result.update(usage=totals, usage_completeness='reported' if attempts and all(r['usage'] for r in attempts) else 'partial_or_unknown',
                          provider_attempts=attempts, demo_profile=budget.PROFILE,
                          experiment_origin='NEW_OFOX_GPT6_LUNA_DEMO_NOT_HISTORICAL_SCORES')
            self.ledger.finish(claim, result['status'], result)
            result['session_state'] = self.ledger.snapshot()['state']
        except (budget.BudgetBlocked, OSError):
            result = {'status':'acceptance_blocked', 'answer':'', 'citations':[], 'claims':[], 'retrieved':[],
                      'error':'Acceptance budget, case or audit blocked execution. Do not retry or reset.', 'model':None, 'usage':{}}
        result.update(elapsed_seconds=round(time.monotonic()-started,3), demo_profile=budget.PROFILE,
                      experiment_origin='NEW_OFOX_GPT6_LUNA_DEMO_NOT_HISTORICAL_SCORES')
        return result


def create_ofox_service(settings, *, transport=None):
    from .demo import ROOT, RUNTIME, _load_experiment
    from rag_ingest.temporal import load_temporal_catalog
    budget.enforce_profile(budget.PROFILE)
    ledger = budget.SessionLedger(budget.DEFAULT_LEDGER)
    ledger.check()  # before credentials, model loading or network transport
    if transport is not None and not isinstance(transport, httpx.MockTransport):
        raise budget.BudgetBlocked('Only MockTransport injection is supported; live transport has zero retries.')
    manifest = json.loads((RUNTIME/'runtime_manifest.json').read_bytes())
    for row in manifest['files']:
        if row['path'].startswith('method/') or row['path'] == 'generation_prompt.txt':
            if sha256((RUNTIME/row['path']).read_bytes()).hexdigest() != row['sha256']:
                raise budget.BudgetBlocked('Historical generation source differs.')
    cfg = replace(settings, api_key=os.environ.get('OFOX_API_KEY','').strip(), base_url=budget.PROVIDER,
                  model=budget.MODEL, thinking='', timeout=120, max_tokens=1200, json_mode=True,
                  top_k=8, collection='fixed_150_overlap_30', arm='enhanced', max_distance=None)
    catalog_path = cfg.experiment_dir/'temporal_catalog.json'
    context = json.loads((cfg.experiment_dir/'enhanced/collection_context.json').read_bytes())
    protocol = json.loads((ROOT/'experiments/joint_pairs8/generation_protocol.json').read_bytes())
    raw = catalog_path.read_bytes()
    if (sha256(raw).hexdigest() != context['temporal_catalog_sha256']
            or sha256(raw.replace(b'\r\n',b'\n')).hexdigest() != protocol['temporal_catalog_sha256_lf']):
        raise budget.BudgetBlocked('Index/catalog snapshot differs.')
    candidate, planned = _load_experiment()
    factory = (lambda: transport) if transport is not None else (lambda: httpx.AsyncHTTPTransport(retries=0, trust_env=False))
    return OfoxAcceptanceService(candidate.JointCandidateRetriever(cfg.experiment_dir,cfg.cache_dir),
        load_temporal_catalog(catalog_path), cfg, ledger, planned.PlannedGenerationClient, factory)


if __name__ == '__main__':
    # No paid runner and no automatic approval creation. Local provisioning is
    # possible only from a separately supplied explicit approval document.
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description='Import explicit OfoxAI consent into the fixed registry; no API calls.')
    parser.add_argument('--approval-file', type=Path, required=True)
    args = parser.parse_args()
    budget.SessionLedger.provision(budget.DEFAULT_LEDGER, json.loads(args.approval_file.read_bytes()))
    print('Fixed registry provisioned. No provider request was made.')
