"""CLI: parse with the extended HW2 parser, then check semantics (default)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from funny_ast import desugar, to_dict, to_sexp
from lexer import Diagnostic, Lexer
from parser import parse
from semantic import analyze


def compile_source(text: str, *, semantic=True, lower_arrays=False):
    parsed = parse(text)
    if not parsed.ok:
        return None, parsed.diagnostics
    program = desugar(parsed.program) if lower_arrays else parsed.program
    if not semantic:
        return program, []
    result = analyze(program)
    return result.program, result.diagnostics


def diagnostic_dict(diagnostic):
    if isinstance(diagnostic, Diagnostic):
        return {'phase': 'syntax/lexical', 'code': 'E_PARSE', 'message': diagnostic.message,
                'line': diagnostic.line, 'col': diagnostic.col}
    return diagnostic.to_dict()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Funny HW3: scoped names, types, annotated HW2 AST')
    parser.add_argument('file', nargs='?', help='Funny source file; read stdin when omitted')
    parser.add_argument('--semantic', action='store_true', help='Check semantics (enabled by default)')
    parser.add_argument('--parse-only', action='store_true', help='Only the extended HW2 parser; no semantic pass')
    parser.add_argument('--json', action='store_true', help='Single JSON object with AST, diagnostics and ok')
    parser.add_argument('--out', help='Write JSON result to this file')
    parser.add_argument('--sexp', action='store_true', help='S-expression instead of JSON AST on stdout')
    parser.add_argument('--tokens', action='store_true', help='Show lexer tokens, without parsing')
    parser.add_argument('--desugar', action='store_true', help='Lower a[i]=v to store calls before semantic analysis')
    parser.add_argument('--test', action='store_true', help='Run fixture and unit tests')
    parser.add_argument('--grammar', action='store_true', help='Report LL(1) conflicts for the HW3 grammar')
    args = parser.parse_args(argv)
    if args.test:
        from run_tests import main as test_main
        return test_main()
    if args.grammar:
        from ll1 import load_grammar
        grammar = load_grammar()
        print(f'LL(1) conflicts: {len(grammar.conflicts)}')
        for conflict in grammar.conflicts:
            print(conflict)
        return 1 if grammar.conflicts else 0
    try:
        text = Path(args.file).read_text(encoding='utf-8') if args.file else sys.stdin.read()
        if args.tokens:
            lexer = Lexer(text)
            print(json.dumps([t.to_dict() for t in lexer.tokens()], indent=2, ensure_ascii=False))
            for diagnostic in lexer.diagnostics:
                print(diagnostic, file=sys.stderr)
            return 1 if lexer.diagnostics else 0
        program, diagnostics = compile_source(text, semantic=not args.parse_only, lower_arrays=args.desugar)
        payload = {'format': 'funny-typed-ast/1', 'ok': not diagnostics,
                   'ast': to_dict(program) if program is not None else None,
                   'diagnostics': [diagnostic_dict(d) for d in diagnostics]}
        rendered = json.dumps(payload, ensure_ascii=False, indent=2) + '\n'
        if args.out:
            path = Path(args.out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding='utf-8')
        if args.json:
            print(rendered, end='')
        else:
            if program is not None:
                print(to_sexp(program) if args.sexp else json.dumps(to_dict(program), ensure_ascii=False, indent=2))
            for diagnostic in diagnostics:
                print(diagnostic, file=sys.stderr)
        return 1 if diagnostics else 0
    except (OSError, UnicodeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
