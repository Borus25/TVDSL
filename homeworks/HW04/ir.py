"""Funny HW4: typed JSON AST -> TAC -> CFG -> local opts -> allocation.
Standard library only. IR operands are explicit const/var/func objects.
"""
from __future__ import annotations
import copy
import itertools
import json
from dataclasses import dataclass, asdict


class CompileError(ValueError):
    pass


def V(name): return {'var': name}
def C(value): return {'const': value}
def F(name): return {'func': name}
def isvar(x): return isinstance(x, dict) and 'var' in x

def operand_text(x):
    if 'var' in x: return x['var']
    if 'func' in x: return '&' + x['func']
    return json.dumps(x['const'], ensure_ascii=False)


def binary(op, a, b):
    if op == '+': return a + b
    if op == '-': return a - b
    if op == '*': return a * b
    if op == '/':
        if b == 0: raise ZeroDivisionError('integer division by zero')
        return (abs(a) // abs(b)) * (-1 if (a < 0) != (b < 0) else 1)
    if op == '==': return a == b
    if op == '!=': return a != b
    if op == '<': return a < b
    if op == '<=': return a <= b
    if op == '>': return a > b
    if op == '>=': return a >= b
    raise CompileError(f'unknown binary operator {op}')


def unary(op, a):
    if op == '-': return -a
    if op == 'not': return not a
    raise CompileError(f'unknown unary operator {op}')


class Generator:
    def __init__(self):
        self.functions = set()
        self.label_counter = 0

    def new_label(self):
        self.label_counter += 1
        return f'L{self.label_counter}'

    def emit(self, op, dst=None, args=None, **fields):
        ins = {'op': op, **fields}
        if dst is not None: ins['dst'] = dst
        if args is not None: ins['args'] = args
        self.code.append(ins)
        return V(dst) if dst is not None else None

    def temp(self, typ):
        self.temps += 1
        name = f't{self.temps}'
        self.types[name] = typ
        return name

    def declare(self, name, typ):
        if typ is None or typ == '<error>':
            raise CompileError(f'missing/invalid type for {name}')
        self.locals += 1
        unique = f'v{self.locals}_{name}'
        if name in self.scopes[-1]: raise CompileError(f'duplicate local {name}')
        self.scopes[-1][name] = unique
        self.types[unique] = typ
        return unique

    def resolve(self, name):
        for scope in reversed(self.scopes):
            if name in scope: return V(scope[name])
        if name in self.functions or name in ('length', 'store'): return F(name)
        raise CompileError(f'unresolved name {name}')

    def build(self, payload):
        ast = payload
        if 'ast' in payload:
            if payload.get('ok') is False or payload.get('diagnostics'):
                raise CompileError('HW3 reported errors: IR generation refused')
            ast = payload['ast']
        if not ast or ast.get('node') != 'Program': raise CompileError('expected typed Program AST')
        # Reject poisoned nodes even if a caller forged ok=true.
        def validate(n):
            if isinstance(n, list):
                for x in n: validate(x)
            if isinstance(n, dict):
                if n.get('node') in ('Ident','Int','Bool','ArrayIndex','Call','UnaryOp','BinaryOp'):
                    if not n.get('type') or n['type'] == '<error>':
                        raise CompileError(f"untyped/invalid {n.get('node')} at {n.get('pos')}")
                for x in n.values(): validate(x)
        validate(ast)
        self.functions = {f['name'] for f in ast['functions']}
        if len(self.functions) != len(ast['functions']): raise CompileError('duplicate function')
        return {'format': 'funny-ir/1', 'functions': [self.function(f) for f in ast['functions']]}

    def function(self, fn):
        self.code, self.types, self.scopes = [], {}, [{}]
        self.temps = self.locals = 0
        if len(fn.get('param_types', [])) != len(fn['params']): raise CompileError('missing parameter types')
        params = [self.declare(n, t) for n,t in zip(fn['params'], fn['param_types'])]
        result = self.declare(fn['returns'], fn.get('return_type'))
        if fn.get('requires') is not None:
            self.emit('assume', args=[self.expr(fn['requires'])], message='requires')
        self.block(fn['body'], scoped=False)
        if fn.get('ensures') is not None:
            self.emit('assert', args=[self.expr(fn['ensures'])], message='ensures')
        self.emit('return', args=[V(result)])
        return {'name': fn['name'], 'params': params, 'param_types': fn['param_types'],
                'return_type': fn['return_type'], 'types': self.types, 'code': self.code}

    def expr(self, n):
        kind, typ = n['node'], n.get('type')
        if kind in ('Int', 'Bool'): return C(n['value'])
        if kind == 'Ident': return self.resolve(n['name'])
        if kind == 'BinaryOp' and n['op'] in ('and','or'):
            # Real short circuit: unused RHS must not trap or call a function.
            dst = self.temp('bool')
            lhs = self.expr(n['left'])
            rhs_label, skip_label, done = self.new_label(), self.new_label(), self.new_label()
            targets = (rhs_label,skip_label) if n['op']=='and' else (skip_label,rhs_label)
            self.emit('branch', args=[lhs], targets=list(targets))
            self.emit('label', label=skip_label)
            self.emit('copy', dst, [C(n['op']=='or')])
            self.emit('jump', target=done)
            self.emit('label', label=rhs_label)
            rhs = self.expr(n['right'])
            self.emit('copy', dst, [rhs])
            self.emit('jump', target=done)
            self.emit('label', label=done)
            return V(dst)
        if kind == 'BinaryOp':
            a = self.expr(n['left']); b = self.expr(n['right'])
            return self.emit('bin', self.temp(typ), [a,b], operator=n['op'])
        if kind == 'UnaryOp':
            a = self.expr(n['operand'])
            return self.emit('un', self.temp(typ), [a], operator=n['op'])
        if kind == 'ArrayIndex':
            a = self.expr(n['base']); i = self.expr(n['index'])
            return self.emit('load', self.temp(typ), [a,i])
        if kind == 'Call':
            callee = self.resolve(n['name'])
            args = [self.expr(a) for a in n['args']]
            return self.emit('call', self.temp(typ), [callee, *args])
        raise CompileError(f'unsupported expression {kind}')

    def block(self, n, scoped=True):
        if scoped: self.scopes.append({})
        for stmt in n['stmts']: self.statement(stmt)
        if scoped: self.scopes.pop()

    def statement(self,n):
        kind=n['node']
        if kind=='Block': self.block(n)
        elif kind=='VarDecl':
            value = self.expr(n['value']) if n.get('value') is not None else None
            dst=self.declare(n['name'], n.get('type') or n.get('annotation'))
            if value is not None: self.emit('copy',dst,[value])
        elif kind=='Assign':
            value=self.expr(n['value'])
            target=n['target']
            if target['node']=='Ident':
                dst=self.resolve(target['name'])
                if not isvar(dst): raise CompileError('assignment to function')
                self.emit('copy',dst['var'],[value])
            else:
                # Functional arrays: a[i][j]=v -> a=store(a,i,store(a[i],j,v)).
                chain=[]
                while target['node']=='ArrayIndex':
                    chain.append(target); target=target['base']
                base=self.resolve(target['name']); current=base; parents=[]
                for level, item in enumerate(reversed(chain)):
                    index=self.expr(item['index']); parents.append((current,index,item['base']['type']))
                    if level<len(chain)-1:
                        current=self.emit('load',self.temp(item['type']),[current,index])
                for arr,index,typ in reversed(parents):
                    value=self.emit('call',self.temp(typ),[F('store'),arr,index,value])
                self.emit('copy',base['var'],[value])
        elif kind=='If':
            cond=self.expr(n['cond']); yes,no,end=self.new_label(),self.new_label(),self.new_label()
            self.emit('branch',args=[cond],targets=[yes,no])
            self.emit('label',label=yes);self.block(n['then']);self.emit('jump',target=end)
            self.emit('label',label=no)
            if n.get('else') is not None:self.block(n['else'])
            self.emit('jump',target=end);self.emit('label',label=end)
        elif kind=='While':
            head,body,end=self.new_label(),self.new_label(),self.new_label()
            self.emit('label',label=head)
            if n.get('invariant') is not None:self.emit('assert',args=[self.expr(n['invariant'])],message='invariant')
            cond=self.expr(n['cond']);self.emit('branch',args=[cond],targets=[body,end])
            self.emit('label',label=body);self.block(n['body']);self.emit('jump',target=head)
            self.emit('label',label=end)
        elif kind in ('Assert','Assume'):
            self.emit(kind.lower(),args=[self.expr(n['expr'])],message=kind.lower())
        else: raise CompileError(f'unsupported statement {kind}')


def uses(ins): return {a['var'] for a in ins.get('args',[]) if isvar(a)}
def defs(ins): return {ins['dst']} if 'dst' in ins else set()
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


def liveness(fn):
    blocks=cfg(fn); code=fn['code']; ins_in={};ins_out={}
    buse=[];bdef=[]
    for b in blocks:
        used=set();defined=set()
        for i in code[b['start']:b['end']]:
            used |= uses(i)-defined; defined |= defs(i)
        buse.append(used);bdef.append(defined)
    live_in=[set() for _ in blocks]; live_out=[set() for _ in blocks]
    changed=True
    while changed:
        changed=False
        for b in reversed(blocks):
            k=b['id'];out=set().union(*(live_in[s] for s in b['successors']))
            inn=buse[k] | (out-bdef[k])
            if out!=live_out[k] or inn!=live_in[k]:changed=True
            live_in[k],live_out[k]=inn,out
    for b in blocks:
        k=b['id'];live=set(live_out[k])
        b['live_in']=sorted(live_in[k]);b['live_out']=sorted(live_out[k])
        for p in reversed(range(b['start'],b['end'])):
            ins_out[p]=set(live);live=uses(code[p])|(live-defs(code[p]));ins_in[p]=set(live)
    return blocks,ins_in,ins_out


def allocation(fn, registers=None):
    blocks,inn,out=liveness(fn)
    names=set(fn['params'])
    for i in fn['code']:names |= uses(i)|defs(i)
    graph={n:set() for n in names}
    def edge(a,b):
        if a!=b:graph[a].add(b);graph[b].add(a)
    for p,i in enumerate(fn['code']):
        # Cliques include simultaneous source operands, not only def/live-out.
        for live in (inn[p],out[p]):
            for a,b in itertools.combinations(sorted(live),2):edge(a,b)
        for a in defs(i):
            for b in out[p]:edge(a,b)
    colors={}
    for name in sorted(graph,key=lambda n:(-len(graph[n]),n)):
        unavailable={colors[n] for n in graph[name] if n in colors}
        color=0
        while color in unavailable:color+=1
        colors[name]=color
    count=1+max(colors.values(),default=-1)
    return {'blocks':blocks,'instruction_live_in':{str(k):sorted(v) for k,v in inn.items()},
            'instruction_live_out':{str(k):sorted(v) for k,v in out.items()},
            'graph':{n:sorted(graph[n]) for n in sorted(graph)},'colors':colors,'color_count':count,
            'spills':sorted(n for n,c in colors.items() if registers is not None and c>=registers),
            'temp_colors':{n:c for n,c in colors.items() if n.startswith('t')}}


def removable(i):
    # Never erase potentially trapping division, indexing, calls or checks.
    return i['op'] in ('copy','un') or (i['op']=='bin' and i['operator']!='/')


def optimize(fn, passes):
    allowed={'const','algebraic','dce','cse'}
    if set(passes)-allowed:raise CompileError(f'unknown passes: {set(passes)-allowed}')
    result=copy.deepcopy(fn)
    # Iterate local passes and liveness-backed DCE until a fixed point.
    while True:
        before=json.dumps(result['code'],sort_keys=True)
        code=[]
        for block in cfg(result):
            constants={};common={}
            for original in result['code'][block['start']:block['end']]:
                i=copy.deepcopy(original)
                if 'const' in passes:
                    i['args']=[copy.deepcopy(constants.get(a['var'],a)) if isvar(a) else a for a in i.get('args',[])] if 'args' in i else i.get('args',[])
                    if not i['args']:i.pop('args',None)
                if 'const' in passes and i['op'] in ('bin','un') and all('const' in a for a in i['args']):
                    try:
                        values=[a['const'] for a in i['args']]
                        value=binary(i['operator'],*values) if i['op']=='bin' else unary(i['operator'],*values)
                        i={'op':'copy','dst':i['dst'],'args':[C(value)]}
                    except (ZeroDivisionError,TypeError,ValueError):pass
                if 'algebraic' in passes and i['op']=='bin':
                    a,b=i['args'];op=i['operator'];replacement=None
                    def eq(x,v):return 'const' in x and type(x['const']) is int and x['const']==v
                    if op=='+' and eq(b,0):replacement=a
                    elif op=='+' and eq(a,0):replacement=b
                    elif op=='-' and eq(b,0):replacement=a
                    elif op=='*' and eq(b,1):replacement=a
                    elif op=='*' and eq(a,1):replacement=b
                    elif op=='*' and (eq(a,0) or eq(b,0)):replacement=C(0)
                    elif op=='/' and eq(b,1):replacement=a
                    if replacement is not None:i={'op':'copy','dst':i['dst'],'args':[replacement]}
                dst=i.get('dst')
                if dst is not None:
                    constants.pop(dst,None)
                    common={k:v for k,v in common.items() if v!=dst and ('var',dst) not in k[2]}
                if i['op']=='call':common.clear()
                if 'cse' in passes and i['op'] in ('bin','un'):
                    args=tuple(tuple(a.items())[0] for a in i['args'])
                    key=(i['op'],i['operator'],args)
                    if key in common:i={'op':'copy','dst':dst,'args':[V(common[key])]}
                    elif not any(isvar(a) and a['var']==dst for a in i['args']):common[key]=dst
                if 'const' in passes and i['op']=='copy' and 'const' in i['args'][0]:constants[dst]=i['args'][0]
                code.append(i)
        result['code']=code
        if 'dce' in passes:
            _,_,out=liveness(result)
            result['code']=[i for p,i in enumerate(result['code']) if not (i.get('dst') is not None and i['dst'] not in out[p] and removable(i))]
        if json.dumps(result['code'],sort_keys=True)==before:break
    return result


def instruction_text(i):
    op=i['op'];args=[operand_text(a) for a in i.get('args',[])];dst=i.get('dst','')
    if op=='label':return i['label']+':'
    if op=='copy':return f'{dst} = {args[0]}'
    if op=='bin':return f'{dst} = {args[0]} {i["operator"]} {args[1]}'
    if op=='un':return f'{dst} = {i["operator"]} {args[0]}'
    if op=='jump':return 'goto '+i['target']
    if op=='branch':return f'if {args[0]} goto {i["targets"][0]} else {i["targets"][1]}'
    if op=='load':return f'{dst} = load {args[0]}, {args[1]}'
    if op=='call':return f'{dst} = call {args[0]}({", ".join(args[1:])})'
    return op+' '+', '.join(args)


def dump(program):
    lines=[]
    for fn in program['functions']:
        lines.append(f'function {fn["name"]}({", ".join(fn["params"])}) -> {fn["return_type"]}:')
        lines.extend('  '+instruction_text(i) for i in fn['code']);lines.append('')
    return '\n'.join(lines)


def metrics(fn, registers=None):
    allocation_result=allocation(fn,registers)
    return {'instructions':sum(i['op']!='label' for i in fn['code']),
            'labels':sum(i['op']=='label' for i in fn['code']),
            'temporaries':len({n for i in fn['code'] for n in uses(i)|defs(i) if n.startswith('t')}),
            'blocks':len(allocation_result['blocks']),'colors':allocation_result['color_count'],
            'spill_candidates':len(allocation_result['spills'])}


def cfg_dot(fn):
    lines=['digraph CFG {','  node [shape=box];']
    for b in cfg(fn):
        label=f'B{b["id"]}'+chr(10)+chr(10).join(instruction_text(i) for i in fn['code'][b['start']:b['end']])
        lines.append(f'  B{b["id"]} [label={json.dumps(label)}];')
        for s in b['successors']:lines.append(f'  B{b["id"]} -> B{s};')
    return '\n'.join(lines+['}'])


def graph_dot(alloc):
    lines=['graph Interference {']
    for n,neighbors in alloc['graph'].items():
        lines.append(f'  {json.dumps(n)} [label={json.dumps(n+" / c"+str(alloc["colors"][n]))}];')
        for m in neighbors:
            if n<m:lines.append(f'  {json.dumps(n)} -- {json.dumps(m)};')
    return '\n'.join(lines+['}'])


class VMError(RuntimeError):pass
class AssumptionFailed(VMError):pass


class Interpreter:
    def __init__(self,program,step_limit=100000):
        self.functions={fn['name']:fn for fn in program['functions']}
        self.limit=step_limit;self.steps=0

    def run(self, name, arguments):
        self.steps=0
        try:return self._call(name,copy.deepcopy(arguments),0)
        except RecursionError as exc:raise VMError('recursion limit exceeded') from exc

    def _call(self,name,arguments,depth):
        if depth>200:raise VMError('recursion limit exceeded')
        if name=='length':
            if len(arguments)!=1:raise VMError('length arity')
            return len(arguments[0])
        if name=='store':
            if len(arguments)!=3:raise VMError('store arity')
            arr,index,value=arguments
            if type(index) is not int or not 0<=index<len(arr):raise IndexError('array index out of bounds')
            result=list(arr);result[index]=value;return result
        if name not in self.functions:raise VMError(f'unknown function {name}')
        fn=self.functions[name]
        if len(arguments)!=len(fn['params']):raise VMError('argument count mismatch')
        def compatible(value,typ):
            if typ=='int':return type(value) is int
            if typ=='bool':return type(value) is bool
            if typ.startswith('array<') and typ.endswith('>'):
                return isinstance(value,list) and all(compatible(v,typ[6:-1]) for v in value)
            if typ.startswith('func('):return isinstance(value,tuple) and value[0]=='function'
            return False
        for i,(value,typ) in enumerate(zip(arguments,fn.get('param_types',[])),1):
            if not compatible(value,typ):raise VMError(f'argument {i}: expected {typ}')
        env=dict(zip(fn['params'],arguments));code=fn['code'];labels={i['label']:p for p,i in enumerate(code) if i['op']=='label'}
        def get(a):
            if 'const' in a:return a['const']
            if 'func' in a:return ('function',a['func'])
            if a['var'] not in env:raise VMError('uninitialized '+a['var'])
            return env[a['var']]
        pc=0
        while pc<len(code):
            self.steps+=1
            if self.steps>self.limit:raise VMError('step limit exceeded')
            i=code[pc];op=i['op'];args=[get(a) for a in i.get('args',[])];pc+=1
            if op=='label':continue
            if op=='copy':env[i['dst']]=args[0]
            elif op=='bin':env[i['dst']]=binary(i['operator'],*args)
            elif op=='un':env[i['dst']]=unary(i['operator'],*args)
            elif op=='load':
                a,index=args
                if type(index) is not int or not 0<=index<len(a):raise IndexError('array index out of bounds')
                env[i['dst']]=a[index]
            elif op=='call':
                callee=args[0]
                if not isinstance(callee,tuple) or callee[0]!='function':raise VMError('not callable')
                env[i['dst']]=self._call(callee[1],args[1:],depth+1)
            elif op=='jump':pc=labels[i['target']]
            elif op=='branch':pc=labels[i['targets'][0 if args[0] else 1]]
            elif op=='return':return args[0]
            elif op in ('assert','assume'):
                if not args[0]:
                    if op=='assume':raise AssumptionFailed(i.get('message','assume'))
                    raise AssertionError(i.get('message','assert'))
            else:raise VMError(f'unknown opcode {op}')
        raise VMError('function fell off end')


def outcome(program,fn,args):
    try:return {'result':Interpreter(program).run(fn,args)}
    except (VMError,ZeroDivisionError,IndexError,AssertionError,TypeError) as exc:
        return {'error':type(exc).__name__,'message':str(exc)}
