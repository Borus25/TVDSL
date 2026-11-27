"""Build models, run exact checks, and export existing HW4 CFGs."""
import argparse
import json
from pathlib import Path
import sys

from checker import check,dot
from protocol import EXPECTED,PROPERTIES,models
from smv import render

HERE=Path(__file__).resolve().parent


def build(out=None):
    out=Path(out) if out else HERE/'generated'
    out.mkdir(parents=True,exist_ok=True)
    model_dir=HERE/'models';model_dir.mkdir(exist_ok=True)
    overview=[]
    for model in models():
        name=model['name'];report=check(model,PROPERTIES)
        verdicts=[r['holds'] for r in report['results']]
        if verdicts!=EXPECTED[name]:raise ValueError('unexpected Python verdicts for '+name)
        (model_dir/(name+'.json')).write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (model_dir/(name+'.smv')).write_text(render(model,PROPERTIES),encoding='utf-8')
        (out/(name+'.dot')).write_text(dot(model),encoding='utf-8')
        (out/(name+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        lines=[f'Model: {name}', 'Engine: Python explicit-state (NOT NuSMV)',f'Reachable: {", ".join(report["states_reachable"])}','']
        for prop in report['results']:
            lines.append(f'{prop["id"]}: {prop["holds"]} | {prop["formula"]}')
            lines.append(json.dumps(prop['evidence'],ensure_ascii=False))
        (out/(name+'.log')).write_text('\n'.join(lines)+'\n',encoding='utf-8')
        overview.append({'model':name,'expected':EXPECTED[name],'actual':verdicts,'passed':True})
    summary={'engine':'python_explicit_exact_for_supported_templates','model_count':len(overview),
             'property_count':len(PROPERTIES),'verdicts_checked':len(overview)*len(PROPERTIES),
             'results':overview,'nusmv_execution':'See generated/nusmv/results.json; not implied by Python success'}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description='HW5 temporal model checking, with HW4 CFG reuse')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('build',help='Emit SMV models, properties, Python exact verdicts, witnesses and DOT')
    sub.add_parser('test',help='Run all Python tests')
    nusmv=sub.add_parser('nusmv',help='Run actual external NuSMV/nuXmv')
    nusmv.add_argument('--binary');nusmv.add_argument('--allow-missing',action='store_true')
    export=sub.add_parser('export-hw4',help='Export a control-flow-only abstraction of HW4 IR')
    export.add_argument('ir_json');export.add_argument('--function');export.add_argument('--hw4-dir')
    export.add_argument('--out',default=str(HERE/'generated/hw4_cfg'))
    args=parser.parse_args(argv)
    try:
        if args.command=='build':
            summary=build();print(json.dumps({k:v for k,v in summary.items() if k!='results'},indent=2));return 0
        if args.command=='test':
            import run_tests
            return run_tests.main([])
        if args.command=='nusmv':
            import run_nusmv
            forwarded=(['--binary',args.binary] if args.binary else [])+(['--allow-missing'] if args.allow_missing else [])
            return run_nusmv.main(forwarded)
        if args.command=='export-hw4':
            from hw4_bridge import export as do_export
            payload=json.loads(Path(args.ir_json).read_text(encoding='utf-8'))
            report=do_export(payload,args.out,args.function,args.hw4_dir)
            print(json.dumps(report,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print('error: '+str(exc),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
