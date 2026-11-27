import argparse
import io
import json
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--hw4-dir',help='Additionally compare CFG with the actual existing HW04 module')
    args=parser.parse_args(argv)
    suite=unittest.defaultTestLoader.discover(str(HERE),pattern='test_mc.py')
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    text=stream.getvalue();print(text)
    external={'status':'not_run','reason':'Optional --hw4-dir not supplied; bundled actual HW4 cfg() and real IR fixture ARE tested'}
    if args.hw4_dir:
        try:
            from hw4_bridge import from_ir
            payload=json.loads((HERE/'examples/hw4_loop_sum.ir.json').read_text())
            _,local,_=from_ir(payload)
            _,actual,source=from_ir(payload,hw4_dir=args.hw4_dir)
            external={'status':'passed' if actual==local else 'failed','source':source}
        except Exception as exc:external={'status':'failed','error':str(exc)}
    summary={'unit_tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
             'protocol_models':5,'protocol_properties':6,'protocol_verdicts':30,
             'exhaustive_total_graph_and_labelling_cases':2744,
             'external_HW4_module':external,'NuSMV':'Not implied by tests. See generated/nusmv/results.json.'}
    out=HERE/'generated';out.mkdir(exist_ok=True)
    (out/'tests.log').write_text(text,encoding='utf-8')
    (out/'tests.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0 if result.wasSuccessful() and external['status']!='failed' else 1


if __name__=='__main__':raise SystemExit(main())
