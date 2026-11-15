"""Explicit offline replay CLI. Reads JSONL evidence; writes a NEW JSONL file."""
import argparse
import hashlib
import json
from pathlib import Path

from relationship_policy import derive,derive_focused_snapshot
from candidate_eligibility import derive as derive_eligibility

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--format',choices=('paired','focused-snapshot','reference-eligibility'),default='paired')
    args=parser.parse_args()
    raw=args.input.read_bytes();snapshot=hashlib.sha256(raw).hexdigest()
    # Parse and validate the whole input before creating an output file.
    cases=[json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    ids=[case['id'] for case in cases]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate source identities')
    if args.format=='reference-eligibility':
        results=[derive_eligibility(case['id'],case,snapshot) for case in cases]
    else:
        operation=derive if args.format=='paired' else derive_focused_snapshot
        results=[operation(case['id'],case.get('baseline',case.get('finding',case)),snapshot) for case in cases]
    with args.output.open('x',encoding='utf-8',newline='\n') as f:
        for result in results:f.write(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n')
    print(json.dumps(dict(candidates=len(results),source_snapshot=snapshot,
        inference_calls=0,database_writes=0,published_history_changed=False,output=str(args.output))))

if __name__=='__main__':main()
