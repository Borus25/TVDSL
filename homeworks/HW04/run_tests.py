"""Reproducible tests; optional real HW3 source integration (no downloads)."""
import argparse
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import fixtures
from ir import Generator,outcome,optimize
from main import read_source

HERE=Path(__file__).resolve().parent


def integration(hw3):
    results=[]
    for case in fixtures.cases():
        path=HERE/'examples'/(case['name']+'.funny')
        try:
            payload=read_source(path,hw3)
            p=Generator().build(payload)
            q={'format':'funny-ir/1','functions':[optimize(fn,['const','algebraic','dce','cse']) for fn in p['functions']]}
            observations=[]
            for t in case['tests']:
                a=outcome(p,t['function'],t['args']);b=outcome(q,t['function'],t['args'])
                expected_ok=a.get('error')==t['error'] if 'error' in t else a=={'result':t['expected']}
                observations.append(a==b and expected_ok)
            results.append({'name':case['name'],'passed':all(observations)})
        except Exception as exc:
            results.append({'name':case['name'],'passed':False,'error':str(exc)})
    with tempfile.TemporaryDirectory() as td:
        bad=Path(td)/'bad.funny';bad.write_text('function f() returns r:int {r=true;}')
        try:
            read_source(bad,hw3)
            results.append({'name':'reject_hw3_error','passed':False})
        except ValueError:
            results.append({'name':'reject_hw3_error','passed':True})
    return results


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--hw3-dir',help='Require real source integration using this existing HW3 directory')
    args=parser.parse_args(argv)
    suite=unittest.defaultTestLoader.discover(str(HERE),pattern='test_ir.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    cases=fixtures.cases();inputs=sum(len(c['tests']) for c in cases)
    report={'unit_tests':result.testsRun,'unit_failures':len(result.failures),'unit_errors':len(result.errors),
            'typed_fixture_programs':len(cases),'pass_combinations':16,
            'runtime_cases_per_combination':inputs,'differential_checks':inputs*16,
            'random_integer_checks':700,'real_hw3_integration':{'status':'not_run','reason':'Use --hw3-dir to enable in your repository'}}
    if args.hw3_dir:
        records=integration(args.hw3_dir)
        report['real_hw3_integration']={'status':'passed' if all(r['passed'] for r in records) else 'failed','cases':records}
    output=HERE/'generated';output.mkdir(exist_ok=True)
    (output/'test_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if result.wasSuccessful() and report['real_hw3_integration']['status']!='failed' else 1


if __name__=='__main__':raise SystemExit(main())
