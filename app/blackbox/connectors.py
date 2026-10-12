import asyncio, ipaddress, json, socket, time, uuid
from urllib.parse import urlsplit
import httpx

async def validate_destination(url):
 p=urlsplit(url)
 if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
  raise ValueError('Use an HTTP(S) URL without embedded credentials.')
 addresses=await asyncio.to_thread(socket.getaddrinfo,p.hostname,p.port or (443 if p.scheme=='https' else 80))
 for item in addresses:
  ip=ipaddress.ip_address(item[4][0])
  if not (ip.is_global or ip.is_loopback):
   raise ValueError('Only public addresses or loopback are allowed; private-network and metadata endpoints are blocked.')

async def request_json(client,method,url,**kwargs):
 await validate_destination(url)
 async with client.stream(method,url,**kwargs) as r:
  r.raise_for_status(); body=bytearray()
  async for chunk in r.aiter_bytes():
   body.extend(chunk)
   if len(body)>512000: raise ValueError('Response exceeded 500 KB limit.')
  if 'text/event-stream' in r.headers.get('content-type',''):
   return parse_chat_stream(body.decode('utf-8'))
  return json.loads(body)

def parse_chat_stream(text):
 """Decode the Reliance token/meta/done SSE contract, never pass HTTP-200 errors."""
 chunks=[];done=False;metadata={}
 for block in text.replace('\r\n','\n').split('\n\n'):
  event='message';data=[]
  for line in block.splitlines():
   if line.startswith('event:'):event=line[6:].strip()
   elif line.startswith('data:'):data.append(line[5:].lstrip())
  if not data:continue
  payload=json.loads('\n'.join(data))
  if event=='error':raise ValueError('Chat stream error: '+str(payload.get('message','Unknown error'))[:300])
  if event=='meta':metadata.update(payload)
  if event=='token':
   if not isinstance(payload.get('text'),str):raise ValueError('Invalid chat stream token.')
   chunks.append(payload['text'])
  if event=='done':
   if payload.get('ok') is not True:raise ValueError('Chat stream reported unsuccessful completion.')
   done=True;metadata.update(payload)
 if not done:raise ValueError('Chat stream ended without a successful completion event.')
 answer=''.join(chunks)
 if not answer.strip():raise ValueError('Chat stream completed without an answer.')
 return {'reply':answer,'stream_metadata':metadata}

def field(data,path):
 for key in path.split('.'):
  data=data[int(key)] if isinstance(data,list) else data[key]
 return data

class Connector:
 def __init__(self,target,timeout):
  self.target=target;self.timeout=timeout;self.kind=target.kind
  self.client=httpx.AsyncClient(timeout=timeout,follow_redirects=False,trust_env=False)
 async def close(self): await self.client.aclose()
 async def detect(self):
  t=self.target
  if t.kind=='zip': raise ValueError('ZIP execution is unavailable: this machine has no configured isolated sandbox. No uploaded code was run.')
  await validate_destination(t.url)
  if self.kind!='auto': return
  if urlsplit(t.url).path.rstrip('/').endswith('/chat/completions'):self.kind='openai';return
  headers={'Authorization':'Bearer '+t.token.get_secret_value()} if t.token else {}
  async with self.client.stream('GET',t.url,headers=headers) as r:
   if r.status_code!=405:r.raise_for_status()
   if 'text/html' in r.headers.get('content-type',''):self.kind='web'
   elif 'json' in r.headers.get('content-type','') or r.status_code==405:self.kind='rest'
   else:raise ValueError('Could not identify a chat interface. Choose REST, OpenAI-compatible, or web chat explicitly.')
 async def conversation(self,case):
  if self.kind=='web': return await self.web_conversation(case)
  transcript=[]; session=str(uuid.uuid4());history=[];usage=[]
  for prompt in case['turns']:
   if case['parallel']: history=[];session=str(uuid.uuid4())
   history.append({'role':'user','content':prompt})
   t=self.target;headers={}
   if t.token:headers['Authorization']='Bearer '+t.token.get_secret_value()
   if self.kind=='openai':
    if not t.model:raise ValueError('The OpenAI-compatible target needs its model ID.')
    body={'model':t.model,'messages':history,'stream':False}
   else:
    body={**t.request_defaults,t.message_field:prompt}
    if t.session_field:body[t.session_field]=session
    if t.history_field:body[t.history_field]=history[:-1]
   started=time.perf_counter()
   try:
    data=await request_json(self.client,'POST',t.url,headers=headers,json=body)
    path=t.response_field or ('choices.0.message.content' if self.kind=='openai' else '')
    if path:answer=field(data,path)
    else:
     candidates=[data[k] for k in ('answer','reply','response','message','text') if isinstance(data.get(k),str)]
     if len(candidates)!=1:raise ValueError('Response field is ambiguous. Enter the exact response JSON field in advanced connection settings.')
     answer=candidates[0]
    if not isinstance(answer,str) or not answer.strip():raise ValueError('The configured answer field is empty or not text.')
    answer=answer[:24000]
    if t.session_field and data.get(t.session_field):session=data[t.session_field]
    history.append({'role':'assistant','content':answer})
    usage.append(data.get('usage'))
    transcript.append({'input':prompt,'output':answer,'seconds':round(time.perf_counter()-started,3),'transport':'HTTP','http_status':200,'response_metadata':data.get('stream_metadata',{})})
   except Exception as e:
    transcript.append({'input':prompt,'output':None,'seconds':round(time.perf_counter()-started,3),'error':safe_error(e)})
    return {'transcript':transcript,'error':safe_error(e),'usage':usage}
   await asyncio.sleep(.25)
  return {'transcript':transcript,'usage':usage,'error':None}
 async def web_conversation(self,case):
  from playwright.async_api import async_playwright
  from pathlib import Path
  t=self.target;transcript=[]
  async with async_playwright() as p:
   chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
   browser=await p.chromium.launch(headless=True,**({'executable_path':str(chrome)} if chrome.exists() else {}))
   context=await browser.new_context(accept_downloads=False,service_workers='block')
   async def guard(route):
    try:
     if route.request.url.startswith(('data:','blob:')): await route.continue_();return
     await validate_destination(route.request.url);await route.continue_()
    except Exception:await route.abort()
   await context.route('**/*',guard)
   page=await context.new_page();page.set_default_timeout(self.timeout*1000)
   try:
    await page.goto(t.url,wait_until='domcontentloaded')
    for prompt in case['turns']:
     if case['parallel'] and transcript:
      await context.close();context=await browser.new_context(accept_downloads=False,service_workers='block');await context.route('**/*',guard);page=await context.new_page();page.set_default_timeout(self.timeout*1000);await page.goto(t.url)
     inputs=page.locator(t.input_selector or 'textarea:visible, input[type="text"]:visible, [contenteditable="true"]:visible')
     if await inputs.count()!=1:raise ValueError('Chat input detection is ambiguous; configure its CSS selector. No arbitrary page controls were clicked.')
     answers=page.locator(t.answer_selector or '[data-message-author-role="assistant"], [data-role="assistant"], .assistant-message, .bot-message')
     before=await answers.count();start=time.perf_counter()
     await inputs.fill(prompt)
     if t.send_selector:await page.locator(t.send_selector).click()
     else:await inputs.press('Enter')
     deadline=time.monotonic()+self.timeout;last='';stable=0
     while time.monotonic()<deadline:
      await asyncio.sleep(.5)
      if await answers.count()>before:
       value=await answers.last.inner_text()
       stable=stable+1 if value==last and value.strip() else 0;last=value
       if stable>=3:break
     else:raise ValueError('No identifiable completed assistant reply. Configure the assistant-message CSS selector.')
     transcript.append({'input':prompt,'output':last[:24000],'seconds':round(time.perf_counter()-start,3),'transport':'browser'})
    return {'transcript':transcript,'error':None,'usage':[]}
   except Exception as e:return {'transcript':transcript,'error':safe_error(e),'usage':[]}
   finally:await browser.close()

def safe_error(e):
 if isinstance(e,httpx.HTTPStatusError):return f'Target returned HTTP {e.response.status_code}.'
 if isinstance(e,(httpx.TimeoutException,TimeoutError)):return 'Request timed out.'
 if isinstance(e,httpx.RequestError):return 'Target connection failed.'
 return str(e)[:400]
