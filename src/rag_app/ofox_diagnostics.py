"""Bounded diagnostics only: no raw errors, payloads, credentials or headers."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from hashlib import sha256
import re
import asyncio
import socket
import ssl

import httpx

CATEGORIES = frozenset({'ok', 'unknown_failure', 'budget_failure', 'audit_failure',
    'dns_failure', 'tls_failure', 'connect_failure', 'proxy_failure', 'timeout', 'cancelled',
    'network_failure', 'http_error', 'invalid_json', 'invalid_schema',
    'model_mismatch', 'non_stop_finish', 'invalid_content'})
STAGES = frozenset({'request_validation', 'reservation', 'transport_factory', 'transport',
    'response_body', 'response_json', 'response_schema', 'response_model',
    'response_finish', 'content', 'audit', 'cleanup', 'complete'})
ERROR_VALUES = frozenset({'invalid_request_error', 'authentication_error', 'permission_error',
    'rate_limit_error', 'insufficient_quota', 'invalid_api_key', 'model_not_found',
    'invalid_provider_type', 'provider_type_unavailable', 'endpoint_not_supported',
    'unsupported_parameter', 'context_length_exceeded', 'upstream_error', 'gateway_timeout'})
FINISH_VALUES = frozenset({'stop', 'length', 'content_filter', 'tool_calls', 'function_call', 'other'})


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sanitize(value):
    """Rebuild an exact fixed schema, including at the persistence boundary."""
    value = value if isinstance(value, dict) else {}
    def enum(key, allowed, default=None):
        item = value.get(key)
        return item if isinstance(item, str) and item in allowed else default
    def timestamp(key):
        item = value.get(key)
        try:
            parsed = datetime.fromisoformat(item) if isinstance(item, str) and len(item) <= 40 else None
            return parsed.astimezone(timezone.utc).isoformat() if parsed and parsed.tzinfo else None
        except (ValueError, OverflowError):
            return None
    digest = value.get('request_id_sha256')
    status = value.get('http_status')
    ordinal = value.get('attempt_ordinal')
    result = dict(schema_version=1,
        attempt_ordinal=ordinal if type(ordinal) is int and 1 <= ordinal <= 6 else None,
        stage=enum('stage', {'selection', 'generation'}, 'unknown'),
        failure_stage=enum('failure_stage', STAGES, 'request_validation'),
        category=enum('category', CATEGORIES, 'unknown_failure'),
        started_at_utc=timestamp('started_at_utc'), finished_at_utc=timestamp('finished_at_utc'),
        http_status=status if type(status) is int and 100 <= status <= 599 else None,
        provider_error_type=enum('provider_error_type', ERROR_VALUES),
        provider_error_code=enum('provider_error_code', ERROR_VALUES),
        finish_reason=enum('finish_reason', FINISH_VALUES),
        request_id_sha256=digest if isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest) else None)
    for key in ('transport_constructed', 'dispatch_started', 'http_response_received', 'body_read_complete'):
        result[key] = value.get(key) is True
    return result


def exception_category(exc, *, deadline_expired=False):
    """Inspect exception classes/causes, never messages, repr or arguments."""
    if isinstance(exc, asyncio.CancelledError):
        return 'timeout' if deadline_expired else 'cancelled'
    seen = set()
    current = exc
    for _ in range(6):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return 'tls_failure'
        if isinstance(current, socket.gaierror):
            return 'dns_failure'
        current = current.__cause__ or current.__context__
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return 'timeout'
    if isinstance(exc, httpx.ProxyError):
        return 'proxy_failure'
    if isinstance(exc, httpx.ConnectError):
        return 'connect_failure'
    if isinstance(exc, httpx.HTTPError):
        return 'network_failure'
    return 'unknown_failure'


@dataclass
class Diagnostic:
    stage: str = 'unknown'
    attempt_ordinal: int | None = None
    failure_stage: str = 'request_validation'
    category: str = 'unknown_failure'
    transport_constructed: bool = False
    dispatch_started: bool = False  # transport handoff, NOT proof of a TCP connection
    http_response_received: bool = False
    body_read_complete: bool = False
    http_status: int | None = None
    provider_error_type: str | None = None
    provider_error_code: str | None = None
    finish_reason: str | None = None
    request_id_sha256: str | None = None
    started_at_utc: str = ''
    finished_at_utc: str = ''

    def __post_init__(self):
        self.started_at_utc = utc_now()

    def response(self, response, secret):
        self.http_response_received = True
        self.http_status = response.status_code
        # Correlation digest only; even a hostile header cannot persist a raw secret.
        for key in ('x-request-id', 'request-id', 'x-ofox-request-id'):
            item = response.headers.get(key)
            if (secret and isinstance(item, str) and len(item) <= 100
                    and secret not in item and re.fullmatch(r'(?:req_[A-Za-z0-9_-]{8,64}|[0-9a-fA-F-]{36})', item)):
                self.request_id_sha256 = sha256(item.encode()).hexdigest()
                break

    def provider_error(self, data, secret):
        error = data.get('error') if isinstance(data, dict) else None
        if isinstance(error, dict):
            for name in ('type', 'code'):
                item = error.get(name)
                if isinstance(item, str) and item in ERROR_VALUES and (not secret or secret not in item):
                    setattr(self, 'provider_error_' + name, item)

    def snapshot(self):
        if not self.finished_at_utc:
            self.finished_at_utc = utc_now()
        return sanitize(asdict(self))
