"""Request-local timing and optional streaming callbacks; no prompt logging."""
import time
from contextvars import ContextVar
from contextlib import contextmanager

TRACE = ContextVar('response_trace', default=None)
SINK = ContextVar('response_sink', default=None)
TOKENS = ContextVar('answer_tokens', default=None)

def citation_numbers(text):
    import re
    return {int(n) for group in re.findall(r'\[(\d+(?:\s*,\s*\d+)*)\]', text)
            for n in re.findall(r'\d+', group)}

def emit(kind, **data):
    sink = SINK.get()
    if sink: sink({'type': kind, **data})

@contextmanager
def stage(name):
    start = time.perf_counter()
    emit('phase', phase=name)
    try: yield
    finally:
        trace = TRACE.get()
        if trace is not None:
            trace['timings_ms'][name] = round((time.perf_counter()-start)*1000, 1)

@contextmanager
def trace_request():
    state = {'timings_ms': {}, 'llm_calls': 0, 'llm_ms': 0}
    token = TRACE.set(state); start = time.perf_counter()
    try: yield state
    finally:
        state['timings_ms']['total'] = round((time.perf_counter()-start)*1000, 1)
        TRACE.reset(token)

class CitedParagraphs:
    def __init__(self, count):
        self.count=count; self.buffer=''; self.blocked=False
    def __call__(self, delta):
        import re
        self.buffer += delta
        if len(self.buffer)>100000: self.blocked=True; return
        while '\n\n' in self.buffer and not self.blocked:
            paragraph,self.buffer=self.buffer.split('\n\n',1)
            if not paragraph.strip(): continue
            cited=citation_numbers(paragraph)
            # Never stream a preamble, refusal or an invalid citation as verified text.
            if '[NO_EVIDENCE]' in paragraph or not cited or not cited <= set(range(1,self.count+1)):
                self.blocked=True; return
            emit('answer_delta', text=paragraph+'\n\n')
