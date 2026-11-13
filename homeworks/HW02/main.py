"""CLI парсера Funny (HW2) — точка входа.

ОБЩАЯ СХЕМА: что происходит от текста программы до AST
(поиск по этапам в PyCharm: Ctrl+Shift+F -> «ЭТАП»)

  funny.lex ─[ЭТАП 1: dfa_build.py]─> dfa.json          (один раз, при изменении токенов)
                                         │
  текст ─────[ЭТАП 2: lexer.py]──────> токены {kind, lexeme, line, col}
                                         │
  grammar.txt ─[ЭТАП 3]─ LL(1)-форма ─[ЭТАП 4: ll1.py]─> FIRST, FOLLOW, M, 0 конфликтов
                                         │                 (по ним выбраны ветки и якоря)
             [ЭТАПЫ 5–8: parser.py] рекурсивный спуск, один токен вперёд
                                         │ ── ошибка? ─> [ЭТАП 9: паника] пропуск до якоря,
                                         │               сообщение «... at строка:столбец»,
                                         │               разбор продолжается
             [ЭТАП 10: funny_ast.py] AST ─> JSON / S-выражение / desugar
                                         │
             [ЭТАП 11: main.py] печать: AST в stdout, ошибки в stderr
             [ЭТАП 12: main.py --test, test_parser.py] проверки

  ЭТАП 1.  Таблица лексера: funny.lex -> НКА -> ДКА -> min ДКА -> dfa.json (конвейер HW1)
  ЭТАП 2.  Лексер: текст -> токены с позициями, next_token() / peek()
  ЭТАП 3.  Грамматика: убрать левую рекурсию, факторизовать -> LL(1)-форма
  ЭТАП 4.  FIRST / FOLLOW / таблица M[A, a], проверка, что конфликтов нет
  ЭТАП 5.  Каркас парсера: текущий токен, advance / expect
  ЭТАП 6.  Программа, функция, параметры
  ЭТАП 7.  Операторы: block, присваивание, if, while, assert, assume
  ЭТАП 8.  Выражения: лесенка приоритетов (ПРИОРИТЕТ 1–7)
  ЭТАП 9.  Ошибки: режим паники, якоря, защита от зацикливания
  ЭТАП 10. AST: узлы, JSON, S-выражения, сахар массивов
  ЭТАП 11. CLI: разбор аргументов, вывод результата
  ЭТАП 12. Тесты: snapshot (tests/) и юнит-тесты (test_parser.py)

Команды:

  python3 main.py prog.funny              AST в JSON (с позициями)
  python3 main.py prog.funny --sexp       AST S-выражением
  python3 main.py prog.funny --desugar    a[i] = v  ->  a = store(a, i, v)
  python3 main.py prog.funny --no-pos     JSON без позиций
  python3 main.py prog.funny --tokens     поток токенов от лексера
  python3 main.py -e 'function f() returns r { }'
  python3 main.py --test                  snapshot-тесты tests/*.funny
  python3 main.py --test -v               то же + ошибки и позиции под каждым тестом
  python3 main.py --test --update         перезаписать эталоны tests/expected/
  python3 main.py --grammar               FIRST/FOLLOW и проверка LL(1)

AST печатается в stdout, ошибки — в stderr в формате
  error: expected ')' but got ';' at 3:15
Код выхода: 0 — ошибок нет, 1 — были ошибки, 2 — неверные аргументы/файл.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

from funny_ast import desugar, to_json, to_sexp
from lexer import Lexer

HERE = Path(__file__).resolve().parent

try:
    from parser import parse
except ImportError:
    # Python 3.8–3.9: встроенный C-модуль `parser` (удалён в 3.10) перекрывает
    # наш parser.py. Загружаем файл явно по пути под другим именем.
    import importlib.util
    _spec = importlib.util.spec_from_file_location("funny_parser", HERE / "parser.py")
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["funny_parser"] = _mod
    _spec.loader.exec_module(_mod)
    parse = _mod.parse
TESTS = HERE / "tests"
EXPECTED = TESTS / "expected"
TIMEOUT = 5.0          # секунд на один тест: дольше — считаем, что парсер завис


# ЭТАП 11.1. Один прогон программы: текст -> (stdout, stderr, ok).
#   1) parse(text) — лексер + парсер (ЭТАПЫ 2, 5–9);
#   2) ошибки есть -> все сообщения в stderr, AST не печатается;
#   3) ошибок нет -> при --desugar переписываем a[i] = v (ЭТАП 10.5),
#      затем выводим JSON (ЭТАП 10.3) или S-выражение (ЭТАП 10.4).
def render(text: str, sexp=False, with_pos=True, sugar_free=False):
    """(stdout, stderr, ok) для программы text."""
    result = parse(text)
    if not result.ok:
        return "", "\n".join(map(str, result.diagnostics)) + "\n", False
    program = desugar(result.program) if sugar_free else result.program
    out = to_sexp(program) if sexp else to_json(program, with_pos)
    return out + "\n", "", True


# ЭТАП 12.1. Snapshot-тесты (слайд «Сравнение AST с эталонным»).
# Для каждой программы tests/*.funny берётся вывод парсера и сравнивается с файлом
# в tests/expected/:
#   pos_*.funny -> должен разобраться без ошибок, вывод = JSON AST, эталон pos_*.json;
#   neg_*.funny -> должны быть ошибки, вывод = текст ошибок, эталон neg_*.err.
# Совпало посимвольно — PASS. Любое изменение AST или сообщений сразу видно.
# --update перезаписывает эталоны (после этого их надо проверить глазами!).
# Каждый тест запускается в отдельном потоке с лимитом TIMEOUT: если парсер
# зациклился на ошибке (штраф −2 на слайде), тест упадёт с «завис», а не повиснет.
def snapshot(path: Path) -> str:
    """Что сравнивается с эталоном: JSON AST или текст ошибок."""
    out, err, _ = render(path.read_text(encoding="utf-8"))
    return out or err


def run_with_timeout(fn, *args):
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("v", fn(*args)), daemon=True)
    t.start()
    t.join(TIMEOUT)
    return box.get("v"), t.is_alive()


STMT_NODES = {"Assign", "If", "While", "Assert", "Assume", "Block"}


def outline(node: dict, depth: int = 0) -> list:
    """Краткая схема AST для --test -v: функции и операторы с позициями.
    pos_06:  function f @1:1 / Assign r @1:27 / Assign a[...] @1:37"""
    kind = node["node"]
    pad = "  " * depth
    if kind == "Program":
        return [line for fn in node["functions"] for line in outline(fn, depth)]
    if kind == "Function":
        return [f"{pad}function {node['name']} @{node['pos']}"] + outline(node["body"], depth + 1)
    if kind == "Block":
        return [line for st in node["stmts"] for line in outline(st, depth)]
    if kind == "Assign":
        t = node["target"]
        name = t["name"] if t["node"] == "Ident" else t["base"]["name"] + "[...]"
        return [f"{pad}Assign {name} @{node['pos']}"]
    lines = [f"{pad}{kind} @{node['pos']}"]
    for key in ("then", "else", "body"):
        if isinstance(node.get(key), dict):
            lines += outline(node[key], depth + 1)
    return lines


def cmd_test(update: bool, verbose: bool = False) -> int:
    files = sorted(TESTS.glob("*.funny"))
    EXPECTED.mkdir(exist_ok=True)
    passed = 0
    for f in files:
        positive = f.name.startswith("pos_")
        exp_file = EXPECTED / (f.stem + (".json" if positive else ".err"))
        got, hung = run_with_timeout(snapshot, f)
        if hung:
            status, note = "FAIL", f"завис дольше {TIMEOUT} с"
        else:
            is_error = not got.lstrip().startswith("{")
            if positive == is_error:
                status = "FAIL"
                note = "ожидался успешный разбор" if positive else "ожидалась ошибка"
            elif update:
                exp_file.write_text(got, encoding="utf-8")
                status, note = "PASS", "эталон обновлён"
            elif not exp_file.exists():
                status, note = "FAIL", f"нет эталона {exp_file.name} (запусти --test --update)"
            elif exp_file.read_text(encoding="utf-8") != got:
                status, note = "FAIL", f"вывод отличается от {exp_file.name}"
            else:
                status = "PASS"
                n_err = got.count("error:")
                word = ("ошибка" if n_err % 10 == 1 and n_err % 100 != 11 else
                        "ошибки" if 2 <= n_err % 10 <= 4 and not 12 <= n_err % 100 <= 14 else "ошибок")
                note = "AST совпал" if positive else f"{n_err} {word}"
        passed += status == "PASS"
        print(f"{status}  {f.name:<38} {note}")
        if status == "FAIL" and not hung:
            print("      " + got.strip().replace("\n", "\n      ")[:600])
        elif verbose and not hung:
            # -v: показать позиции. Негативные — сами ошибки «... at строка:столбец»,
            # позитивные — функции и операторы из AST с их позициями.
            if positive:
                lines = outline(json.loads(got))
            else:
                lines = got.strip().splitlines()
            for line in lines:
                print("        " + line)
    pos = sum(f.name.startswith("pos_") for f in files)
    print(f"\nИТОГО: {passed}/{len(files)} PASS  (позитивных {pos}, негативных {len(files) - pos})")
    return 0 if passed == len(files) else 1


# ЭТАП 11. CLI: разобрать аргументы и запустить нужный режим.
#   файл / -e КОД  -> render() и печать;  --tokens -> только лексер;
#   --test         -> snapshot-тесты;     --grammar -> отчёт ЭТАПА 4.
# Код выхода: 0 — без ошибок, 1 — ошибки в программе, 2 — неверные аргументы/файл.
def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python3 main.py",
                                description="LL(1)-парсер языка Funny (HW2)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("file", nargs="?", help="файл с программой на Funny ('-' — stdin)")
    src.add_argument("-e", "--expr", metavar="CODE", help="текст программы прямо в командной строке")
    src.add_argument("--test", action="store_true", help="прогнать snapshot-тесты из tests/")
    src.add_argument("--grammar", action="store_true", help="FIRST/FOLLOW и проверка LL(1)")
    p.add_argument("--update", action="store_true", help="с --test: перезаписать эталоны")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="с --test: показать ошибки и позиции под каждым тестом")
    p.add_argument("--sexp", action="store_true", help="AST S-выражением вместо JSON")
    p.add_argument("--no-pos", action="store_true", help="JSON без позиций")
    p.add_argument("--desugar", action="store_true", help="a[i] = v -> a = store(a, i, v)")
    p.add_argument("--tokens", action="store_true", help="напечатать токены вместо AST")
    a = p.parse_args(argv)

    if a.test:
        return cmd_test(a.update, a.verbose)
    if a.grammar:
        from ll1 import load_grammar
        g = load_grammar()
        print(g.report())
        return 1 if g.conflicts else 0

    if a.expr is not None:
        text = a.expr
    elif a.file == "-":
        text = sys.stdin.read()
    elif a.file:
        try:
            text = Path(a.file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"error: cannot read {a.file}: {exc}", file=sys.stderr)
            return 2
    else:
        p.print_help()
        return 2

    if a.tokens:
        lexer = Lexer(text)
        for t in lexer.tokens():
            print(f"{t.line:>4}:{t.col:<4} {t.kind:<10} {t.lexeme!r}")
        for d in lexer.diagnostics:
            print(d, file=sys.stderr)
        return 1 if lexer.diagnostics else 0

    out, err, ok = render(text, a.sexp, not a.no_pos, a.desugar)
    sys.stdout.write(out)
    sys.stderr.write(err)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:          # вывод обрезан (| head) — это не ошибка
        sys.exit(0)
