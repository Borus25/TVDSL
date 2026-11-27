"""Reuse HW4 cfg(): export a CONTROL-FLOW abstraction, not full IR semantics."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from checker import dot,lasso,sat,shortest_path,validate
from smv import render
from vendor.hw4_cfg import cfg as reference_cfg


def load_cfg(hw4_dir=None):
    if hw4_dir is None:
        return reference_cfg,{'source':'bundled verbatim HW4 cfg()','upstream_blob':'daa0105178dd8c6998860a86d3576d3261e4a045'}
    path=Path(hw4_dir).resolve()/'ir.py'
    if not path.is_file():raise ValueError(f'HW4 module not found: {path}')
    spec=importlib.util.spec_from_file_location('_hw4_for_temporal_mc',path)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module.cfg,{'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def from_ir(payload,function=None,hw4_dir=None):
    if payload.get('format')!='funny-ir/1':raise ValueError('expected HW4 funny-ir/1 JSON')
    functions=payload.get('functions',[])
    if function is None:
        if len(functions)!=1:raise ValueError('specify function for an IR with multiple functions')
        fn=functions[0]
    else:
        selected=[f for f in functions if f['name']==function]
        if len(selected)!=1:raise ValueError('function not found or ambiguous')
        fn=selected[0]
    cfg,provenance=load_cfg(hw4_dir);blocks=cfg(fn)
    if not blocks:raise ValueError('empty function')
    transitions={};labels={}
    for b in blocks:
        state=f'b{b["id"]}'
        targets=[f'b{s}' for s in b['successors']]
        terminal=fn['code'][b['end']-1]['op']=='return'
        if not targets and not terminal:raise ValueError('non-return dead end; refusing to call it successful termination')
        transitions[state]=targets or [state]
        labels[state]=['done'] if terminal else []
    model={'name':'hw4_control_flow','initial':'b0','transitions':transitions,'labels':labels,'fairness':[],
           'description':'Control-only overapproximation; guards/data/calls/exceptions erased; return-block is absorbing'}
    validate(model)
    return model,blocks,provenance


CFG_PROPERTIES=[
    {'id':'cfg_exit_possible','logic':'CTL','formula':'EF done'},
    {'id':'cfg_exit_inevitable','logic':'CTL','formula':'AF done'},
    {'id':'cfg_exit_stable','logic':'CTL','formula':'AG (done -> AX done)'},
]


def export(payload,out,function=None,hw4_dir=None):
    model,blocks,provenance=from_ir(payload,function,hw4_dir)
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    (out/'cfg.smv').write_text(render(model,CFG_PROPERTIES),encoding='utf-8')
    (out/'cfg.dot').write_text(dot(model),encoding='utf-8')
    (out/'model.json').write_text(json.dumps(model,indent=2)+'\n',encoding='utf-8')
    initial=model['initial'];done=sat(model,'done');not_done=set(model['transitions'])-done
    formulas=[('EF','done'),('AF','done'),('AG',('or',('not','done'),('AX','done')))]
    results=[]
    for prop,formula in zip(CFG_PROPERTIES,formulas):
        truth=sat(model,formula)
        results.append({**prop,'holds':initial in truth,'satisfaction_set':sorted(truth)})
    result={'engine':'python_explicit','abstraction':'CONTROL_FLOW_ONLY_NOT_PROGRAM_MODEL_CHECKING',
            'hw4_cfg_source':provenance,'blocks':blocks,'results':results,
            'exit_path_in_abstraction':shortest_path(model,initial,done),
            'nontermination_path_in_abstraction':lasso(model,not_done,initial),
            'limitations':['Branch guards are nondeterministic; calls, arithmetic and exceptions are erased.',
                           'Paths may be infeasible for concrete data. No concrete termination/correctness claim.',
                           'One step is one basic block; done denotes arrival at a return block, not its execution.']}
    (out/'analysis.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result
