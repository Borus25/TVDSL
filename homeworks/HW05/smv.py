"""Deterministic, auditable translation of finite labelled graphs to SMV."""
import re
from checker import validate


def identifier(text):
    if not isinstance(text,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',text):
        raise ValueError(f'unsafe SMV identifier {text!r}')
    return text


def render(model,properties):
    validate(model)
    states=sorted(model['transitions'])
    for s in states:identifier(s)
    atoms=sorted({a for labels in model['labels'].values() for a in labels}|{'idle','req','ack','error'})
    for a in atoms:identifier(a)
    if set(atoms)&set(states):raise ValueError('state and atomic proposition names overlap')
    lines=['-- Generated from an explicit graph; no FAIRNESS/INVAR constraints.',
           '-- Expected-false specifications are intentional diagnostic queries.',
           'MODULE main','VAR','  state : {'+', '.join(states)+'};',
           'ASSIGN',f'  init(state) := {model["initial"]};','  next(state) := case']
    for s in states:
        targets=sorted(set(model['transitions'][s]))
        target=targets[0] if len(targets)==1 else '{'+', '.join(targets)+'}'
        lines.append(f'    state = {s} : {target};')
    lines+=['    TRUE : state;','  esac;','DEFINE']
    for atom in atoms:
        truth=[f'(state = {s})' for s in states if atom in model['labels'][s]]
        lines.append('  '+atom+' := '+(' | '.join(truth) if truth else 'FALSE')+';')
    lines.append('')
    for prop in properties:
        identifier(prop['id'])
        keyword='CTLSPEC' if prop['logic']=='CTL' else 'LTLSPEC'
        lines.append(f'{keyword} NAME {prop["id"]} := {prop["formula"]};')
    return '\n'.join(lines)+'\n'
