"""NDJSON transport around the existing ask handler and its concurrency guard."""
import asyncio
import json
import threading
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from .response_trace import SINK

def stream_response(handler, request):
    async def events():
        queue=asyncio.Queue(); loop=asyncio.get_running_loop(); closed=threading.Event()
        def publish(event):
            if not closed.is_set(): loop.call_soon_threadsafe(queue.put_nowait,event)
        def sink(event):
            if closed.is_set():
                from .llm_provider import LLMError
                raise LLMError('cancelled')
            publish(event)
        def work():
            token=SINK.set(sink)
            try: publish({'type':'result','data':handler(request)})
            except HTTPException as exc: publish({'type':'error','status':exc.status_code})
            except Exception: publish({'type':'error','status':500})
            finally: SINK.reset(token)
        task=asyncio.create_task(asyncio.to_thread(work))
        try:
            while True:
                try: event=await asyncio.wait_for(queue.get(),timeout=5)
                except asyncio.TimeoutError: event={'type':'ping'}
                yield json.dumps(event,ensure_ascii=False)+'\n'
                if event['type'] in ('result','error'): break
        finally:
            closed.set()
            # The bounded provider request retains the ask slot until it exits.
            # Do not release the semaphore early when the browser disconnects.
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    return StreamingResponse(events(),media_type='application/x-ndjson',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
