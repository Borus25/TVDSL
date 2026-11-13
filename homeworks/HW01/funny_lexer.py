#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
from collections import deque

from funny_lexer.build import build_lexer_automaton
from funny_lexer.token_specs import SKIP_TOKENS
from funny_lexer.tokenizer import tokenize

OP_TYPES = {
    "LPAREN", "RPAREN", "LBRACKET", "RBRACKET",
    "LBRACE", "RBRACE", "COMMA", "SEMI",
    "EQEQ", "NEQ", "LE", "GE", "LT", "GT", "ASSIGN",
    "PLUS", "MINUS", "STAR", "SLASH",
}


def public_type(token_type):
    if token_type.startswith("KW_"):
        return token_type[3:]
    if token_type in OP_TYPES:
        return "OP"
    return token_type


# input, expected first token, comment, expected all tokens, error positions
TESTS = [
    ("", None, "пустая строка", [], []),
    (" \t\r\n", "WS", "только пробелы", ["WS"], []),
    ("0", "INT", "ноль", ["INT"], []),
    ("00", "INT", "00 — INT(0) + INT(0)", ["INT", "INT"], []),
    ("01", "INT", "01 — INT(0) + INT(1)", ["INT", "INT"], []),
    ("42", "INT", "двузначное", ["INT"], []),
    ("100", "INT", "трёхзначное", ["INT"], []),
    ("foo", "IDENT", "простой IDENT", ["IDENT"], []),
    ("foo_bar", "IDENT", "IDENT с _", ["IDENT"], []),
    ("_x", "IDENT", "IDENT с _ в начале", ["IDENT"], []),
    ("_1", "IDENT", "IDENT с цифрой", ["IDENT"], []),
    ("function", "FUNCTION", "kw", ["FUNCTION"], []),
    ("returns", "RETURNS", "kw", ["RETURNS"], []),
    ("uses", "USES", "kw", ["USES"], []),
    ("while", "WHILE", "kw", ["WHILE"], []),
    ("if", "IF", "kw", ["IF"], []),
    ("else", "ELSE", "kw", ["ELSE"], []),
    ("true", "TRUE", "kw", ["TRUE"], []),
    ("false", "FALSE", "kw", ["FALSE"], []),
    ("not", "NOT", "kw", ["NOT"], []),
    ("and", "AND", "kw", ["AND"], []),
    ("or", "OR", "kw", ["OR"], []),
    ("functio", "IDENT", "префикс kw -> IDENT", ["IDENT"], []),
    ("iff", "IDENT", "префикс kw -> IDENT", ["IDENT"], []),
    ("(", "OP", "(", ["OP"], []),
    (")", "OP", ")", ["OP"], []),
    ("[", "OP", "[", ["OP"], []),
    ("]", "OP", "]", ["OP"], []),
    ("{", "OP", "{", ["OP"], []),
    ("}", "OP", "}", ["OP"], []),
    (",", "OP", ",", ["OP"], []),
    (";", "OP", ";", ["OP"], []),
    ("+", "OP", "+", ["OP"], []),
    ("-", "OP", "-", ["OP"], []),
    ("*", "OP", "*", ["OP"], []),
    ("/", "OP", "/", ["OP"], []),
    ("==", "OP", "==", ["OP"], []),
    ("!=", "OP", "!=", ["OP"], []),
    ("<=", "OP", "<=", ["OP"], []),
    (">=", "OP", ">=", ["OP"], []),
    ("<", "OP", "<", ["OP"], []),
    (">", "OP", ">", ["OP"], []),
    ("=", "OP", "=", ["OP"], []),
    ("===", "OP", "maximal munch: OP(==) + OP(=)", ["OP", "OP"], []),
    ("// comment", "COMMENT", "комментарий до конца строки", ["COMMENT"], []),
    ("//", "COMMENT", "пустой комментарий", ["COMMENT"], []),
    ("π", None, "non-ASCII -> trap", [], [0]),
    ("@", None, "мусорный ASCII -> trap", [], [0]),
    ("\x80", None, "байт вне ASCII -> trap", [], [0]),
    ("1π", "INT", "1 корректно, π -> trap после", ["INT"], [1]),
]


def canonical_numbering(dfa):
    trap = dfa.trap_state
    mapping = {dfa.start: 0}
    queue = deque([dfa.start])
    while queue:
        state = queue.popleft()
        for symbol in dfa.alphabet:
            dst = dfa.trans[(state, symbol)]
            if dst != trap and dst not in mapping:
                mapping[dst] = len(mapping)
                queue.append(dst)
    for state in sorted(dfa.states, key=str):
        if state != trap and state not in mapping:
            mapping[state] = len(mapping)
    mapping[trap] = len(mapping)
    return mapping


def dfa_dict(dfa):
    numbers = canonical_numbering(dfa)
    states = sorted(dfa.states, key=lambda state: numbers[state])
    accepts = {}
    for state in states:
        token_type = dfa.accepts.get(state)
        if token_type is not None:
            accepts[str(numbers[state])] = [
                public_type(token_type), token_type in SKIP_TOKENS
            ]
    transitions = {
        str(numbers[state]): {
            str(ord(symbol)): numbers[dfa.trans[(state, symbol)]]
            for symbol in dfa.alphabet
        }
        for state in states
    }
    return {
        "alphabet_size": len(dfa.alphabet),
        "states": len(states),
        "start": numbers[dfa.start],
        "trap": numbers[dfa.trap_state],
        "accept": accepts,
        "transitions": transitions,
    }


def write_json(dfa, path):
    data = dfa_dict(dfa)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    return data


def check_case(dfa, source, expected_all, expected_errors):
    tokens, errors = tokenize(dfa, source, include_skipped=True)
    actual_all = [public_type(token.type) for token in tokens]
    actual_errors = [position for position, _ in errors]
    return actual_all, actual_errors, (
        actual_all == expected_all and actual_errors == expected_errors
    )


def run_tests(full_dfa, min_dfa):
    rows = []
    passed = 0
    for source, expected, comment, expected_all, expected_errors in TESTS:
        full_types, full_errors, full_ok = check_case(
            full_dfa, source, expected_all, expected_errors
        )
        min_types, min_errors, min_ok = check_case(
            min_dfa, source, expected_all, expected_errors
        )
        same = full_types == min_types and full_errors == min_errors
        ok = full_ok and min_ok and same
        passed += int(ok)
        actual = min_types[0] if min_types else None
        rows.append((repr(source), expected, actual, ok, comment))

    input_w = max(len("input"), *(len(row[0]) for row in rows))
    expected_w = max(len("expected"), *(len(str(row[1])) for row in rows))
    actual_w = max(len("actual"), *(len(str(row[2])) for row in rows))

    print()
    print(
        f"{'input':<{input_w}}  {'expected':<{expected_w}}  "
        f"{'actual':<{actual_w}}  ok  comment"
    )
    print("-" * (input_w + expected_w + actual_w + 20))
    for source, expected, actual, ok, comment in rows:
        expected_text = "None" if expected is None else expected
        actual_text = "None" if actual is None else actual
        mark = "✓" if ok else "✗"
        print(
            f"{source:<{input_w}}  {expected_text:<{expected_w}}  "
            f"{actual_text:<{actual_w}}  {mark}   {comment}"
        )
    print("-" * (input_w + expected_w + actual_w + 20))
    print(f"{passed}/{len(TESTS)} tests passed")
    print("ALL PASS" if passed == len(TESTS) else "TESTS FAILED")
    return passed == len(TESTS)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Генератор минимизированного ДКА лексера Funny"
    )
    parser.add_argument("--out", default="dfa.json", metavar="FILE")
    parser.add_argument("--tests", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    result = build_lexer_automaton()
    data = write_json(result.min_dfa, args.out)
    print(f"States: {data['states']}, start={data['start']}, trap={data['trap']}")
    print("Accept: " + json.dumps(data["accept"], ensure_ascii=False))
    if args.tests and not run_tests(result.dfa, result.min_dfa):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())