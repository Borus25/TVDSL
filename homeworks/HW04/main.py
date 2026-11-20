"""HW4 CLI. No imports of HW3 modules: subprocess avoids main/parser collisions."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

from ir import (CompileError, Generator, allocation, cfg_dot, dump, graph_dot,
                metrics, optimize, outcome)

HERE=Path(__file__).resolve().parent


def read_source(path,hw3):
    entry=Path(hw3).resolve()/'main.py'
    if not entry.is_file():
        raise CompileError(f'HW3 not found at {entry}; put HW04 next to HW03 or use --hw3-dir')
    process=subprocess.run([sys.executable,str(entry),str(Path(path).resolve()),'--semantic','--json'],
                           cwd=entry.parent,capture_output=True,text=True)
    try:payload=json.loads(process.stdout)
    except ValueError as exc:raise CompileError('HW3 returned no JSON: '+process.stderr.strip()) from exc
    if process.returncode!=0 or not payload.get('ok'):
        messages=['{code}: {message} at {line}:{col}'.format(**d) for d in payload.get('diagnostics',[])]
        raise CompileError('HW3 errors; IR not generated:\n'+'\n'.join(messages))
    return payload


def build_artifacts(payload,passes,registers=None):
    before=Generator().build(payload)
    after=copy.deepcopy(before)
    after['functions']=[optimize(fn,passes) for fn in before['functions']]
    allocations={fn['name']:allocation(fn,registers) for fn in after['functions']}
    report={a['name']:{'before':metrics(a,registers),'after':metrics(b,registers)}
            for a,b in zip(before['functions'],after['functions'])}
    return before,after,allocations,report


def main(argv=None):
    parser=argparse.ArgumentParser(description='Funny HW4: IR, CFG, optimization, coloring')
    parser.add_argument('input',nargs='?',help='Funny source or typed AST JSON with --ast')
    parser.add_argument('--ast',action='store_true',help='Read annotated HW3 JSON (no frontend invocation)')
    parser.add_argument('--hw3-dir',default=str(HERE.parent/'HW03'))
    parser.add_argument('--opt',default='',help='Comma-separated const,algebraic,dce,cse; default none')
    parser.add_argument('--out',default='generated',help='Output directory')
    parser.add_argument('--registers',type=int,help='Physical budget; only report spill candidates')
    parser.add_argument('--run',metavar='FUNCTION',help='Execute before/after and compare observations')
    parser.add_argument('--args',default='[]',help='JSON list of runtime arguments')
    parser.add_argument('--verify',help='JSON list of {function,args,expected?} execution cases')
    parser.add_argument('--test',action='store_true')
    args=parser.parse_args(argv)
    if args.test:
        import run_tests
        return run_tests.main()
    if not args.input:parser.error('input required except with --test')
    if args.registers is not None and args.registers<1:parser.error('--registers must be positive')
    try:
        passes=[p.strip() for p in args.opt.split(',') if p.strip()]
        payload=json.loads(Path(args.input).read_text(encoding='utf-8-sig')) if args.ast else read_source(args.input,args.hw3_dir)
        before,after,allocs,report=build_artifacts(payload,passes,args.registers)
        output=Path(args.out);output.mkdir(parents=True,exist_ok=True)
        def write_json(name,obj):
            (output/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        write_json('ir_before.json',before);write_json('ir_after.json',after)
        (output/'ir_before.txt').write_text(dump(before),encoding='utf-8')
        (output/'ir_after.txt').write_text(dump(after),encoding='utf-8')
        write_json('analysis.json',allocs);write_json('metrics.json',report)
        for fn in after['functions']:
            # Filenames use indices, never unchecked AST-provided names.
            index=after['functions'].index(fn)
            (output/f'cfg_{index}.dot').write_text(cfg_dot(fn),encoding='utf-8')
            (output/f'interference_{index}.dot').write_text(graph_dot(allocs[fn['name']]),encoding='utf-8')
        checks=[]
        if args.run:
            values=json.loads(args.args)
            if not isinstance(values,list):raise CompileError('--args must be a JSON list')
            checks.append({'function':args.run,'args':values})
        if args.verify:
            cases=json.loads(Path(args.verify).read_text(encoding='utf-8'))
            if not isinstance(cases,list):raise CompileError('verification file must contain a list')
            checks.extend(cases)
        verification=[]
        for case in checks:
            a=outcome(before,case['function'],case['args']);b=outcome(after,case['function'],case['args'])
            ok=a==b and ('expected' not in case or a=={'result':case['expected']})
            verification.append({**case,'before':a,'after':b,'passed':ok})
        if checks:write_json('verification.json',verification)
        print(json.dumps({'optimizations':passes,'metrics':report,'verification':verification},ensure_ascii=False,indent=2))
        return 0 if all(v['passed'] for v in verification) else 1
    except (CompileError,OSError,ValueError,KeyError,TypeError) as exc:
        print(f'error: {exc}',file=sys.stderr);return 1


if __name__=='__main__':
    raise SystemExit(main())
