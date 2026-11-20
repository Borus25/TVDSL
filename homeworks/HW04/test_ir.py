import copy
import itertools
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

import fixtures as f
from ir import (C,F,V,CompileError,Generator,Interpreter,allocation,binary,cfg,cfg_dot,
                dump,graph_dot,liveness,metrics,optimize,outcome)
from main import build_artifacts,read_source

HERE=Path(__file__).resolve().parent
PASSES=['const','algebraic','dce','cse']


def variants():
    for size in range(5):
        for selected in itertools.combinations(PASSES,size):yield selected


def optimized(p,passes):
    q=copy.deepcopy(p);q['functions']=[optimize(fn,passes) for fn in p['functions']];return q


class PipelineTests(unittest.TestCase):
    def test_all_fixtures_all_pass_combinations(self):
        for case in f.cases():
            before=Generator().build(case['ast'])
            for passes in variants():
                after=optimized(before,passes)
                for test in case['tests']:
                    with self.subTest(case=case['name'],passes=passes,args=test['args']):
                        a=outcome(before,test['function'],test['args']);b=outcome(after,test['function'],test['args'])
                        self.assertEqual(a,b)
                        if 'error' in test:self.assertEqual(a.get('error'),test['error'])
                        else:self.assertEqual(a,{'result':test['expected']})

    def test_actual_hw3_golden_ast(self):
        ast=json.loads((HERE/'tests/hw3_pos_types_ok.json').read_text())
        before=Generator().build(ast)
        after=optimized(before,PASSES)
        for x in [-100,-1,0,1,7,100]:
            self.assertEqual(Interpreter(before).run('f',[x]),(x+1)*2)
            self.assertEqual(Interpreter(after).run('f',[x]),(x+1)*2)

    def test_greedy_coloring_valid_every_fixture(self):
        for case in f.cases():
            for fn in optimized(Generator().build(case['ast']),PASSES)['functions']:
                a=allocation(fn,1)
                for name,neighbors in a['graph'].items():
                    for neighbor in neighbors:
                        self.assertIn(name,a['graph'][neighbor])
                        self.assertNotEqual(a['colors'][name],a['colors'][neighbor])
                self.assertEqual(set(a['spills']),{n for n,c in a['colors'].items() if c>=1})

    def test_cfg_and_liveness_fixed_point(self):
        for case in f.cases():
            for fn in Generator().build(case['ast'])['functions']:
                blocks,_,_=liveness(fn)
                self.assertEqual(blocks[0]['start'],0)
                self.assertEqual(blocks[-1]['end'],len(fn['code']))
                for block in blocks:
                    live_out=set().union(*(set(blocks[s]['live_in']) for s in block['successors']))
                    self.assertEqual(live_out,set(block['live_out']))
                    used=set();defined=set()
                    from ir import uses,defs
                    for i in fn['code'][block['start']:block['end']]:
                        used|=uses(i)-defined;defined|=defs(i)
                    self.assertEqual(set(block['live_in']),used|(live_out-defined))

    def test_no_opt_is_identity(self):
        for case in f.cases():
            p=Generator().build(case['ast'])
            self.assertEqual(p,optimized(p,[]))

    def test_optimizer_idempotent(self):
        for case in f.cases():
            p=Generator().build(case['ast']);a=optimized(p,PASSES)
            self.assertEqual(a,optimized(a,PASSES))

    def test_optimizations_do_not_mutate_input(self):
        p=Generator().build(f.cases()[0]['ast']);saved=copy.deepcopy(p)
        optimized(p,PASSES)
        self.assertEqual(p,saved)

    def test_cse_reduces_repeated_computations(self):
        case=next(c for c in f.cases() if c['name']=='cse')
        fn=Generator().build(case['ast'])['functions'][0]
        after=optimize(fn,['cse'])
        count=lambda code:sum(i['op']=='bin' and i['operator']=='+' for i in code)
        self.assertEqual(count(fn['code']),2)
        self.assertEqual(count(after['code']),1)

    def test_passes_independently_have_effect(self):
        case=next(c for c in f.cases() if c['name']=='identities')
        fn=Generator().build(case['ast'])['functions'][0]
        self.assertNotEqual(fn['code'],optimize(fn,['algebraic'])['code'])
        case=next(c for c in f.cases() if c['name']=='constants')
        fn=Generator().build(case['ast'])['functions'][0]
        self.assertNotEqual(fn['code'],optimize(fn,['const'])['code'])
        case=next(c for c in f.cases() if c['name']=='dead_code')
        fn=Generator().build(case['ast'])['functions'][0]
        self.assertLess(len(optimize(fn,['dce'])['code']),len(fn['code']))

    def test_metrics_reduce_demo(self):
        p=Generator().build(f.cases()[0]['ast']);q=optimized(p,PASSES)
        a=metrics(p['functions'][0]);b=metrics(q['functions'][0])
        self.assertLess(b['instructions'],a['instructions'])
        self.assertLess(b['temporaries'],a['temporaries'])

    def test_parameters_interfere_at_entry(self):
        fn=Generator().build(f.program(f.fn('f',[('x','int'),('y','int')],[f.assign('r',f.binop('+',f.ident('x'),f.ident('y')))])))['functions'][0]
        a=allocation(fn);x,y=fn['params']
        self.assertIn(y,a['graph'][x])
        self.assertNotEqual(a['colors'][x],a['colors'][y])

    def test_labels_globally_unique(self):
        case=next(c for c in f.cases() if c['name']=='mutual_recursion')
        p=Generator().build(case['ast'])
        labels=[i['label'] for fn in p['functions'] for i in fn['code'] if i['op']=='label']
        self.assertEqual(len(labels),len(set(labels)))

    def test_function_scopes_unique(self):
        case=next(c for c in f.cases() if c['name']=='shadowing')
        fn=Generator().build(case['ast'])['functions'][0]
        self.assertEqual(len([name for name in fn['types'] if name.endswith('_x')]),2)

    def test_short_circuit_has_branches(self):
        case=next(c for c in f.cases() if c['name']=='short_and')
        fn=Generator().build(case['ast'])['functions'][0]
        self.assertIn('branch',[i['op'] for i in fn['code']])
        self.assertEqual(Interpreter({'functions':[fn]}).run('f',[]),False)

    def test_functional_array_does_not_mutate_arguments(self):
        case=next(c for c in f.cases() if c['name']=='array_store')
        p=Generator().build(case['ast']);args=[[1,2]]
        self.assertEqual(Interpreter(p).run('f',args),100)
        self.assertEqual(args,[[1,2]])

    def test_preserve_trapping_dead_operations(self):
        for name,op in [('dead_division','bin'),('dead_load','load'),('dead_call','call')]:
            case=next(c for c in f.cases() if c['name']==name)
            p=optimized(Generator().build(case['ast']),PASSES)
            self.assertTrue(any(i['op']==op for fn in p['functions'] for i in fn['code']))

    def test_json_ir_roundtrip(self):
        for case in f.cases():
            p=Generator().build(case['ast']);q=json.loads(json.dumps(p))
            self.assertEqual(q,p)
            t=case['tests'][0]
            self.assertEqual(outcome(p,t['function'],t['args']),outcome(q,t['function'],t['args']))

    def test_graph_exports(self):
        fn=Generator().build(f.cases()[0]['ast'])['functions'][0]
        self.assertTrue(cfg_dot(fn).startswith('digraph CFG'))
        self.assertTrue(graph_dot(allocation(fn)).startswith('graph Interference'))
        self.assertIn('function f',dump({'functions':[fn]}))


class SafetyTests(unittest.TestCase):
    def test_reject_error_envelope(self):
        with self.assertRaises(CompileError):Generator().build({'ok':False,'ast':f.cases()[0]['ast']})
        with self.assertRaises(CompileError):Generator().build({'ok':True,'ast':f.cases()[0]['ast'],'diagnostics':[{}]})

    def test_reject_poisoned_type(self):
        p=copy.deepcopy(f.cases()[0]['ast']);p['functions'][0]['body']['stmts'][-1]['value']['type']='<error>'
        with self.assertRaises(CompileError):Generator().build(p)

    def test_reject_untyped_expression(self):
        p=f.program(f.fn('f',[],[f.assign('r',f.integer(1))]));p['functions'][0]['body']['stmts'][0]['value'].pop('type')
        with self.assertRaises(CompileError):Generator().build(p)

    def test_reject_unknown_ast(self):
        with self.assertRaises(CompileError):Generator().build({'node':'NotProgram'})
        p=f.program(f.fn('f',[],[{'node':'Unsupported'}]))
        with self.assertRaises(CompileError):Generator().build(p)

    def test_reject_unknown_pass(self):
        fn=Generator().build(f.cases()[0]['ast'])['functions'][0]
        with self.assertRaises(CompileError):optimize(fn,['fake'])

    def test_integer_division_not_python_float(self):
        self.assertEqual(binary('/',-5,2),-2)
        self.assertEqual(binary('/',5,-2),-2)
        self.assertEqual(binary('/',10**100,3),10**100//3)
        with self.assertRaises(ZeroDivisionError):binary('/',1,0)

    def test_runtime_arguments_are_typed(self):
        program=Generator().build(f.cases()[0]['ast'])
        self.assertIn('error',outcome(program,'f',[True]))
        self.assertIn('error',outcome(program,'f',[]))

    def test_cfg_unknown_target(self):
        with self.assertRaises(CompileError):cfg({'code':[{'op':'jump','target':'missing'}]})

    def test_cfg_fallthrough_and_return(self):
        fn={'code':[{'op':'copy','dst':'x','args':[C(1)]},{'op':'label','label':'A'},{'op':'return','args':[V('x')]}]}
        b=cfg(fn);self.assertEqual(b[0]['successors'],[1]);self.assertEqual(b[1]['successors'],[])

    def test_unreachable_blocks_marked(self):
        fn={'code':[{'op':'return','args':[C(1)]},{'op':'copy','dst':'x','args':[C(2)]},{'op':'return','args':[V('x')]}]}
        b=cfg(fn);self.assertTrue(b[0]['reachable']);self.assertFalse(b[1]['reachable'])

    def test_interpreter_budget(self):
        p={'functions':[{'name':'f','params':[],'code':[{'op':'label','label':'L'},{'op':'jump','target':'L'}]}]}
        with self.assertRaisesRegex(RuntimeError,'step limit'):Interpreter(p,step_limit=5).run('f',[])

    def test_cse_redefinition_direct_ir(self):
        fn={'name':'f','params':['x'],'param_types':['int'],'return_type':'int','types':{'x':'int','t1':'int'},'code':[
            {'op':'bin','dst':'t1','operator':'+','args':[V('x'),C(1)]},
            {'op':'copy','dst':'t1','args':[C(99)]},
            {'op':'bin','dst':'t2','operator':'+','args':[V('x'),C(1)]},
            {'op':'return','args':[V('t2')]}]}
        for passes in variants():
            after=optimize(fn,passes)
            self.assertEqual(Interpreter({'functions':[after]}).run('f',[3]),4)

    def test_randomized_integer_inputs(self):
        rng=random.Random(401)
        names={'constants','branch','cse','cse_kill','identities','redefinition','division'}
        for case in f.cases():
            if case['name'] not in names:continue
            p=Generator().build(case['ast']);q=optimized(p,PASSES)
            for _ in range(100):
                values=[rng.randint(-10000,10000) for _ in p['functions'][0]['params']]
                self.assertEqual(outcome(p,'f',values),outcome(q,'f',values))


class CLITests(unittest.TestCase):
    def test_ast_cli_creates_all_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            proc=subprocess.run([sys.executable,str(HERE/'main.py'),str(HERE/'tests/hw3_pos_types_ok.json'),'--ast','--opt',','.join(PASSES),'--out',td,'--run','f','--args','[3]','--registers','1'],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            for name in ['ir_before.json','ir_after.json','ir_before.txt','ir_after.txt','analysis.json','metrics.json','cfg_0.dot','interference_0.dot','verification.json']:
                self.assertTrue((Path(td)/name).is_file(),name)
            self.assertTrue(json.loads((Path(td)/'verification.json').read_text())[0]['passed'])

    def test_cli_defaults_no_opt(self):
        with tempfile.TemporaryDirectory() as td:
            proc=subprocess.run([sys.executable,str(HERE/'main.py'),str(HERE/'tests/hw3_pos_types_ok.json'),'--ast','--out',td],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertEqual((Path(td)/'ir_before.json').read_bytes(),(Path(td)/'ir_after.json').read_bytes())

    def test_cli_negative(self):
        with tempfile.TemporaryDirectory() as td:
            for args in [['--opt','bad'],['--registers','0']]:
                proc=subprocess.run([sys.executable,str(HERE/'main.py'),str(HERE/'tests/hw3_pos_types_ok.json'),'--ast','--out',td,*args],capture_output=True,text=True)
                self.assertNotEqual(proc.returncode,0)

    def test_missing_frontend_explained(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(CompileError,'HW3 not found'):read_source('missing.funny',td)

    def test_subprocess_bridge_contract(self):
        # Real subprocess protocol test with an explicitly fake frontend, not HW3.
        with tempfile.TemporaryDirectory() as td:
            script=Path(td)/'main.py'
            ast=f.cases()[0]['ast']
            script.write_text('import json\nprint('+repr(json.dumps({'ok':True,'ast':ast,'diagnostics':[]}))+')\n')
            payload=read_source(HERE/'examples/constants.funny',td)
            self.assertEqual(payload['ast'],ast)
            script.write_text('import sys\nprint(\'{"ok":false,"diagnostics":[{"code":"E_TEST","message":"bad","line":1,"col":2}]}\')\nsys.exit(1)\n')
            with self.assertRaisesRegex(CompileError,'E_TEST'):read_source(HERE/'examples/constants.funny',td)


if __name__=='__main__':unittest.main()
