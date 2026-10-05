import json
import time
from urllib.parse import urlsplit
import httpx

def target(config):
    url = config.target_url.rstrip('/') + ('/' + config.endpoint.lstrip('/') if config.endpoint else '')
    parts = urlsplit(url)
    if parts.scheme not in ('http','https') or parts.username or parts.password or parts.fragment:
        raise ValueError('Use an http:// or https:// URL without embedded credentials or fragments.')
    local = parts.hostname in ('127.0.0.1','localhost','::1')
    if not local and not config.target_consent:
        raise ValueError('Confirm that you own or are authorized to test this external API.')
        raise ValueError('This local MVP permits only explicit localhost / 127.0.0.1 / ::1 HTTP targets; redirects are disabled.')
    return url

def field(value, path):
    for part in path.split('.'):
        if isinstance(value,dict):
            value = value[part]
        elif isinstance(value,list):
            value = value[int(part)]
        else:
            raise KeyError(path)
    return value

async def request(config, prompt='Hello', session=None, payload=None):
    body = {config.request_field:prompt} if payload is None else payload
    if session and config.session_field:
        body[config.session_field] = session
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=config.timeout, follow_redirects=False, trust_env=False) as client:
            async with client.stream(config.method, target(config), **({'json':body} if config.method in ('POST','PUT','PATCH','DELETE') else {'params':body})) as response:
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 262144:
                        raise ValueError('Response exceeded 256 KB limit')
                text = data.decode('utf-8',errors='replace')
                content_type=response.headers.get('content-type','')
                try:
                    parsed = json.loads(text)
                except ValueError:
                    parsed = None
                if 'text/event-stream' in content_type:
                    tokens=[]
                    for line in text.splitlines():
                        if not line.startswith('data:'):
                            continue
                        try:
                            event=json.loads(line[5:].strip())
                            if isinstance(event,dict) and isinstance(event.get('text'),str):
                                tokens.append(event['text'])
                        except ValueError:
                            continue
                    answer=''.join(tokens)
                    parsed={'answer':answer,'streaming':True,'raw_event_count':sum(line.startswith('data:') for line in text.splitlines())}
                try:
                    answer = field(parsed,config.response_field)
                    valid = True
                except (KeyError,ValueError,TypeError,IndexError):
                    answer, valid = text[:10000], False
                return dict(status_code=response.status_code, json=parsed, answer=answer, response_field_found=valid, duration_ms=round((time.perf_counter()-start)*1000,2))
    except httpx.TimeoutException:
        return dict(error='Request timed out',timeout=True,duration_ms=round((time.perf_counter()-start)*1000,2))
    except (httpx.HTTPError,ValueError) as exc:
        return dict(error=str(exc)[:500],duration_ms=round((time.perf_counter()-start)*1000,2))

async def functional(config):
    cases = [c for c in config.dataset if c.get('category') == 'functional']
    if not cases:
        cases = [dict(name='Valid chat request',prompt='Hello',expected_status=200),dict(name='Missing message',payload={},expected_status=422),dict(name='Invalid message type',payload={config.request_field:42},expected_status=422),dict(name='Empty message',prompt='',expected_status=422),dict(name='Boundary: 4097 characters',prompt='x'*4097,expected_status=422)]
    for case in cases:
        observed = await request(config, case.get('prompt','Hello'), payload=case.get('payload'))
        expected_status = case.get('expected_status',200)
        passed = observed.get('status_code') == expected_status
        diagnostics = []
        if 200 <= expected_status < 300:
            passed = passed and observed.get('response_field_found',False)
        for name in case.get('required_fields',[]):
            try:
                field(observed.get('json'),name)
            except (KeyError,ValueError,TypeError,IndexError):
                passed = False
                diagnostics.append(f'Missing required field: {name}')
        for name, value in case.get('expected_fields',{}).items():
            try:
                if field(observed.get('json'),name) != value:
                    passed = False
                    diagnostics.append(f'Value mismatch at {name}')
            except (KeyError,ValueError,TypeError,IndexError):
                passed = False
                diagnostics.append(f'Missing field: {name}')
        for name, kind in case.get('field_types',{}).items():
            try:
                actual = field(observed.get('json'),name)
                valid = {'string':isinstance(actual,str),'number':type(actual) in (float,int),'integer':type(actual) is int,'boolean':type(actual) is bool,'object':isinstance(actual,dict),'array':isinstance(actual,list),'null':actual is None}.get(kind,False)
                if not valid:
                    passed=False
                    diagnostics.append(f'Type mismatch at {name}: expected {kind}')
            except (KeyError,ValueError,TypeError,IndexError):
                passed=False
                diagnostics.append(f'Missing typed field: {name}')
        yield dict(name=case.get('name','Functional case'), input=case.get('payload',case.get('prompt','Hello')), expected={'status':expected_status,'fields':case.get('expected_fields',{}),'note':'Default validation contract expects 422; override with dataset cases for your API.'},actual=observed,status='passed' if passed else 'failed',duration_ms=observed['duration_ms'],evidence=diagnostics or ['Observed HTTP response compared with configured contract.'],recommendation='Align expected status/field rules with the documented API contract; inspect failing response.')

