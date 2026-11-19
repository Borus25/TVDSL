"""Independent assertions, beyond AST snapshots and hand-written fixture codes."""
import dataclasses
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import funny_ast as ast
from funny_types import BOOL, ERROR, INT, UnificationError, array_type, func_type, parse_type, unify
from lexer import Lexer
from ll1 import load_grammar
from main import compile_source
from parser import parse
from semantic import SemanticAnalyzer, Symbol, SymbolTable

HERE = Path(__file__).resolve().parent
EXPRS = (ast.Int, ast.Bool, ast.Ident, ast.ArrayIndex, ast.Call, ast.UnaryOp, ast.BinaryOp)


def walk(node):
    if dataclasses.is_dataclass(node):
        yield node
        for field in dataclasses.fields(node):
            yield from walk(getattr(node, field.name))
    elif isinstance(node, (list, tuple)):
        for child in node:
            yield from walk(child)


def compile_body(body, result='int'):
    return compile_source(f'function f() returns r: {result} {{ {body} }}')


class TypeTests(unittest.TestCase):
    def test_primitive_equality(self):
        self.assertEqual(unify(INT, INT), INT)
        with self.assertRaises(UnificationError):
            unify(INT, BOOL)

    def test_nested_array_unification(self):
        typ = parse_type('array<array<int>>')
        self.assertEqual(typ, array_type(array_type(INT)))
        self.assertEqual(unify(typ, typ), typ)
        with self.assertRaises(UnificationError):
            unify(typ, parse_type('array<array<bool>>'))

    def test_function_unification(self):
        self.assertEqual(str(func_type([INT, BOOL], INT)), 'func(int, bool)->int')
        self.assertEqual(unify(func_type([INT], BOOL), func_type([INT], BOOL)), func_type([INT], BOOL))
        with self.assertRaises(UnificationError):
            unify(func_type([INT], INT), func_type([], INT))
        with self.assertRaises(UnificationError):
            unify(func_type([INT], BOOL), func_type([BOOL], BOOL))

    def test_error_is_not_int(self):
        self.assertEqual(unify(ERROR, BOOL), ERROR)
        self.assertNotEqual(ERROR, INT)

    def test_invalid_type_rejected(self):
        for name in ['string', '', 'array<>']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                parse_type(name)


class SymbolTests(unittest.TestCase):
    def test_shadowing_and_restoration(self):
        table = SymbolTable()
        outer = Symbol('x', INT, 'var', (1, 1))
        self.assertIsNone(table.declare(outer))
        table.enter_scope()
        inner = Symbol('x', BOOL, 'var', (2, 1))
        table.declare(inner)
        self.assertIs(table.lookup('x'), inner)
        table.exit_scope()
        self.assertIs(table.lookup('x'), outer)
        self.assertIsNone(table.lookup('unknown'))

    def test_duplicate_keeps_first(self):
        table = SymbolTable()
        first = Symbol('x', INT, 'var', (1, 1))
        table.declare(first)
        self.assertIs(table.declare(Symbol('x', BOOL, 'var', (2, 1))), first)
        self.assertIs(table.lookup('x'), first)
        with self.assertRaises(RuntimeError):
            table.exit_scope()


class SemanticTests(unittest.TestCase):
    def test_exact_multiple_error_positions(self):
        text = (HERE/'tests/neg_multiple_errors.funny').read_text()
        _, errors = compile_source(text)
        self.assertEqual([(e.code, e.line, e.col) for e in errors],
                         [('E_UNDECLARED', 2, 7), ('E_ASSIGN_TYPE', 3, 17), ('E_ASSIGN_TYPE', 4, 16)])
        self.assertIn('cannot assign int to bool', errors[1].message)

    def test_no_cascade_exact(self):
        _, errors = compile_body('r = y + 1 + z;')
        self.assertEqual([e.code for e in errors], ['E_UNDECLARED', 'E_UNDECLARED'])
        self.assertIn("'y'", errors[0].message)
        self.assertIn("'z'", errors[1].message)

    def test_callable_alias_must_be_initialized(self):
        source = ('function g() returns r:int {r=0;} '
                  'function f(b:bool) returns r:int {var h; if(b){h=g;} r=h();}')
        _, errors = compile_source(source)
        self.assertEqual([e.code for e in errors], ['E_UNINITIALIZED'])

    def test_infer_from_later_valid_assignment(self):
        program, errors = compile_body('var x; x=y; x=1; r=x;')
        self.assertEqual([e.code for e in errors], ['E_UNDECLARED'])
        self.assertEqual(program.functions[0].body.stmts[0].type, 'int')

    def test_contradiction_does_not_retype_variable(self):
        program, errors = compile_body('var x=1; x=true; r=x;')
        self.assertEqual([e.code for e in errors], ['E_ASSIGN_TYPE'])
        self.assertEqual(program.functions[0].body.stmts[-1].value.type, 'int')

    def test_initializer_uses_outer_binding(self):
        program, errors = compile_body('var x=1; {var x=x+1; assert x>1;} r=x;')
        self.assertEqual(errors, [])
        self.assertEqual(program.functions[0].body.stmts[1].stmts[0].type, 'int')

    def test_if_initialization_merge(self):
        _, errors = compile_body('var x:int; if(true){x=1;} r=x;')
        self.assertEqual([e.code for e in errors], ['E_UNINITIALIZED'])
        _, errors = compile_body('var x:int; if(true){x=1;}else{x=2;} r=x;')
        self.assertEqual(errors, [])

    def test_all_successful_expression_nodes_have_types(self):
        for path in sorted((HERE/'tests').glob('pos_*.funny')):
            with self.subTest(path=path.name):
                program, errors = compile_source(path.read_text())
                self.assertEqual(errors, [])
                exprs = [node for node in walk(program) if isinstance(node, EXPRS)]
                self.assertTrue(exprs)
                self.assertTrue(all(node.type not in (None, '<error>') for node in exprs))

    def test_error_expressions_are_annotated(self):
        program, errors = compile_body('r=y+1;')
        self.assertEqual([e.code for e in errors], ['E_UNDECLARED'])
        exprs = [node for node in walk(program) if isinstance(node, EXPRS)]
        self.assertTrue(all(node.type is not None for node in exprs))
        self.assertEqual(program.functions[0].body.stmts[0].value.type, '<error>')

    def test_json_roundtrip_typed_ast(self):
        for path in (HERE/'tests').glob('pos_*.funny'):
            with self.subTest(path=path.name):
                program, _ = compile_source(path.read_text())
                raw = ast.to_dict(program)
                self.assertEqual(raw, ast.to_dict(ast.from_dict(json.loads(json.dumps(raw)))) )

    def test_desugar_nested_array_preserves_types(self):
        source = (HERE/'tests/pos_array_nested.funny').read_text()
        program, errors = compile_source(source, lower_arrays=True)
        self.assertEqual(errors, [])
        calls = [node for node in walk(program) if isinstance(node, ast.Call) and node.name == 'store']
        self.assertEqual([c.type for c in calls], ['array<array<int>>', 'array<int>'])
        self.assertIsInstance(program.functions[0].body.stmts[0].target, ast.Ident)

    def test_analyzer_can_be_reused(self):
        analyzer = SemanticAnalyzer()
        first = parse('function f() returns r:int {r=y;}').program
        second = parse('function f() returns r:int {r=0;}').program
        self.assertFalse(analyzer.check(first).ok)
        self.assertTrue(analyzer.check(second).ok)

    def test_conditions_contracts_and_invariant(self):
        _, errors = compile_source('function f() returns r:int requires 1 ensures 2 {r=0; while(3) invariant 4 {assert 5; assume 6;}}')
        self.assertEqual([e.code for e in errors], ['E_CONTRACT','E_CONTRACT','E_CONDITION','E_CONTRACT','E_CONDITION','E_CONDITION'])

    def test_forward_signature_uses_declared_result(self):
        program, errors = compile_source('function f() returns r:bool {r=g(1);} function g(x:int) returns r:bool {r=x>0;}')
        self.assertEqual(errors, [])
        self.assertEqual(program.functions[0].body.stmts[0].value.type, 'bool')

    def test_extra_arguments_still_checked(self):
        _, errors = compile_source('function f() returns r:int {r=g(y);} function g() returns r:int {r=1;}')
        self.assertEqual([e.code for e in errors], ['E_ARG_COUNT', 'E_UNDECLARED'])


class ParserIntegrationTests(unittest.TestCase):
    def test_grammar_ll1(self):
        self.assertEqual(load_grammar().conflicts, [])

    def test_table_parser_matches_recursive_parser(self):
        grammar = load_grammar()
        for path in sorted((HERE/'tests').glob('*.funny')):
            with self.subTest(path=path.name):
                source = path.read_text()
                lexer = Lexer(source)
                kinds = [t.kind for t in lexer.tokens()]
                table_ok = grammar.parse(kinds) is None and not lexer.diagnostics
                self.assertEqual(table_ok, parse(source).ok)

    def test_parse_only_accepts_old_untyped_syntax(self):
        source = 'function f(x) returns r {r=x+1;}'
        program, errors = compile_source(source, semantic=False)
        self.assertEqual(errors, [])
        self.assertEqual(program.functions[0].params, ['x'])
        _, errors = compile_source(source)
        self.assertEqual([e.code for e in errors], ['E_MISSING_TYPE','E_MISSING_TYPE'])

    def test_all_original_hw2_positive_fixtures_parse(self):
        for path in (HERE.parent/'HW02/tests').glob('pos_*.funny'):
            with self.subTest(path=path.name):
                self.assertTrue(parse(path.read_text(encoding='utf-8')).ok)

    def test_cli_json_and_exit_codes(self):
        for name, code in [('pos_types_ok', 0), ('neg_multiple_errors', 1)]:
            with self.subTest(name=name):
                proc = subprocess.run([sys.executable, str(HERE/'main.py'), str(HERE/'tests'/(name+'.funny')), '--json'],
                                      capture_output=True, text=True, cwd=HERE.parent)
                self.assertEqual(proc.returncode, code, proc.stderr)
                payload = json.loads(proc.stdout)
                self.assertEqual(payload['ok'], code == 0)
                self.assertIsNotNone(payload['ast'])

    def test_cli_file_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'ast.json'
            proc = subprocess.run([sys.executable, str(HERE/'main.py'), str(HERE/'tests/pos_types_ok.funny'), '--json', '--out', str(path)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.stdout), json.loads(path.read_text()))

    def test_cli_syntax_error_has_null_ast(self):
        proc = subprocess.run([sys.executable, str(HERE/'main.py'), str(HERE/'tests/neg_syntax.funny'), '--json'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertIsNone(payload['ast'])
        self.assertEqual(payload['diagnostics'][0]['code'], 'E_PARSE')

    def test_lexer_new_tokens_and_keyword_prefix(self):
        tokens = Lexer('var x: array<int> varx int2 bool2 array2').tokens()
        self.assertEqual([t.kind for t in tokens], ['VAR','IDENT',':','TYPE_ARRAY','<','TYPE_INT','>','IDENT','IDENT','IDENT','IDENT','EOF'])


if __name__ == '__main__':
    unittest.main()
