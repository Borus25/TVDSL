"""Explicitly constructed typed AST fixtures plus matching Funny source.
These are test inputs, not claimed outputs of a frontend run.
"""

def node(kind,**fields):return {'node':kind,**fields,'pos':'1:1'}
def integer(v):return node('Int',value=v,type='int')
def boolean(v):return node('Bool',value=v,type='bool')
def ident(n,t='int'):return node('Ident',name=n,type=t)
def binop(op,a,b):return node('BinaryOp',op=op,left=a,right=b,type='bool' if op in ('<','>','<=','>=','==','!=','and','or') else 'int')
def un(op,a):return node('UnaryOp',op=op,operand=a,type='bool' if op=='not' else 'int')
def call(n,args,t='int'):return node('Call',name=n,args=args,type=t)
def index(a,i,t='int'):return node('ArrayIndex',base=a,index=i,type=t)
def block(*stmts):return node('Block',stmts=list(stmts))
def assign(n,value,t='int'):return node('Assign',target=ident(n,t) if isinstance(n,str) else n,value=value)
def var(n,value=None,t='int',annotation=True):return node('VarDecl',name=n,value=value,annotation=t if annotation else None,type=t)
def branch(cond,yes,no=None):return node('If',cond=cond,then=block(*yes),**{'else':block(*no) if no is not None else None})
def loop(cond,body,invariant=None):return node('While',cond=cond,body=block(*body),invariant=invariant)
def fn(name,params,stmts,result='int',requires=None,ensures=None):
    return node('Function',name=name,params=[p[0] for p in params],param_types=[p[1] for p in params],
                returns='r',return_type=result,requires=requires,ensures=ensures,body=block(*stmts),
                type='func('+','.join(p[1] for p in params)+')->'+result)
def program(*functions):return node('Program',functions=list(functions))


def cases():
    I=integer;B=boolean;X=ident;O=binop;A=assign
    items=[]
    def add(name,ast,tests):items.append({'name':name,'ast':ast,'tests':tests})
    def test(args,value=None,error=None,function='f'):
        return {'function':function,'args':args,**({'error':error} if error else {'expected':value})}
    add('constants',program(fn('f',[('x','int')],[var('a',O('*',I(2),I(3))),var('b',O('*',X('a'),I(1))),A('r',O('+',O('+',X('x'),X('a')),X('b')))])),[test([x],x+12) for x in [-7,0,1,100]])
    add('branch',program(fn('f',[('x','int')],[branch(O('>',X('x'),I(0)),[A('r',X('x'))],[A('r',un('-',X('x')))])])),[test([-3],3),test([0],0),test([7],7)])
    add('loop_sum',program(fn('f',[('n','int')],[var('i',I(0)),var('s',I(0)),loop(O('<',X('i'),X('n')),[A('s',O('+',X('s'),X('i'))),A('i',O('+',X('i'),I(1)))],O('>=',X('i'),I(0))),A('r',X('s'))])),[test([0],0),test([1],0),test([5],10),test([10],45)])
    add('recursion',program(fn('f',[('n','int')],[branch(O('<=',X('n'),I(1)),[A('r',I(1))],[A('r',O('*',X('n'),call('f',[O('-',X('n'),I(1))])))])])),[test([0],1),test([1],1),test([5],120),test([7],5040)])
    add('forward_call',program(fn('f',[('x','int')],[A('r',call('g',[X('x')]))]),fn('g',[('x','int')],[A('r',O('+',X('x'),I(2)))])),[test([0],2),test([-3],-1)])
    even=fn('even',[('n','int')],[branch(O('==',X('n'),I(0)),[A('r',B(True),'bool')],[A('r',call('odd',[O('-',X('n'),I(1))],'bool'),'bool')])],result='bool')
    odd=fn('odd',[('n','int')],[branch(O('==',X('n'),I(0)),[A('r',B(False),'bool')],[A('r',call('even',[O('-',X('n'),I(1))],'bool'),'bool')])],result='bool')
    add('mutual_recursion',program(even,odd),[test([n],n%2==0,function='even') for n in range(7)])
    add('shadowing',program(fn('f',[('x','int')],[var('y',X('x')),block(var('x',B(True),'bool'),node('Assert',expr=X('x','bool')),A('y',O('+',X('y'),I(1)))),A('r',O('+',X('y'),X('x')))])),[test([2],5),test([-1],-1)])
    add('initializer_shadow',program(fn('f',[],[var('x',I(1)),block(var('x',O('+',X('x'),I(1))),A('r',X('x')))])),[test([],2)])
    add('deferred',program(fn('f',[],[var('x',None,annotation=False),A('x',I(4)),A('r',X('x'))])),[test([],4)])
    add('redefinition',program(fn('f',[('x','int')],[var('a',I(1)),A('a',O('+',X('x'),I(2))),A('r',O('+',X('a'),I(1)))])),[test([4],7),test([-3],0)])
    add('cse',program(fn('f',[('x','int'),('y','int')],[var('a',O('+',X('x'),X('y'))),var('b',O('+',X('x'),X('y'))),A('r',O('*',X('a'),X('b')))])),[test([2,3],25),test([-2,3],1)])
    add('cse_kill',program(fn('f',[('x','int')],[var('a',O('+',X('x'),I(1))),A('x',O('+',X('x'),I(2))),var('b',O('+',X('x'),I(1))),A('r',O('+',X('a'),X('b')))])),[test([3],10),test([0],4)])
    add('identities',program(fn('f',[('x','int')],[var('a',O('+',X('x'),I(0))),var('b',O('*',I(1),X('a'))),var('c',O('-',X('b'),I(0))),A('r',O('/',X('c'),I(1)))])),[test([-5],-5),test([3],3)])
    add('array_read',program(fn('f',[('a','array<int>')],[A('r',O('+',index(X('a','array<int>'),I(0)),call('length',[X('a','array<int>')])))])),[test([[4,5]],6),test([[]],error='IndexError')])
    add('array_store',program(fn('f',[('a','array<int>')],[var('b',X('a','array<int>'),'array<int>'),A(index(X('a','array<int>'),I(0)),I(99)),A('r',O('+',index(X('a','array<int>'),I(0)),index(X('b','array<int>'),I(0))))])),[test([[1,2]],100),test([[]],error='IndexError')])
    add('nested_array_store',program(fn('f',[('a','array<array<int>>')],[A(index(index(X('a','array<array<int>>'),I(0),'array<int>'),I(1)),I(9)),A('r',index(index(X('a','array<array<int>>'),I(0),'array<int>'),I(1)))])),[test([[[1,2],[3,4]]],9)])
    add('store_call',program(fn('f',[('a','array<int>')],[A('r',call('store',[X('a','array<int>'),I(0),I(7)],'array<int>'),'array<int>')],result='array<int>')),[test([[1,2]],[7,2])])
    add('negative_index',program(fn('f',[('a','array<int>')],[A('r',index(X('a','array<int>'),un('-',I(1))))])),[test([[1]],error='IndexError')])
    add('division',program(fn('f',[('x','int')],[A('r',O('/',X('x'),I(2)))])),[test([-5],-2),test([5],2),test([10**50],10**50//2)])
    add('dead_division',program(fn('f',[],[var('dead',O('/',I(1),I(0))),A('r',I(0))])),[test([],error='ZeroDivisionError')])
    add('dead_load',program(fn('f',[('a','array<int>')],[var('dead',index(X('a','array<int>'),I(9))),A('r',I(0))])),[test([[1]],error='IndexError')])
    danger=O('>',O('/',I(1),I(0)),I(0))
    add('short_and',program(fn('f',[],[A('r',O('and',B(False),danger),'bool')],result='bool')),[test([],False)])
    add('short_or',program(fn('f',[],[A('r',O('or',B(True),danger),'bool')],result='bool')),[test([],True)])
    add('short_rhs_executed',program(fn('f',[],[A('r',O('and',B(True),danger),'bool')],result='bool')),[test([],error='ZeroDivisionError')])
    add('checks',program(fn('f',[('x','int')],[node('Assert',expr=O('>=',X('x'),I(0))),node('Assume',expr=O('<',X('x'),I(10))),A('r',X('x'))])),[test([2],2),test([-1],error='AssertionError'),test([11],error='AssumptionFailed')])
    add('contracts',program(fn('f',[('x','int')],[A('r',O('+',X('x'),I(1)))],requires=O('>',X('x'),I(0)),ensures=O('>',X('r'),X('x')))),[test([1],2),test([0],error='AssumptionFailed')])
    add('invariant_failure',program(fn('f',[],[A('r',I(0)),loop(B(False),[],B(False))])),[test([],error='AssertionError')])
    add('function_alias',program(fn('g',[('x','int')],[A('r',O('+',X('x'),I(2)))]),fn('f',[('x','int')],[var('h',X('g','func(int)->int'),'func(int)->int',False),A('r',call('h',[X('x')]))])),[test([3],5)])
    add('dead_call',program(fn('g',[],[node('Assert',expr=B(False)),A('r',I(0))]),fn('f',[],[var('unused',call('g',[])),A('r',I(1))])),[test([],error='AssertionError')])
    add('branch_live_out',program(fn('f',[('b','bool')],[var('x',I(0)),branch(X('b','bool'),[A('x',I(4))],[A('x',I(6))]),A('r',X('x'))])),[test([True],4),test([False],6)])
    add('loop_live_out',program(fn('f',[('n','int')],[var('i',I(0)),loop(O('<',X('i'),X('n')),[A('i',O('+',X('i'),I(1)))]),A('r',X('i'))])),[test([5],5),test([-1],0)])
    add('nested_short_circuit',program(fn('f',[('a','bool'),('b','bool')],[A('r',O('or',O('and',X('a','bool'),X('b','bool')),un('not',X('a','bool'))),'bool')],result='bool')),[test([a,b],(a and b) or not a) for a in [False,True] for b in [False,True]])
    add('array_bool',program(fn('f',[('a','array<bool>')],[A('r',index(X('a','array<bool>'),I(0),'bool'),'bool')],result='bool')),[test([[True]],True),test([[False]],False)])
    add('array_equality',program(fn('f',[('a','array<int>'),('b','array<int>')],[A('r',O('==',X('a','array<int>'),X('b','array<int>')),'bool')],result='bool')),[test([[1],[1]],True),test([[1],[2]],False)])
    add('dead_code',program(fn('f',[('x','int')],[var('unused',O('*',X('x'),I(5))),var('unused2',un('-',X('x'))),A('r',I(7))])),[test([5],7)])
    return items


def source_expr(n):
    k=n['node']
    if k=='Int':return str(n['value']) if n['value']>=0 else '('+str(n['value'])+')'
    if k=='Bool':return 'true' if n['value'] else 'false'
    if k=='Ident':return n['name']
    if k=='BinaryOp':return '('+source_expr(n['left'])+' '+n['op']+' '+source_expr(n['right'])+')'
    if k=='UnaryOp':return '('+n['op']+' '+source_expr(n['operand'])+')'
    if k=='Call':return n['name']+'('+', '.join(source_expr(a) for a in n['args'])+')'
    if k=='ArrayIndex':return source_expr(n['base'])+'['+source_expr(n['index'])+']'
    raise ValueError(k)


def source_stmt(n,depth=1):
    p='  '*depth;k=n['node']
    if k=='Block':return p+'{\n'+''.join(source_stmt(s,depth+1) for s in n['stmts'])+p+'}\n'
    if k=='VarDecl':return p+'var '+n['name']+(':'+n['annotation'] if n.get('annotation') else '')+(' = '+source_expr(n['value']) if n.get('value') is not None else '')+';\n'
    if k=='Assign':return p+source_expr(n['target'])+' = '+source_expr(n['value'])+';\n'
    if k=='If':return p+'if ('+source_expr(n['cond'])+') '+source_stmt(n['then'],depth).lstrip()+(p+'else '+source_stmt(n['else'],depth).lstrip() if n.get('else') else '')
    if k=='While':return p+'while ('+source_expr(n['cond'])+') '+('invariant '+source_expr(n['invariant'])+' ' if n.get('invariant') else '')+source_stmt(n['body'],depth).lstrip()
    if k in ('Assert','Assume'):return p+k.lower()+' '+source_expr(n['expr'])+';\n'
    raise ValueError(k)


def source(program):
    output=[]
    for f in program['functions']:
        header='function '+f['name']+'('+', '.join(n+':'+t for n,t in zip(f['params'],f['param_types']))+') returns r:'+f['return_type']+'\n'
        for k in ('requires','ensures'):
            if f.get(k) is not None:header+='  '+k+' '+source_expr(f[k])+'\n'
        output.append(header+source_stmt(f['body'],0))
    return '\n'.join(output)
