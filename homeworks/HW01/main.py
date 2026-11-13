#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HW1. Lexer: regex -> NFA (Thompson) -> DFA (subset construction) -> minimized DFA (Hopcroft)

Запуск:
    python3 main.py build                 # построить автомат, вывести статистику
    python3 main.py export --out-dir out  # построить + экспортировать таблицу переходов
    python3 main.py test                  # построить + прогнать тесты из tests/test_cases.json
    python3 main.py tokenize FILE          # построить + токенизировать файл, напечатать поток токенов
    python3 main.py all                   # build + export + test (по умолчанию)
"""
import argparse
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from funny_lexer.build import build_lexer_automaton
from funny_lexer.export import export_json, export_csv
from funny_lexer.tests_runner import load_test_cases, run_test_cases, print_report
from funny_lexer.tokenizer import tokenize
from funny_lexer.token_specs import TOKEN_SPECS

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TESTS = os.path.join(HERE, "tests", "test_cases.json")
DEFAULT_OUT = os.path.join(HERE, "out")


def cmd_build(args):
    res = build_lexer_automaton()
    print("Токен-спецификаций: %d" % len(TOKEN_SPECS))
    print("Состояний в объединённом NFA (Thompson):  %d" % res.nfa_state_count)
    print("Состояний в ДКА (subset construction):    %d" % res.dfa_state_count)
    print("Состояний в минимизированном ДКА (Hopcroft): %d" % res.min_dfa_state_count)
    return res


def cmd_export(args):
    res = cmd_build(args)
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    export_json(res.dfa, os.path.join(out_dir, "dfa_full.json"))
    export_csv(res.dfa, os.path.join(out_dir, "dfa_full.csv"))
    export_json(res.min_dfa, os.path.join(out_dir, "dfa_min.json"))
    export_csv(res.min_dfa, os.path.join(out_dir, "dfa_min.csv"))

    print("\nЭкспортировано в %s:" % out_dir)
    for fn in ["dfa_full.json", "dfa_full.csv", "dfa_min.json", "dfa_min.csv"]:
        print("  - %s" % fn)
    return res


def cmd_test(args):
    res = cmd_build(args)
    cases = load_test_cases(args.tests)
    print("\n=== Прогон тестов на ПОЛНОМ ДКА ===")
    results_full, p_full, t_full = run_test_cases(res.dfa, cases)
    print_report(results_full, p_full, t_full)

    print("\n=== Прогон тестов на МИНИМИЗИРОВАННОМ ДКА ===")
    results_min, p_min, t_min = run_test_cases(res.min_dfa, cases)
    print_report(results_min, p_min, t_min)

    if p_full != t_full or p_min != t_min:
        sys.exit(1)
    return res


def cmd_tokenize(args):
    res = cmd_build(args)
    with open(args.file, "r", encoding="utf-8") as f:
        text = f.read()
    tokens, errors = tokenize(res.min_dfa, text)
    print("\n=== Токены ===")
    for t in tokens:
        print(t)
    if errors:
        print("\n=== Ошибки (символ вне покрытия / вне алфавита) ===")
        for pos, ch in errors:
            print("позиция %d: %r" % (pos, ch))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p_build = sub.add_parser("build", help="построить автомат и вывести статистику")
    p_build.set_defaults(func=cmd_build)

    p_export = sub.add_parser("export", help="построить и экспортировать таблицы переходов")
    p_export.add_argument("--out-dir", default=DEFAULT_OUT)
    p_export.set_defaults(func=cmd_export)

    p_test = sub.add_parser("test", help="построить и прогнать тесты")
    p_test.add_argument("--tests", default=DEFAULT_TESTS)
    p_test.set_defaults(func=cmd_test)

    p_tok = sub.add_parser("tokenize", help="токенизировать файл")
    p_tok.add_argument("file")
    p_tok.set_defaults(func=cmd_tokenize)

    p_all = sub.add_parser("all", help="build + export + test")
    p_all.add_argument("--out-dir", default=DEFAULT_OUT)
    p_all.add_argument("--tests", default=DEFAULT_TESTS)

    def cmd_all(args):
        cmd_export(args)
        print()
        cmd_test(args)

    p_all.set_defaults(func=cmd_all)

    args = ap.parse_args()
    if not args.cmd:
        args = ap.parse_args(["all"])
    args.func(args)


if __name__ == "__main__":
    main()
