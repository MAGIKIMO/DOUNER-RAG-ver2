"""Run reference-source checks; factual/citation entailment still needs human review."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import httpx


def run(cases, api_url):
    results=[]
    with httpx.Client(timeout=180,follow_redirects=False) as client:
        for case in cases:
            try:
                response=client.post(api_url.rstrip('/')+'/api/v1/ask',json={'question':case['question'],'language':'ko'})
                response.raise_for_status();data=response.json()
                urls=[s['url'] for s in data.get('sources',[])]
                expected=case.get('reference_urls',[])
                hit=any(url in urls for url in expected) if expected else None
                result={'id':case['id'],'question':case['question'],'reference_hit':hit,
                    'reference_reviewed':case.get('reference_reviewed',False),'status':data.get('debug_info',{}).get('status'),
                    'answer':data.get('answer'),'sources':data.get('sources',[]),
                    'human_checks':case['human_checks'],'human_answer_correct':None,'human_citations_supported':None}
            except (httpx.HTTPError,ValueError,KeyError):
                result={'id':case['id'],'question':case['question'],'error':'request_failed',
                    'reference_reviewed':case.get('reference_reviewed',False),
                    'reference_hit':False if case.get('reference_urls') else None}
            results.append(result)
            print(json.dumps({k:result.get(k) for k in ('id','reference_hit','status','error')},ensure_ascii=False),flush=True)
    verified=[r for r in results if r.get('reference_reviewed') and r.get('reference_hit') is not None]
    return {'created_at':datetime.now(timezone.utc).isoformat(),'cases':results,
        'verified_reference_hit_rate':sum(r['reference_hit'] for r in verified)/len(verified) if verified else None,
        'note':'Source hit is not answer correctness or citation entailment. Unreviewed reference URLs are provisional.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--api-url',default='http://localhost:8000')
    p.add_argument('--cases',type=Path,default=Path(__file__).with_name('rag_eval_cases.json'))
    p.add_argument('--limit',type=int,default=5)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if not 1<=args.limit<=50:p.error('limit must be 1..50')
    cases=json.loads(args.cases.read_text(encoding='utf-8'))[:args.limit]
    args.output.write_text(json.dumps(run(cases,args.api_url),ensure_ascii=False,indent=2),encoding='utf-8')
