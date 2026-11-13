"""ЭТАП 12.2. Юнит-тесты HW2:  python3 -m unittest test_parser -v

Метки над каждой группой (поиск: Ctrl+Shift+F -> «ТЕСТ»):
  ТЕСТ ГРАММАТИКИ          — LL(1) без конфликтов, примеры FIRST/FOLLOW (ЭТАПЫ 3–4)
  ТЕСТ СООТВЕТСТВИЯ        — рекурсивный спуск = табличный LL(1)-разбор по grammar.txt
  ТЕСТ ГЕНЕРАЦИИ           — программы, выведенные из правил grammar.txt, принимаются
  ТЕСТ УСТОЙЧИВОСТИ        — нет зацикливания, ошибки с разными позициями (ЭТАП 9)
  ТЕСТ AST                 — приоритеты, сахар массивов, JSON, позиции (ЭТАПЫ 8, 10)
  ТЕСТ ЛЕКСЕРА             — позиции токенов, peek, requires/ensures, ловушка (ЭТАПЫ 1–2)

Snapshot-тесты (tests/*.funny против tests/expected/) запускаются отдельно:
python3 main.py --test. Здесь — то, что snapshot не проверяет:
  * грамматика действительно LL(1);
  * парсер (рекурсивный спуск) соответствует grammar.txt: сверка с табличным
    LL(1)-разбором на всех тестах и на тысячах случайно испорченных программ;
  * парсер не зацикливается на мусоре и всегда завершает разбор;
  * приоритеты, позиции, JSON round-trip, десахаризация массивов, лексер.
"""
import random
import time
import unittest
from pathlib import Path

from funny_ast import (ArrayIndex, Assign, BinaryOp, Call, Ident, Int, UnaryOp, desugar,
                       from_dict, to_dict)
from lexer import Lexer
from ll1 import load_grammar
from main import parse          # main.py обходит встроенный модуль parser на Python 3.8–3.9

HERE = Path(__file__).resolve().parent
PROGRAMS = sorted((HERE / "tests").glob("*.funny"))
GRAMMAR = load_grammar()


def table_parse(text):
    """Табличный LL(1)-разбор: None — принято, иначе индекс токена ошибки."""
    kinds = [t.kind for t in Lexer(text).tokens()]
    return GRAMMAR.parse(kinds)


def body(stmt_src: str):
    """AST первого оператора внутри тестовой функции."""
    r = parse(f"function f(a, b, c, d) returns r {{ {stmt_src} }}")
    assert r.ok, r.diagnostics
    return r.program.functions[0].body.stmts[0]


# ТЕСТ ГРАММАТИКИ. Грамматика из grammar.txt действительно LL(1): в таблице M нет
# клеток с двумя правилами. Плюс несколько FIRST/FOLLOW, на которые опирается парсер:
# ';' нет в FOLLOW(stmt) — поэтому она необязательна без конфликта.
class GrammarTests(unittest.TestCase):
    def test_ll1_no_conflicts(self):
        self.assertEqual(GRAMMAR.conflicts, [])

    def test_first_follow_examples(self):
        self.assertEqual(GRAMMAR.first["stmt"], {"IDENT", "IF", "WHILE", "ASSERT", "ASSUME", "{"})
        self.assertEqual(GRAMMAR.follow["stmt"], {"IDENT", "IF", "WHILE", "ASSERT", "ASSUME", "{", "}"})
        self.assertIn("ε", GRAMMAR.first["semi"])
        # ';' не входит в FOLLOW(stmt): поэтому она может быть необязательной
        self.assertNotIn(";", GRAMMAR.follow["stmt"])
        # '(' и '[' не входят в FOLLOW(ident_tail): x = a  и следующий оператор не путаются
        self.assertFalse({"(", "["} & GRAMMAR.follow["ident_tail"])


# ТЕСТ СООТВЕТСТВИЯ (критерий «AST-вывод и соответствие грамматике»).
# Есть два независимых парсера одной грамматики:
#   parser.py — рекурсивный спуск, написанный вручную (ЭТАПЫ 5–9);
#   ll1.py    — табличный разбор по M[A, a], построенной прямо из grammar.txt (ЭТАП 4.5).
# Если на одном и том же входе оба принимают программу или оба останавливаются на
# ОДНОМ И ТОМ ЖЕ токене, значит, рекурсивный спуск реализует ровно grammar.txt.
# Проверяется на всех тестах из tests/ и на 3000 программах, испорченных случайно
# (удалить / вставить / заменить токен).
class AgreementWithGrammar(unittest.TestCase):
    """Рекурсивный спуск ≡ табличный LL(1) по grammar.txt."""

    def check(self, text):
        r = parse(text)
        rd = None if r.first_error_index is None else r.first_error_index
        self.assertEqual(rd, table_parse(text), repr(text))

    def test_all_test_programs(self):
        for f in PROGRAMS:
            with self.subTest(f.name):
                self.check(f.read_text(encoding="utf-8"))

    def test_random_mutations(self):
        rnd = random.Random(2026)
        sources = [f.read_text(encoding="utf-8") for f in PROGRAMS if f.name.startswith("pos_")]
        pieces = ["(", ")", "{", "}", "[", "]", ";", ",", "=", "==", "<", "+", "-", "*",
                  "if", "else", "while", "assert", "assume", "not", "and", "or", "true",
                  "x", "0", "1", "function", "returns", "requires", "ensures", "invariant",
                  "length", "uses", " "]
        for _ in range(3000):
            toks = Lexer(rnd.choice(sources)).tokens()[:-1]
            words = [t.lexeme for t in toks]
            for _ in range(rnd.randint(1, 3)):
                op = rnd.random()
                i = rnd.randrange(len(words) + 1)
                if op < 0.4 and words:
                    del words[min(i, len(words) - 1)]
                elif op < 0.8:
                    words.insert(i, rnd.choice(pieces))
                elif words:
                    words[min(i, len(words) - 1)] = rnd.choice(pieces)
            self.check(" ".join(words))


# ТЕСТ ГЕНЕРАЦИИ. Обратная проверка: строим случайные ПРАВИЛЬНЫЕ программы прямо по
# правилам grammar.txt (начиная с program, раскрываем нетерминалы случайной
# альтернативой) и проверяем, что оба парсера их принимают, а AST переживает
# JSON туда-обратно. Чтобы вывод не рос бесконечно, после глубины 12 берётся самое
# «короткое» правило (с минимальной высотой дерева вывода).
LEXEME = {"IDENT": ["x", "a", "foo_1"], "INT": ["0", "7", "42"]}


def _min_heights():
    """h[A] — минимальная высота дерева вывода из A (неподвижная точка)."""
    inf = float("inf")
    h = {a: inf for a in GRAMMAR.nonterminals}

    def cost(p):
        return 1 + max([h[s] for s in p if not GRAMMAR.is_terminal(s)], default=0)
    changed = True
    while changed:
        changed = False
        for a, prods in GRAMMAR.rules.items():
            best = min(cost(p) for p in prods)
            if best < h[a]:
                h[a], changed = best, True
    return h, cost


HEIGHT, PROD_COST = _min_heights()


def generate(rnd, sym="program", depth=0):
    """Случайный вывод из grammar.txt: список лексем правильной программы."""
    if GRAMMAR.is_terminal(sym):
        if sym == "EOF":
            return []
        if sym in LEXEME:
            return [rnd.choice(LEXEME[sym])]
        return [sym.lower() if sym.isalpha() else sym]
    prods = GRAMMAR.rules[sym]
    if depth > 12:                     # глубоко — правило с минимальной высотой вывода
        prods = [min(prods, key=PROD_COST)]
    prod = rnd.choice(prods)
    out = []
    for s in prod:
        out += generate(rnd, s, depth + 1)
    return out


class GeneratedPrograms(unittest.TestCase):
    def test_programs_derived_from_grammar_are_accepted(self):
        rnd = random.Random(1)
        for _ in range(1500):
            text = " ".join(generate(rnd))
            with self.subTest(text=text[:120]):
                r = parse(text)
                self.assertTrue(r.ok, f"{text}\n{r.diagnostics}")
                self.assertIsNone(table_parse(text))
                self.assertEqual(from_dict(to_dict(r.program)), r.program)


# ТЕСТ УСТОЙЧИВОСТИ (штрафы слайда: зацикливание −2, позиции не обновляются).
#   * 1000 строк случайного мусора — разбор каждой обязан закончиться;
#   * в neg_12 ошибки на 8 разных строках и все позиции разные;
#   * после ошибки в первой функции ошибка во второй тоже находится.
class Robustness(unittest.TestCase):
    def test_no_hang_on_garbage(self):
        rnd = random.Random(7)
        alphabet = list("(){}[];,=<>+-*/!@ \n") + ["if ", "else ", "while ", "function ", "x ", "1 "]
        start = time.perf_counter()
        for _ in range(1000):
            text = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 80)))
            r = parse(text)                       # должен завершиться
            self.assertTrue(r.ok or r.diagnostics)
        self.assertLess(time.perf_counter() - start, 30)

    def test_errors_have_different_positions(self):
        text = (HERE / "tests" / "neg_12_many_errors.funny").read_text(encoding="utf-8")
        diags = parse(text).diagnostics
        self.assertGreaterEqual(len(diags), 6)
        positions = [(d.line, d.col) for d in diags]
        self.assertEqual(len(set(positions)), len(positions))
        self.assertEqual(sorted({d.line for d in diags}), [2, 3, 4, 5, 6, 7, 9, 10])

    def test_recovery_keeps_parsing_after_error(self):
        r = parse("function f() returns r { r = ; }\nfunction g() returns r { r = }")
        self.assertEqual([d.line for d in r.diagnostics], [1, 2])


# ТЕСТ AST. Структура дерева (позиции в сравнении не участвуют):
#   a + b * c -> (+ a (* b c));  a - b - c -> (- (- a b) c);  -a * b -> (* (- a) b);
#   a[b + 1] = c и его десахаризация в a = store(a, b + 1, c);
#   from_dict(to_dict(ast)) == ast;  позиции узлов на многострочной программе.
class AstTests(unittest.TestCase):
    def test_precedence(self):
        s = body("r = a + b * c;")
        self.assertEqual(s.value, BinaryOp("+", Ident("a"), BinaryOp("*", Ident("b"), Ident("c"))))
        s = body("r = a - b - c;")
        self.assertEqual(s.value, BinaryOp("-", BinaryOp("-", Ident("a"), Ident("b")), Ident("c")))
        s = body("r = -a * b;")
        self.assertEqual(s.value, BinaryOp("*", UnaryOp("-", Ident("a")), Ident("b")))
        s = body("assert a or b and not c == d;")
        self.assertEqual(s.expr, BinaryOp("or", Ident("a"), BinaryOp(
            "and", Ident("b"), UnaryOp("not", BinaryOp("==", Ident("c"), Ident("d"))))))

    def test_array_assign_and_desugar(self):
        s = body("a[b + 1] = c;")
        self.assertEqual(s, Assign(ArrayIndex(Ident("a"), BinaryOp("+", Ident("b"), Int(1))), Ident("c")))
        self.assertEqual(desugar(s), Assign(Ident("a"), Call(
            "store", [Ident("a"), BinaryOp("+", Ident("b"), Int(1)), Ident("c")])))

    def test_json_roundtrip(self):
        for f in PROGRAMS:
            r = parse(f.read_text(encoding="utf-8"))
            if r.ok:
                with self.subTest(f.name):
                    self.assertEqual(from_dict(to_dict(r.program)), r.program)

    def test_positions(self):
        r = parse("function f(x) returns r\n{\n  r = x + 1;\n}")
        fn = r.program.functions[0]
        assign = fn.body.stmts[0]
        self.assertEqual(fn.pos, (1, 1))
        self.assertEqual(fn.body.pos, (2, 1))
        self.assertEqual(assign.pos, (3, 3))
        self.assertEqual(assign.value.right.pos, (3, 11))


# ТЕСТ ЛЕКСЕРА. Вид и позиция каждого токена, peek() не продвигает поток, после
# конца всегда EOF, requires/ensures — ключевые слова (а requiresx — IDENT), ловушка
# и комментарии с русскими буквами, dfa.json соответствует funny.lex.
class LexerTests(unittest.TestCase):
    def test_positions_and_kinds(self):
        toks = Lexer("if (x >= 10)\n  r = a[0];").tokens()
        self.assertEqual([(t.kind, t.line, t.col) for t in toks], [
            ("IF", 1, 1), ("(", 1, 4), ("IDENT", 1, 5), (">=", 1, 7), ("INT", 1, 10), (")", 1, 12),
            ("IDENT", 2, 3), ("=", 2, 5), ("IDENT", 2, 7), ("[", 2, 8), ("INT", 2, 9), ("]", 2, 10),
            (";", 2, 11), ("EOF", 2, 12)])

    def test_peek_does_not_advance(self):
        lx = Lexer("function f")
        self.assertEqual(lx.peek().kind, "FUNCTION")
        self.assertEqual(lx.peek().kind, "FUNCTION")
        self.assertEqual(lx.next_token().kind, "FUNCTION")
        self.assertEqual(lx.next_token().lexeme, "f")
        self.assertEqual(lx.next_token().kind, "EOF")
        self.assertEqual(lx.next_token().kind, "EOF")

    def test_keywords_requires_ensures(self):
        kinds = [t.kind for t in Lexer("requires ensures requiresx").tokens()]
        self.assertEqual(kinds, ["REQUIRES", "ENSURES", "IDENT", "EOF"])

    def test_trap_and_comments(self):
        lx = Lexer("x @@ y // комментарий: z = 1\nw")
        self.assertEqual([t.lexeme for t in lx.tokens()], ["x", "y", "w", ""])
        self.assertEqual([str(d) for d in lx.diagnostics], ["error: unexpected characters '@@' at 1:3"])

    def test_dfa_json_matches_funny_lex(self):
        """dfa.json собран из текущего funny.lex (никто не забыл пересобрать)."""
        import json
        from dfa_build import build_funny
        tables, _ = build_funny(HERE / "funny.lex")
        on_disk = json.loads((HERE / "dfa.json").read_text(encoding="utf-8"))
        self.assertEqual(tables, on_disk)


if __name__ == "__main__":
    unittest.main()
