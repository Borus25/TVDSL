import copy
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from checker import (ModelError,ax,check,evidence,ex,lasso,reachable,sat,shortest_path,validate,verify_path)
from protocol import EXPECTED,PROPERTIES,models
from smv import render
from hw4_bridge import from_ir,export,load_cfg
from run_nusmv import find_binary,parse_result,run

HERE=Path(__file__).resolve().parent


def named(name):return next(m for m in models() if m['name']==name)


def all_simple_lassos(model):
    edges=model['transitions'];found=[]
    def walk(path):
        for target in edges[path[-1]]:
            if target in path:
                start=path.index(target)
                found.append((path[:start],path[start:]))
            else:walk(path+[target])
    walk([model['initial']])
    return found


class ProtocolTests(unittest.TestCase):
    def test_all_thirty_expected_verdicts(self):
        for model in models():
            report=check(model,PROPERTIES)
            self.assertEqual([p['holds'] for p in report['results']],EXPECTED[model['name']])

    def test_original_is_exact_P09_graph(self):
        m=named('original')
        self.assertEqual(m['initial'],'s0')
        self.assertEqual(m['transitions'],{'s0':['s1'],'s1':['s1','s2'],'s2':['s0'],'s3':['s3']})
        self.assertEqual(m['labels'],{'s0':['idle'],'s1':['req'],'s2':['ack'],'s3':['error']})
        self.assertEqual(m['fairness'],[])

    def test_reachable_original_and_fixed(self):
        for name in ['original','fixed']:
            self.assertEqual(reachable(named(name)),{'s0','s1','s2'})

    def test_fix_changes_exactly_one_transition(self):
        a=named('original');b=named('fixed')
        edges=lambda m:{(s,t) for s,ts in m['transitions'].items() for t in ts}
        self.assertEqual(edges(a)-edges(b),{('s1','s1')})
        self.assertEqual(edges(b)-edges(a),set())
        self.assertEqual(a['labels'],b['labels'])

    def test_EF_ack_iterations_original(self):
        r=check(named('original'),PROPERTIES)
        self.assertEqual(r['iterations']['EF_ack'],[['s2'],['s1','s2'],['s0','s1','s2']])

    def test_AF_ack_iterations_original_and_fixed(self):
        a=check(named('original'),PROPERTIES);b=check(named('fixed'),PROPERTIES)
        self.assertEqual(a['sets']['AF_ack'],['s2'])
        self.assertEqual(a['iterations']['AF_ack'],[['s2']])
        self.assertEqual(b['iterations']['AF_ack'],[['s2'],['s1','s2'],['s0','s1','s2']])

    def test_AG_error_complement(self):
        for m in models():
            self.assertEqual(sat(m,('AG',('not','error'))),set(m['transitions'])-sat(m,('EF','error')))

    def test_original_minimal_response_lasso(self):
        r=check(named('original'),PROPERTIES)['results'][3]['evidence']
        self.assertEqual(r['prefix'],['s0','s1'])
        self.assertEqual(r['cycle'],['s1','s1'])
        self.assertEqual(r['unanswered_request_at'],1)

    def test_all_finite_and_infinite_traces_valid(self):
        for m in models():
            for p in check(m,PROPERTIES)['results']:
                e=p['evidence']
                if 'path' in e:
                    self.assertEqual(e['path'][0],m['initial'])
                    self.assertTrue(verify_path(m,e['path']))
                if 'cycle' in e:
                    self.assertTrue(verify_path(m,e['prefix']))
                    self.assertEqual(e['prefix'][0],m['initial'])
                    self.assertTrue(verify_path(m,e['cycle']))
                    self.assertGreaterEqual(len(e['cycle']),2)
                    self.assertEqual(e['cycle'][0],e['cycle'][-1])
                    self.assertEqual(e['prefix'][-1],e['cycle'][0])
                    self.assertTrue(all('ack' not in m['labels'][s] for s in e['cycle']))
                    if p['id']=='p04_response':
                        pos=e['unanswered_request_at']
                        self.assertIn('req',m['labels'][e['prefix'][pos]])
                        self.assertTrue(all('ack' not in m['labels'][s] for s in e['prefix'][pos:]))

    def test_EF_false_requires_absence_certificate(self):
        r=check(named('original'),PROPERTIES)['results'][5]
        self.assertFalse(r['holds'])
        self.assertEqual(r['evidence']['kind'],'absence_certificate')
        self.assertEqual(r['evidence']['satisfaction_EF_error'],['s3'])
        self.assertTrue(r['evidence']['closed_under_successors'])
        self.assertFalse(set(r['evidence']['reachable'])&set(r['evidence']['error_states']))

    def test_EF_true_has_positive_witness(self):
        r=check(named('error_transition'),PROPERTIES)['results'][5]
        self.assertTrue(r['holds'])
        self.assertEqual(r['evidence']['kind'],'existential_witness')
        self.assertEqual(r['evidence']['path'],['s0','s1','s3'])

    def test_mutations_exercise_every_safety_property(self):
        for i in range(3):
            self.assertTrue(any(not EXPECTED[m['name']][i] for m in models()))

    def test_safety_and_liveness_separated(self):
        r=check(named('original'),PROPERTIES)['results']
        self.assertTrue(all(p['holds'] for p in r[:3]))
        self.assertFalse(any(p['holds'] for p in r[3:5]))


class CTLTests(unittest.TestCase):
    def test_all_total_three_state_graphs_all_p_labellings(self):
        # 7^3 total successor relations * 2^3 labellings = 2744 cases.
        states=['a','b','c']
        subsets=[list(c) for n in range(1,4) for c in itertools.combinations(states,n)]
        for successors in itertools.product(subsets,repeat=3):
            for bits in itertools.product([False,True],repeat=3):
                m={'initial':'a','transitions':dict(zip(states,successors)),
                   'labels':{s:['p'] if bit else [] for s,bit in zip(states,bits)},'fairness':[]}
                p={s for s,bit in zip(states,bits) if bit}
                forward=reachable(m)
                self.assertEqual('a' in sat(m,('EF','p')),bool(forward&p))
                self.assertEqual('a' in sat(m,('AG','p')),forward<=p)
                self.assertEqual('a' in sat(m,('AF','p')),lasso(m,set(states)-p,'a') is None)
                self.assertEqual('a' in sat(m,('EG','p')),lasso(m,p,'a') is not None)
                self.assertEqual(sat(m,('AX','p')),set(states)-sat(m,('EX',('not','p'))))

    def test_until_operators(self):
        m=named('original')
        self.assertEqual(sat(m,('EU',('not','error'),'ack')),{'s0','s1','s2'})
        self.assertEqual(sat(m,('AU',('not','error'),'ack')),{'s2'})
        self.assertEqual(sat(named('fixed'),('AU',('not','error'),'ack')),{'s0','s1','s2'})

    def test_template_ltl_against_independent_lasso_enumeration(self):
        for m in models():
            lassos=all_simple_lassos(m)
            for p in PROPERTIES[1:5]:
                values=[]
                for prefix,cycle in lassos:
                    path=prefix+cycle;labels=m['labels'];truth=True
                    if p['id']=='p02_no_overlap':truth=all(not {'req','ack'}<=set(labels[s]) for s in path)
                    elif p['id']=='p03_ack_to_idle':
                        edges=list(zip(path,path[1:]))+[(cycle[-1],cycle[0])]
                        truth=all('ack' not in labels[a] or 'idle' in labels[b] for a,b in edges)
                    elif p['id']=='p05_recurring_ack':truth=any('ack' in labels[s] for s in cycle)
                    else:
                        has_ack_cycle=any('ack' in labels[s] for s in cycle)
                        truth=has_ack_cycle or all('req' not in labels[s] or any('ack' in labels[t] for t in path[i:]) for i,s in enumerate(path))
                    values.append(truth)
                self.assertEqual(all(values),m['initial'] in sat(m,p['ctl']))

    def test_reject_deadlock_and_unknown_state(self):
        m=named('original');m['transitions']['s1']=[]
        with self.assertRaises(ModelError):validate(m)
        m=named('original');m['transitions']['s1']=['bad']
        with self.assertRaises(ModelError):validate(m)

    def test_reject_silent_fairness_approximation(self):
        m=named('original');m['fairness']=['ack']
        with self.assertRaises(ModelError):sat(m,('AF','ack'))
        with self.assertRaises(ModelError):render(m,PROPERTIES)

    def test_reject_empty_and_invalid_initial(self):
        with self.assertRaises(ModelError):validate({'transitions':{}})
        m=named('original');m['initial']='bad'
        with self.assertRaises(ModelError):validate(m)

    def test_booleans_and_unsupported_operator(self):
        m=named('original')
        self.assertEqual(sat(m,True),set(m['transitions']))
        self.assertEqual(sat(m,False),set())
        with self.assertRaises(ModelError):sat(m,('LTL_U','req','ack'))


class ExportTests(unittest.TestCase):
    def test_generated_SMV_transition_table_matches_original(self):
        text=render(named('original'),PROPERTIES)
        for line in ['init(state) := s0;','state = s0 : s1;', 'state = s1 : {s1, s2};',
                     'state = s2 : s0;','state = s3 : s3;']:
            self.assertIn(line,text)
        for p in PROPERTIES:self.assertIn('NAME '+p['id']+' := '+p['formula']+';',text)
        self.assertEqual(text.count('LTLSPEC NAME'),4)
        self.assertEqual(text.count('CTLSPEC NAME'),2)
        self.assertNotIn('\nFAIRNESS',text)
        self.assertNotIn('\nINVAR ',text)

    def test_SMV_fixed_keeps_unreachable_error(self):
        text=render(named('fixed'),PROPERTIES)
        self.assertIn('state = s1 : s2;',text)
        self.assertIn('state = s3 : s3;',text)
        self.assertIn('error := (state = s3);',text)

    def test_unsafe_identifier_rejected(self):
        m=named('original');m['labels']['s0'].append('x; INVAR FALSE')
        with self.assertRaises(ValueError):render(m,PROPERTIES)

    def test_real_hw4_loop_IR_CFG_reused(self):
        payload=json.loads((HERE/'examples/hw4_loop_sum.ir.json').read_text())
        m,blocks,source=from_ir(payload)
        self.assertEqual([(b['start'],b['end']) for b in blocks],[(0,2),(2,7),(7,13),(13,16)])
        self.assertEqual(m['transitions'],{'b0':['b1'],'b1':['b2','b3'],'b2':['b1'],'b3':['b3']})
        self.assertEqual(sat(m,('EF','done')),{'b0','b1','b2','b3'})
        self.assertEqual(sat(m,('AF','done')),{'b3'})
        self.assertIn('HW4',source['source'])

    def test_hw4_export_files_and_lasso(self):
        with tempfile.TemporaryDirectory() as td:
            payload=json.loads((HERE/'examples/hw4_loop_sum.ir.json').read_text())
            result=export(payload,td)
            for name in ['cfg.smv','cfg.dot','model.json','analysis.json']:self.assertTrue((Path(td)/name).is_file())
            self.assertFalse(result['results'][1]['holds'])
            self.assertEqual(result['nontermination_path_in_abstraction']['cycle'],['b1','b2','b1'])

    def test_external_hw4_module_loading(self):
        with tempfile.TemporaryDirectory() as td:
            code=(HERE/'vendor/hw4_cfg.py').read_text()
            (Path(td)/'ir.py').write_text(code)
            external,source=load_cfg(td)
            reference,_=load_cfg()
            fn=json.loads((HERE/'examples/hw4_loop_sum.ir.json').read_text())['functions'][0]
            self.assertEqual(reference(fn),external(fn))
            self.assertIn('sha256',source)

    def test_invalid_hw4_input_rejected(self):
        with self.assertRaises(ValueError):from_ir({'format':'bad'})
        payload=json.loads((HERE/'examples/hw4_loop_sum.ir.json').read_text())
        with self.assertRaises(ValueError):from_ir(payload,'missing')
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):load_cfg(td)

    def test_return_stuttering_totalization(self):
        payload={'format':'funny-ir/1','functions':[{'name':'f','code':[{'op':'return','args':[{'const':1}]}]}]}
        m,_,_=from_ir(payload)
        self.assertEqual(m['transitions'],{'b0':['b0']})
        self.assertEqual(sat(m,('AF','done')),{'b0'})

    def test_non_return_dead_end_not_called_done(self):
        payload={'format':'funny-ir/1','functions':[{'name':'f','code':[{'op':'copy','dst':'x','args':[{'const':1}]}]}]}
        with self.assertRaises(ValueError):from_ir(payload)


class RunnerTests(unittest.TestCase):
    def test_parse_NuSMV_true_and_false(self):
        for verdict,expected in [('true',True),('false',False)]:
            self.assertEqual(parse_result('-- specification AG !error is '+verdict+'\n'),expected)
        self.assertFalse(parse_result('-- specification EF error is false\n-- no counterexample\n'))

    def test_reject_missing_or_ambiguous_verdict(self):
        with self.assertRaises(ValueError):parse_result('syntax error')
        with self.assertRaises(ValueError):parse_result('-- specification p is true\n-- specification q is false\n')

    def test_missing_tool_is_never_a_successful_tool_run(self):
        with tempfile.TemporaryDirectory() as td:
            r=run(binary=str(Path(td)/'definitely_missing'),out=td)
            self.assertEqual(r['status'],'not_run')
            self.assertEqual(r['results'],[])
            self.assertTrue((Path(td)/'NOT_RUN.txt').is_file())

    def test_build_CLI(self):
        p=subprocess.run([sys.executable,str(HERE/'main.py'),'build'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout)['verdicts_checked'],30)

    def test_external_runner_missing_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            args=[sys.executable,str(HERE/'run_nusmv.py'),'--binary',str(Path(td)/'missing'),'--out',td]
            self.assertEqual(subprocess.run(args,capture_output=True).returncode,2)
            self.assertEqual(subprocess.run(args+['--allow-missing'],capture_output=True).returncode,0)
            self.assertEqual(json.loads((Path(td)/'results.json').read_text())['status'],'not_run')

    def test_shortest_path_and_closed_lasso_helpers(self):
        m=named('original')
        self.assertEqual(shortest_path(m,'s0',{'s2'}),['s0','s1','s2'])
        self.assertIsNone(shortest_path(m,'s0',{'s3'}))
        self.assertIsNone(lasso(m,{'s2'},'s2'))
        self.assertFalse(verify_path(m,['s0','s3']))


if __name__=='__main__':unittest.main()
