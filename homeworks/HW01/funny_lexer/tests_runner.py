# -*- coding: utf-8 -*-
import json
from .tokenizer import tokenize


def load_test_cases(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_test_cases(dfa, cases):
    results = []
    n_pass = 0
    for case in cases:
        tokens, errors = tokenize(dfa, case["input"])
        got_tokens = [list(t.to_tuple()) for t in tokens]
        got_error_positions = [pos for pos, _ in errors]

        ok_tokens = got_tokens == case["expected_tokens"]
        ok_errors = got_error_positions == case["expected_error_positions"]
        ok = ok_tokens and ok_errors
        if ok:
            n_pass += 1

        results.append({
            "name": case["name"],
            "input": case["input"],
            "status": "PASS" if ok else "FAIL",
            "expected_tokens": case["expected_tokens"],
            "got_tokens": got_tokens,
            "expected_error_positions": case["expected_error_positions"],
            "got_error_positions": got_error_positions,
        })
    return results, n_pass, len(cases)


def print_report(results, n_pass, n_total):
    for r in results:
        mark = "OK  " if r["status"] == "PASS" else "FAIL"
        print("[%s] %s  input=%r" % (mark, r["name"], r["input"]))
        if r["status"] == "FAIL":
            print("       expected_tokens=%s" % r["expected_tokens"])
            print("       got_tokens     =%s" % r["got_tokens"])
            print("       expected_errors=%s got_errors=%s" % (
                r["expected_error_positions"], r["got_error_positions"]))
    print("\n%d/%d tests passed" % (n_pass, n_total))
