"""Two-stage, no-retry raw-body recording; authentication headers are never recorded."""
import base64
from hashlib import sha256
import json
import httpx


class RecordedClient:
    def __init__(self,cfg,role,stream,allowed_questions,seen,upstream_factory=None):
        self.cfg,self.role,self.stream,self.allowed,self.seen=cfg,role,stream,allowed_questions,seen
        self.upstream_factory=upstream_factory or (lambda:httpx.AsyncHTTPTransport(retries=0))

    def generate(self,messages):
        from rag_app.llm import ChatClient,LLMError
        owner=self
        question=json.loads(messages[-1]['content'])['question']
        identity=(self.role,question)
        if question not in self.allowed or identity in self.seen or len(self.seen)>=80:
            raise LLMError('Unexpected, repeated or excessive experimental provider call.')
        self.seen.add(identity)
        def emit(event):
            self.stream.write(json.dumps({'phase':self.role,'question_sha256':sha256(question.encode()).hexdigest(),
                 'attempt':1,**event},ensure_ascii=False)+'\n');self.stream.flush()
        def protected(raw):
            sensitive=bool(self.cfg.api_key and self.cfg.api_key.encode() in raw)
            safe=raw.replace(self.cfg.api_key.encode(),b'[REDACTED_API_KEY]') if sensitive else raw
            return {'body_base64':base64.b64encode(safe).decode(),'body_utf8':safe.decode('utf-8',errors='replace'),
                    'sha256_original':sha256(raw).hexdigest(),'sensitive_redaction_applied':sensitive}
        class Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self,request):
                raw=await request.aread();payload=json.loads(raw)
                expected={'model':owner.cfg.model,'messages':messages,'max_tokens':owner.cfg.max_tokens,'temperature':0,
                          'stream':False,'response_format':{'type':'json_object'},'thinking':{'type':'disabled'}}
                if payload!=expected or request.method!='POST' or str(request.url)!=owner.cfg.base_url.rstrip('/')+'/chat/completions':
                    raise LLMError('HTTP request differs from the frozen generation settings.')
                body=protected(raw);emit({'event':'http_request',**body})
                if body['sensitive_redaction_applied']:raise LLMError('Sensitive request content blocked.')
                try:
                    async with owner.upstream_factory() as upstream:
                        response=await upstream.handle_async_request(request);returned=await response.aread()
                    if response.status_code!=200:
                        emit({'event':'http_error_response','status_code':response.status_code})
                        return response
                    body=protected(returned);emit({'event':'http_response','status_code':200,**body})
                    if body['sensitive_redaction_applied']:raise LLMError('Sensitive response content blocked.')
                    return response
                except BaseException as exc:
                    emit({'event':'http_error','error_type':type(exc).__name__});raise
        return ChatClient(self.cfg,transport=Transport()).generate(messages)
