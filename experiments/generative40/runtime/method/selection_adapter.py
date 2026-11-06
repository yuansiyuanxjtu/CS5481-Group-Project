"""Isolated selection adapter with hash-linked stage logs; never constructs a client."""
from hashlib import sha256
from copy import deepcopy
import json
from pathlib import Path
from coverage_contract import render_selection,selection_payload

HERE=Path(__file__).resolve().parent

SAFE_ERRORS={
    "llm_error":"Experimental model request failed; inspect the bounded stage logs.",
    "invalid_output":"Experimental output failed format, coverage or citation validation.",
    "retrieval_error":"Experimental evidence preparation failed.",
    "invalid_input":"The experimental question was rejected."
}


def safe_service_result(result):
    safe=deepcopy(result)
    if result.get("error") is not None:
        safe["error"]=SAFE_ERRORS.get(result.get("status"),"The experimental service reported a failure.")
    return safe


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()


def messages_for_selection(question,evidence):
    return [{"role":"system","content":(HERE/"selection_prompt.txt").read_text(encoding="utf-8")},
            {"role":"user","content":json.dumps(selection_payload(question,evidence),ensure_ascii=False)}]


def verify_events(events,expected_count=None,expected_final_hash=None):
    previous="0"*64
    for index,event in enumerate(events,1):
        payload={k:v for k,v in event.items() if k!="event_sha256"}
        if (event["sequence"]!=index or event["previous_sha256"]!=previous
                or sha256(canonical(payload)).hexdigest()!=event["event_sha256"]):
            raise ValueError("Changed, missing or reordered stage event")
        previous=event["event_sha256"]
    if (expected_count is not None and len(events)!=expected_count) or (expected_final_hash is not None and previous!=expected_final_hash):
        raise ValueError("Event chain differs from the frozen external count/hash")
    return previous


class SelectionClient:
    def __init__(self,client,record):
        self.client,self.record=client,record
        self.sequence=0;self.previous="0"*64;self.request_id=None;self.seen=set()

    def emit(self,event):
        payload={**event,"request_id":self.request_id,"attempt":1,"sequence":self.sequence+1,"previous_sha256":self.previous}
        digest=sha256(canonical(payload)).hexdigest()
        self.record({**payload,"event_sha256":digest})
        self.sequence+=1;self.previous=digest

    def fail(self,stage,exc):
        self.emit({"event":stage,"error_type":type(exc).__name__})

    def generate(self,messages):
        from rag_app.llm import GenerationError,LLMError
        from rag_app.grounding import validate_generation
        self.request_id=None
        try:
            if len(messages)!=2 or messages[1]["role"]!="user":raise ValueError("Unexpected request shape")
            payload=json.loads(messages[1]["content"])
            if set(payload)!={"question","evidence"}:raise ValueError("Unexpected user payload")
            self.request_id=sha256(payload["question"].encode()).hexdigest()
            if self.request_id in self.seen:raise ValueError("Duplicate question in this trial")
            prepared=messages_for_selection(payload["question"],payload["evidence"])
        except (ValueError,TypeError,KeyError) as exc:
            self.fail("selection_input_error",exc)
            raise GenerationError("Experimental selection input is invalid") from None
        self.seen.add(self.request_id)
        self.emit({"event":"selection_request","messages":prepared})
        try:
            generation=self.client.generate(prepared)
        except LLMError as exc:
            self.fail("selection_provider_error",exc)
            raise LLMError("Experimental model provider request failed.") from None
        except GenerationError as exc:
            self.fail("selection_provider_output_error",exc)
            raise GenerationError("Experimental model provider returned invalid output.") from None
        except Exception as exc:
            self.fail("selection_provider_error",exc)
            raise LLMError("Unexpected experimental provider failure") from None
        self.emit({"event":"selection_raw_response","generation":generation})
        try:
            selection=json.loads(generation["content"])
        except (ValueError,TypeError,KeyError) as exc:
            self.fail("selection_parse_error",exc)
            raise GenerationError("Selection response is not valid JSON") from None
        self.emit({"event":"selection_parsed_plan","selection":selection})
        try:
            rendered=render_selection(selection,payload["question"],payload["evidence"])
        except (ValueError,TypeError,KeyError) as exc:
            self.fail("selection_contract_error",exc)
            raise GenerationError("Selection failed the experimental coverage contract") from None
        except Exception as exc:
            self.fail("selection_rendering_error",exc)
            raise GenerationError("Unexpected experimental rendering failure") from None
        self.emit({"event":"deterministic_rendering",**rendered})
        try:
            validated=validate_generation(rendered["content"],payload["evidence"])
        except GenerationError as exc:
            self.fail("selection_validation_error",exc)
            raise GenerationError("Experimental output failed original citation validation.") from None
        except Exception as exc:
            self.fail("selection_validation_error",exc)
            raise GenerationError("Unexpected original validation failure") from None
        self.emit({"event":"original_validation","validated":validated})
        return {**generation,"content":rendered["content"]}

    def record_service_result(self,result):
        self.emit({"event":"service_result","result":safe_service_result(result),
                   "error_representation":"bounded_status_message" if result.get("error") is not None else "unchanged_no_error",
                   "exception_body_recorded":False})


def answer_with_trace(service,question):
    service.llm.request_id=sha256(question.encode() if isinstance(question,str) else canonical(question)).hexdigest()
    result=safe_service_result(service.answer_question(question))
    service.llm.record_service_result(result)
    return result
