"""Evidence planning assists an LLM-generated final answer; original validator remains."""
from copy import deepcopy
import json
from pathlib import Path
from coverage_contract import source_units,question_parts
from selection_adapter import SelectionClient

PROMPT_PATH=Path(__file__).resolve().parent.parent/'generation_prompt.txt'


def final_messages(question,evidence,selection):
    by_id={u['unit_id']:u for u in source_units(evidence)}
    chosen=list(dict.fromkeys(uid for p in selection['parts'] for uid in p['unit_ids']))
    plan={'question_parts':question_parts(question),'selection':selection,
          'selected_units':[by_id[uid] for uid in chosen],
          'notice':'Fallible model proposal only; independently check the full question and original evidence.'}
    return [{'role':'system','content':PROMPT_PATH.read_text(encoding='utf-8')},
            {'role':'user','content':json.dumps({'question':question,'evidence':evidence,'evidence_plan':plan},ensure_ascii=False)}]


class PlannedGenerationClient(SelectionClient):
    def __init__(self,selector_client,generator_client,record):
        self.actual_calls=0
        owner=self
        class BoundedClient:
            def __init__(self,inner):self.inner=inner
            def generate(self,messages):
                from rag_app.llm import LLMError
                if owner.actual_calls>=80:raise LLMError('Experimental trial call cap reached.')
                owner.actual_calls+=1
                return self.inner.generate(messages)
        super().__init__(BoundedClient(selector_client),record)
        self.generator_client=BoundedClient(generator_client);self.phase='evidence_planning';self.plan=None
        self.final_generation=None

    def emit(self,event):
        if event['event']=='selection_parsed_plan':self.plan=deepcopy(event['selection'])
        super().emit({**event,'purpose':self.phase})

    def generate(self,messages):
        from rag_app.llm import GenerationError,LLMError
        self.phase='evidence_planning';self.plan=None;self.final_generation=None
        evidence_preview=super().generate(messages)
        preview=json.loads(evidence_preview['content'])
        if preview['status']=='insufficient_evidence':
            self.emit({'event':'final_answer_skipped','reason':'A requested part was declared unsupported; whole-question refusal.',
                       'answer_origin':'model_plan_triggered_refusal'})
            return evidence_preview
        payload=json.loads(messages[1]['content'])
        prepared=final_messages(payload['question'],payload['evidence'],self.plan)
        self.phase='LLM_answer_generation'
        self.emit({'event':'generation_request','messages':prepared})
        try:
            generation=self.generator_client.generate(prepared)
        except LLMError as exc:
            self.fail('generation_provider_error',exc)
            raise LLMError('Experimental answer-generation request failed.') from None
        except GenerationError as exc:
            self.fail('generation_provider_output_error',exc)
            raise GenerationError('Experimental answer-generation provider returned invalid output.') from None
        except Exception as exc:
            self.fail('generation_provider_error',exc)
            raise LLMError('Unexpected experimental answer-generation failure.') from None
        self.final_generation=deepcopy(generation)
        self.emit({'event':'generation_raw_response','generation':generation})
        # No deterministic quote rendering replaces this content. QAService validates
        # the exact final LLM response using its original validate_generation call.
        return generation

    def record_service_result(self,result):
        self.phase='final_service_output'
        self.emit({'event':'final_answer_validation_outcome','status':result['status'],
                   'final_LLM_response_present':self.final_generation is not None,
                   'answer_origin':'LLM_generated' if self.final_generation is not None else 'no_final_LLM_answer',
                   'provenance_validation_is_not_semantic_correctness':True})
        super().record_service_result(result)
