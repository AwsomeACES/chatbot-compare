import asyncio
import math
import time
from collections import Counter
from .functional_tester import request

async def performance(config, stop):
    start=time.perf_counter()
    semaphore=asyncio.Semaphore(config.concurrency)
    samples=[]
    async def once():
        async with semaphore:
            if not stop.is_set() and time.perf_counter()-start < config.duration_limit:
                samples.append(await request(config,'Hello'))
    pending=[]
    for _ in range(config.iterations):
        if stop.is_set() or time.perf_counter()-start >= config.duration_limit:
            break
        pending.append(asyncio.create_task(once()))
        await asyncio.sleep(1/config.requests_per_second)
    await asyncio.gather(*pending)
    elapsed=time.perf_counter()-start
    latencies=sorted(s['duration_ms'] for s in samples)
    n=len(samples)
    ok=sum(200 <= s.get('status_code',0) < 300 for s in samples)
    def percentile(p, minimum):
        return latencies[max(0,math.ceil(p*n)-1)] if n >= minimum else None
    return {'total_requests':n,'successful_requests':ok,'failed_requests':n-ok,'requests_per_second':round(n/elapsed,3),'average_latency_ms':round(sum(latencies)/n,2) if n else None,'p50_ms':percentile(.5,2),'p95_ms':percentile(.95,20),'p99_ms':percentile(.99,100),'timeout_count':sum(bool(s.get('timeout')) for s in samples),'error_rate':(n-ok)/n if n else None,'status_distribution':dict(Counter(str(s.get('status_code','error')) for s in samples)),'elapsed_seconds':round(elapsed,3),'limitations':'Nearest-rank percentiles; p95 requires 20 samples, p99 requires 100. Scheduling stops at duration limit; in-flight requests may continue up to request timeout.'}
