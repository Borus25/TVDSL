"""Extracted unchanged cfg() from TVDSL HW04/ir.py.
Source blob: daa0105178dd8c6998860a86d3576d3261e4a045.
Only dependency shims below are added; the algorithm itself is unchanged.
"""
class CompileError(ValueError):
    pass

TERMINATORS={'branch','jump','return'}


def cfg(fn):
    code=fn['code']
    if not code: return []
    labels={i['label']:p for p,i in enumerate(code) if i['op']=='label'}
    leaders={0}
    for p,i in enumerate(code):
        if i['op']=='label':leaders.add(p)
        if i['op'] in TERMINATORS:
            if p+1<len(code):leaders.add(p+1)
            targets=i.get('targets', [i['target']] if 'target' in i else [])
            for target in targets:
                if target not in labels:raise CompileError(f'unknown label {target}')
                leaders.add(labels[target])
    starts=sorted(leaders); blocks=[]; owner={}
    for b,start in enumerate(starts):
        end=starts[b+1] if b+1<len(starts) else len(code)
        blocks.append({'id':b,'start':start,'end':end,'successors':[]})
        for p in range(start,end):owner[p]=b
    for b,block in enumerate(blocks):
        ins=code[block['end']-1]
        if ins['op']=='branch':succ=[owner[labels[t]] for t in ins['targets']]
        elif ins['op']=='jump':succ=[owner[labels[ins['target']]]]
        elif ins['op']=='return':succ=[]
        else:succ=[b+1] if b+1<len(blocks) else []
        block['successors']=sorted(set(succ))
    reachable=set(); pending=[0]
    while pending:
        b=pending.pop()
        if b in reachable:continue
        reachable.add(b);pending.extend(blocks[b]['successors'])
    for block in blocks:block['reachable']=block['id'] in reachable
    return blocks
