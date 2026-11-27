"""Exact explicit-state CTL checker and witnesses for the six protocol specs.
No general LTL parser: the supported LTL templates are translated explicitly
in protocol.py to equivalent universal CTL properties on total fair-free graphs.
"""
from collections import deque
import json


class ModelError(ValueError):pass


def validate(model):
    if model.get('fairness'):
        raise ModelError('Python checker does not support fairness; refusing silent approximation')
    edges=model.get('transitions',{})
    if not edges:raise ModelError('empty state space')
    if model.get('initial') not in edges:raise ModelError('invalid initial state')
    if set(model.get('labels',{}))!=set(edges):raise ModelError('labels must cover exactly the states')
    for s,targets in edges.items():
        if not isinstance(s,str) or not s:raise ModelError('invalid state identifier')
        if not targets:raise ModelError(f'deadlock at {s}; explicit self-loop required')
        if set(targets)-set(edges):raise ModelError(f'unknown successor of {s}')
    return model


def reachable(model,start=None):
    validate(model);seen=set();pending=[start or model['initial']]
    while pending:
        s=pending.pop()
        if s in seen:continue
        seen.add(s);pending.extend(model['transitions'][s])
    return seen


def shortest_path(model,start,goals,allowed=None):
    edges=model['transitions'];allowed=set(edges) if allowed is None else set(allowed)
    if start not in allowed:return None
    parents={start:None};queue=deque([start]);goals=set(goals)
    while queue:
        s=queue.popleft()
        if s in goals:
            path=[]
            while s is not None:path.append(s);s=parents[s]
            return path[::-1]
        for t in sorted(set(edges[s])&allowed):
            if t not in parents:parents[t]=s;queue.append(t)
    return None


def ex(model,states):return {s for s,targets in model['transitions'].items() if set(targets)&states}
def ax(model,states):return {s for s,targets in model['transitions'].items() if set(targets)<=states}


def fixed_point(seed,step):
    value=set(seed);history=[sorted(value)]
    while True:
        new=set(step(value))
        if new==value:return value,history
        value=new;history.append(sorted(value))


def sat(model,formula):
    validate(model);states=set(model['transitions'])
    if formula is True:return states
    if formula is False:return set()
    if isinstance(formula,str):return {s for s in states if formula in model['labels'][s]}
    op,*args=formula
    if op=='not':return states-sat(model,args[0])
    if op=='and':return sat(model,args[0])&sat(model,args[1])
    if op=='or':return sat(model,args[0])|sat(model,args[1])
    if op=='EX':return ex(model,sat(model,args[0]))
    if op=='AX':return ax(model,sat(model,args[0]))
    if op in ('EF','AF','EG','AG'):
        p=sat(model,args[0])
        if op=='EF':return fixed_point(p,lambda z:p|ex(model,z))[0]
        if op=='AF':return fixed_point(p,lambda z:p|ax(model,z))[0]
        if op=='EG':return fixed_point(states,lambda z:p&ex(model,z))[0]
        return fixed_point(states,lambda z:p&ax(model,z))[0]
    if op in ('EU','AU'):
        p,q=sat(model,args[0]),sat(model,args[1])
        pred=ex if op=='EU' else ax
        return fixed_point(q,lambda z:q|(p&pred(model,z)))[0]
    raise ModelError(f'unsupported CTL operator {op}')


def lasso(model,allowed,start):
    """A finite prefix ending at cycle[0], and a nonempty closed cycle."""
    allowed=set(allowed);edges=model['transitions'];choices=[]
    for anchor in sorted(allowed):
        prefix=shortest_path(model,start,{anchor},allowed)
        if prefix is None:continue
        for successor in sorted(set(edges[anchor])&allowed):
            back=shortest_path(model,successor,{anchor},allowed)
            if back is not None:
                cycle=[anchor]+back
                choices.append((len(prefix)+len(cycle),prefix,cycle))
    if not choices:return None
    _,prefix,cycle=min(choices)
    return {'prefix':prefix,'cycle':cycle}


def verify_path(model,path):
    return bool(path) and all(s in model['transitions'] for s in path) and all(b in model['transitions'][a] for a,b in zip(path,path[1:]))


def evidence(model,property_id,holds):
    initial=model['initial'];reach=reachable(model);states=set(model['transitions'])
    if property_id=='p06_error_reachable':
        if holds:
            return {'kind':'existential_witness','path':shortest_path(model,initial,sat(model,'error'))}
        return {'kind':'absence_certificate','reachable':sorted(reach),
                'error_states':sorted(sat(model,'error')),'satisfaction_EF_error':sorted(sat(model,('EF','error'))),
                'closed_under_successors':all(set(model['transitions'][s])<=reach for s in reach),
                'explanation':'Reachable closure contains no error; initial is not in EF(error). A single failed path would not suffice.'}
    if holds:return {'kind':'satisfaction_set_proof','initial_in_satisfaction_set':True}
    if property_id in ('p01_no_error','p02_no_overlap'):
        bad=sat(model,'error') if property_id=='p01_no_error' else sat(model,('and','req','ack'))
        return {'kind':'finite_counterexample','path':shortest_path(model,initial,bad)}
    if property_id=='p03_ack_to_idle':
        candidates=[]
        for s in sorted(reach&sat(model,'ack')):
            prefix=shortest_path(model,initial,{s})
            for t in model['transitions'][s]:
                if t not in sat(model,'idle'):candidates.append(prefix+[t])
        return {'kind':'finite_counterexample','path':min(candidates,key=lambda x:(len(x),x))}
    allowed=states-sat(model,'ack');candidates=[]
    if property_id=='p04_response':
        for request in sorted(reach&sat(model,'req')&allowed):
            suffix=lasso(model,allowed,request)
            if suffix:
                prefix=shortest_path(model,initial,{request})+suffix['prefix'][1:]
                candidates.append({'kind':'lasso_counterexample','prefix':prefix,'cycle':suffix['cycle'],
                                   'unanswered_request_at':len(shortest_path(model,initial,{request}))-1})
    elif property_id=='p05_recurring_ack':
        for anchor in sorted(reach&allowed):
            suffix=lasso(model,allowed,anchor)
            if suffix:
                prefix=shortest_path(model,initial,{anchor})+suffix['prefix'][1:]
                candidates.append({'kind':'lasso_counterexample','prefix':prefix,'cycle':suffix['cycle']})
    else:raise ModelError('no witness generator for this property')
    if not candidates:raise ModelError('false liveness formula without a cycle witness')
    return min(candidates,key=lambda x:(len(x['prefix'])+len(x['cycle']),x['prefix'],x['cycle']))


def check(model,properties):
    validate(model);results=[]
    for prop in properties:
        truth=sat(model,prop['ctl']);holds=model['initial'] in truth
        results.append({**{k:v for k,v in prop.items() if k!='ctl'},'holds':holds,
                        'satisfaction_set':sorted(truth),'evidence':evidence(model,prop['id'],holds)})
    ack=sat(model,'ack');error=sat(model,'error')
    ef_ack,ef_steps=fixed_point(ack,lambda z:ack|ex(model,z))
    af_ack,af_steps=fixed_point(ack,lambda z:ack|ax(model,z))
    ef_error,err_steps=fixed_point(error,lambda z:error|ex(model,z))
    return {'engine':'python_explicit_exact_for_supported_templates','model':model['name'],
            'states_total':len(model['transitions']),'states_reachable':sorted(reachable(model)),
            'fairness':[], 'results':results,
            'iterations':{'EF_ack':ef_steps,'AF_ack':af_steps,'EF_error':err_steps},
            'sets':{'EF_ack':sorted(ef_ack),'AF_ack':sorted(af_ack),'EF_error':sorted(ef_error),
                    'AG_not_error':sorted(set(model['transitions'])-ef_error)},
            'tool_execution':'This report is NOT a NuSMV log'}


def dot(model):
    validate(model);lines=['digraph Model {','  rankdir=LR;','  start [shape=point];',f'  start -> {json.dumps(model["initial"])};']
    reach=reachable(model)
    for s in sorted(model['transitions']):
        label=s+': '+', '.join(model['labels'][s])
        lines.append(f'  {json.dumps(s)} [label={json.dumps(label)},style={"solid" if s in reach else "dashed"}];')
        for t in model['transitions'][s]:lines.append(f'  {json.dumps(s)} -> {json.dumps(t)};')
    return '\n'.join(lines+['}'])+'\n'
