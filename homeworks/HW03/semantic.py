"""HW3: scoped symbols, two-pass type checking, annotated HW2 AST."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import funny_ast as ast
from funny_types import BOOL, ERROR, INT, Type, UnificationError, func_type, parse_type, unify

Pos = Tuple[int, int]


@dataclass(frozen=True)
class SemanticDiagnostic:
    code: str
    message: str
    pos: Pos

    @property
    def line(self):
        return self.pos[0]

    @property
    def col(self):
        return self.pos[1]

    def __str__(self):
        return f'error: {self.message} at {self.line}:{self.col} [{self.code}]'

    def to_dict(self):
        return {'phase': 'semantic', 'code': self.code, 'message': self.message,
                'line': self.line, 'col': self.col}


@dataclass
class Symbol:
    name: str
    type: Optional[Type]
    kind: str
    pos: Pos
    initialized: bool = False
    declaration: Optional[ast.Node] = None


class SymbolTable:
    def __init__(self):
        self.scopes: List[Dict[str, Symbol]] = [{}]

    def enter_scope(self):
        self.scopes.append({})

    def exit_scope(self):
        if len(self.scopes) == 1:
            raise RuntimeError('cannot exit global scope')
        return self.scopes.pop()

    def lookup(self, name: str) -> Optional[Symbol]:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def declare(self, symbol: Symbol) -> Optional[Symbol]:
        previous = self.scopes[-1].get(symbol.name)
        if previous is None:
            self.scopes[-1][symbol.name] = symbol
        return previous

    def visible_symbols(self):
        return [symbol for scope in self.scopes for symbol in scope.values()]


@dataclass
class SemanticResult:
    program: ast.Program
    diagnostics: List[SemanticDiagnostic]

    @property
    def ok(self):
        return not self.diagnostics


class SemanticAnalyzer:
    def __init__(self):
        self.table = SymbolTable()
        self.diagnostics: List[SemanticDiagnostic] = []
        self.signatures: Dict[int, Type] = {}
        self.read_nodes = []

    def error(self, code: str, message: str, pos: Pos):
        self.diagnostics.append(SemanticDiagnostic(code, message, pos))

    def declare(self, symbol: Symbol):
        previous = self.table.declare(symbol)
        if previous is not None:
            self.error('E_REDECLARED',
                       f"redeclaration of '{symbol.name}' (first declared at {previous.pos[0]}:{previous.pos[1]})",
                       symbol.pos)
            return False
        return True

    def annotation(self, text: Optional[str], name: str, pos: Pos) -> Type:
        if text is None:
            self.error('E_MISSING_TYPE', f"explicit type annotation required for {name}", pos)
            return ERROR
        try:
            return parse_type(text)
        except ValueError:
            self.error('E_TYPE', f'unsupported type {text!r}', pos)
            return ERROR

    def check(self, program: ast.Program) -> SemanticResult:
        # Analyzer instances can safely be reused; all state belongs to a run.
        self.table = SymbolTable()
        self.diagnostics = []
        self.signatures = {}
        self.read_nodes = []
        for fn in program.functions:
            params = [self.annotation(fn.param_types[i] if i < len(fn.param_types) else None,
                                      f"parameter '{name}'",
                                      fn.param_positions[i] if i < len(fn.param_positions) else fn.pos)
                      for i, name in enumerate(fn.params)]
            result = self.annotation(fn.return_type, f"return '{fn.returns}'", fn.return_pos or fn.pos)
            signature = func_type(params, result)
            self.signatures[id(fn)] = signature
            fn.type = str(signature)
            if fn.name in ('length', 'store'):
                self.error('E_BUILTIN', f"cannot redefine builtin '{fn.name}'", fn.name_pos)
            else:
                self.declare(Symbol(fn.name, signature, 'func', fn.name_pos, True, fn))
        for fn in program.functions:
            self.function(fn)
        # Fill deferred declarations/assignment-target annotations after inference.
        for node, symbol in self.read_nodes:
            if symbol.type is not None and node.type is None:
                node.type = str(symbol.type)
        self.diagnostics.sort(key=lambda d: (d.line, d.col))
        return SemanticResult(program, self.diagnostics)

    def finish_scope(self):
        scope = self.table.exit_scope()
        for symbol in scope.values():
            if symbol.kind == 'var' and symbol.type is None:
                self.error('E_CANNOT_INFER', f"cannot infer type of '{symbol.name}': no valid assignment", symbol.pos)
                symbol.type = ERROR
                if symbol.declaration is not None:
                    symbol.declaration.type = str(ERROR)

    def function(self, fn: ast.Function):
        signature = self.signatures[id(fn)]
        self.table.enter_scope()
        for i, (name, typ) in enumerate(zip(fn.params, signature.args[:-1])):
            pos = fn.param_positions[i] if i < len(fn.param_positions) else fn.pos
            self.declare(Symbol(name, typ, 'param', pos, True))
        result = Symbol(fn.returns, signature.args[-1], 'result', fn.return_pos)
        inserted = self.declare(result)
        if fn.requires is not None:
            self.require(self.infer(fn.requires), BOOL, 'E_CONTRACT', 'requires condition must be bool', fn.requires.pos)
        # Postconditions see parameters and the result, not body-local declarations.
        if fn.ensures is not None:
            result.initialized = True
            self.require(self.infer(fn.ensures), BOOL, 'E_CONTRACT', 'ensures condition must be bool', fn.ensures.pos)
            result.initialized = False
        self.block(fn.body, new_scope=False)
        if inserted and not result.initialized:
            self.error('E_RETURN_UNINITIALIZED', f"return variable '{fn.returns}' is not assigned on every path", fn.return_pos)
        self.finish_scope()

    def require(self, actual: Type, expected: Type, code: str, message: str, pos: Pos) -> bool:
        try:
            unify(actual, expected)
            return actual != ERROR and expected != ERROR
        except UnificationError:
            self.error(code, f'{message}, got {actual}', pos)
            return False

    def assignment_type(self, expected: Type, actual: Type, pos: Pos):
        try:
            unify(expected, actual)
        except UnificationError:
            self.error('E_ASSIGN_TYPE', f'cannot assign {actual} to {expected}', pos)

    @staticmethod
    def mark(node: ast.Node, typ: Type) -> Type:
        node.type = str(typ)
        return typ

    def infer(self, node: ast.Expr) -> Type:
        if isinstance(node, ast.Int):
            return self.mark(node, INT)
        if isinstance(node, ast.Bool):
            return self.mark(node, BOOL)
        if isinstance(node, ast.Ident):
            symbol = self.table.lookup(node.name)
            if symbol is None:
                self.error('E_UNDECLARED', f"use of undeclared '{node.name}'", node.pos)
                return self.mark(node, ERROR)
            if not symbol.initialized:
                self.error('E_UNINITIALIZED', f"use of uninitialized '{node.name}'", node.pos)
                return self.mark(node, ERROR)
            return self.mark(node, symbol.type if symbol.type is not None else ERROR)
        if isinstance(node, ast.ArrayIndex):
            base, index = self.infer(node.base), self.infer(node.index)
            valid = self.require(index, INT, 'E_INDEX_TYPE', 'array index must be int', node.index.pos)
            if base == ERROR:
                return self.mark(node, ERROR)
            if base.name != 'array':
                self.error('E_NOT_ARRAY', f'cannot index {base}', node.pos)
                return self.mark(node, ERROR)
            return self.mark(node, base.elem if valid else ERROR)
        if isinstance(node, ast.UnaryOp):
            operand = self.infer(node.operand)
            expected = BOOL if node.op == 'not' else INT
            valid = self.require(operand, expected, 'E_OPERATOR', f"operator '{node.op}' requires {expected}", node.pos)
            return self.mark(node, expected if valid else ERROR)
        if isinstance(node, ast.BinaryOp):
            left, right = self.infer(node.left), self.infer(node.right)
            op = node.op
            if op in ('==', '!='):
                valid = True
                try:
                    unify(left, right)
                except UnificationError:
                    self.error('E_OPERATOR', f"operator '{op}' requires equal operand types, got {left} and {right}", node.pos)
                    valid = False
                if left.name == 'func' or right.name == 'func':
                    self.error('E_OPERATOR', 'functions cannot be compared', node.pos)
                    valid = False
                return self.mark(node, BOOL if valid and ERROR not in (left, right) else ERROR)
            expected = BOOL if op in ('and', 'or') else INT
            # A poisoned operand must not hide an independent error in its sibling.
            l_ok = self.require(left, expected, 'E_OPERATOR', f"operator '{op}' requires {expected}", node.left.pos)
            r_ok = self.require(right, expected, 'E_OPERATOR', f"operator '{op}' requires {expected}", node.right.pos)
            result = BOOL if op in ('<', '<=', '>', '>=', 'and', 'or') else INT
            return self.mark(node, result if l_ok and r_ok else ERROR)
        if isinstance(node, ast.Call):
            return self.infer_call(node)
        raise TypeError(f'unknown expression: {node!r}')

    def infer_call(self, node: ast.Call) -> Type:
        arguments = [self.infer(arg) for arg in node.args]
        symbol = self.table.lookup(node.name)
        # length is a keyword in HW2, store is the builtin used by desugaring.
        if node.name in ('length', 'store') and symbol is None:
            return self.builtin(node, arguments)
        if symbol is None:
            self.error('E_UNKNOWN_FUNCTION', f"unknown function '{node.name}'", node.pos)
            return self.mark(node, ERROR)
        if not symbol.initialized:
            self.error('E_UNINITIALIZED', f"use of uninitialized '{node.name}'", node.pos)
            return self.mark(node, ERROR)
        if symbol.type is None or symbol.type.name != 'func':
            if symbol.type != ERROR:
                self.error('E_NOT_CALLABLE', f"'{node.name}' is not callable", node.pos)
            return self.mark(node, ERROR)
        expected = symbol.type.args[:-1]
        valid = True
        if len(arguments) != len(expected):
            self.error('E_ARG_COUNT', f"function '{node.name}' expects {len(expected)} args, got {len(arguments)}", node.pos)
            valid = False
        for i, (actual, target) in enumerate(zip(arguments, expected), 1):
            try:
                unify(actual, target)
            except UnificationError:
                self.error('E_ARG_TYPE', f"argument {i} of '{node.name}': expected {target}, got {actual}", node.args[i-1].pos)
                valid = False
        if ERROR in arguments:
            valid = False
        return self.mark(node, symbol.type.args[-1] if valid else ERROR)

    def builtin(self, node: ast.Call, args: List[Type]) -> Type:
        count = 1 if node.name == 'length' else 3
        if len(args) != count:
            self.error('E_ARG_COUNT', f"function '{node.name}' expects {count} args, got {len(args)}", node.pos)
            return self.mark(node, ERROR)
        base = args[0]
        valid = True
        if base != ERROR and base.name != 'array':
            self.error('E_ARG_TYPE', f"argument 1 of '{node.name}': expected array<T>, got {base}", node.args[0].pos)
            valid = False
        if node.name == 'store':
            valid = self.require(args[1], INT, 'E_INDEX_TYPE', 'array index must be int', node.args[1].pos) and valid
            if base.name == 'array':
                try:
                    unify(base.elem, args[2])
                except UnificationError:
                    self.error('E_ARG_TYPE', f"argument 3 of 'store': expected {base.elem}, got {args[2]}", node.args[2].pos)
                    valid = False
        if ERROR in args:
            valid = False
        result = INT if node.name == 'length' else base
        return self.mark(node, result if valid else ERROR)

    def block(self, node: ast.Block, new_scope=True):
        if new_scope:
            self.table.enter_scope()
        for stmt in node.stmts:
            self.statement(stmt)
        if new_scope:
            self.finish_scope()

    def statement(self, node: ast.Stmt):
        if isinstance(node, ast.Block):
            self.block(node)
        elif isinstance(node, ast.VarDecl):
            value = self.infer(node.value) if node.value is not None else None
            declared = parse_type(node.annotation) if node.annotation is not None else None
            typ = declared if declared is not None else (value if value != ERROR else None)
            if declared is not None and value is not None:
                self.assignment_type(declared, value, node.value.pos)
            symbol = Symbol(node.name, typ, 'var', node.pos, value is not None, node)
            self.declare(symbol)
            if typ is not None:
                node.type = str(typ)
            self.read_nodes.append((node, symbol))
        elif isinstance(node, ast.Assign):
            value = self.infer(node.value)
            if isinstance(node.target, ast.Ident):
                symbol = self.table.lookup(node.target.name)
                if symbol is None:
                    self.error('E_UNDECLARED', f"use of undeclared '{node.target.name}'", node.target.pos)
                    self.mark(node.target, ERROR)
                elif symbol.kind == 'func':
                    self.error('E_ASSIGN_FUNCTION', f"cannot assign to function '{symbol.name}'", node.target.pos)
                    self.mark(node.target, ERROR)
                else:
                    if symbol.type is None and value != ERROR:
                        symbol.type = value
                        if symbol.declaration is not None:
                            symbol.declaration.type = str(value)
                    if symbol.type is not None:
                        self.assignment_type(symbol.type, value, node.value.pos)
                        self.mark(node.target, symbol.type)
                    else:
                        self.read_nodes.append((node.target, symbol))
                    symbol.initialized = True
            else:
                target = self.infer(node.target)
                self.assignment_type(target, value, node.value.pos)
        elif isinstance(node, ast.If):
            self.require(self.infer(node.cond), BOOL, 'E_CONDITION', 'if condition must be bool', node.cond.pos)
            before = [(s, s.initialized) for s in self.table.visible_symbols()]
            self.block(node.then)
            then_state = [s.initialized for s, _ in before]
            for symbol, init in before:
                symbol.initialized = init
            if node.else_ is not None:
                self.block(node.else_)
            for (symbol, _), then_init in zip(before, then_state):
                symbol.initialized = symbol.initialized and then_init
        elif isinstance(node, ast.While):
            self.require(self.infer(node.cond), BOOL, 'E_CONDITION', 'while condition must be bool', node.cond.pos)
            if node.invariant is not None:
                self.require(self.infer(node.invariant), BOOL, 'E_CONTRACT', 'invariant condition must be bool', node.invariant.pos)
            before = [(s, s.initialized) for s in self.table.visible_symbols()]
            self.block(node.body)
            for symbol, initialized in before:
                symbol.initialized = initialized
        elif isinstance(node, (ast.Assert, ast.Assume)):
            kind = 'assert' if isinstance(node, ast.Assert) else 'assume'
            self.require(self.infer(node.expr), BOOL, 'E_CONDITION', f'{kind} condition must be bool', node.expr.pos)
        else:
            raise TypeError(f'unknown statement: {node!r}')


def analyze(program: ast.Program) -> SemanticResult:
    return SemanticAnalyzer().check(program)
