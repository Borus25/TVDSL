"""ЭТАП 1. Таблица лексера: funny.lex -> регулярки -> НКА (Томпсон) -> ДКА (подмножества)
-> минимальный ДКА (Хопкрофт) -> dfa.json.

Подэтапы (поиск: Ctrl+Shift+F -> «ЭТАП 1»):
  ЭТАП 1.1. Регулярка -> AST
  ЭТАП 1.2. AST -> НКА (Томпсон), все токены под общим стартом
  ЭТАП 1.3. НКА -> ДКА (построение подмножеств), ловушка
  ЭТАП 1.4. ДКА -> минимальный ДКА (Хопкрофт)
  ЭТАП 1.5. Чтение funny.lex и запись dfa.json

Это тот же алгоритм и тот же формат dfa.json, что в HW1 (funnylex.py),
собранный в один файл. В HW2 он нужен только для одного: пересобрать
таблицу после того, как в funny.lex добавлены REQUIRES и ENSURES.

    python3 dfa_build.py                # funny.lex -> dfa.json
    python3 dfa_build.py --spec X.lex --out Y.json

Если у тебя под рукой свой HW1, можно собрать им же:
    python3 funnylex.py --spec funny.lex build   и скопировать build/dfa.json сюда.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

ALPHABET_SIZE = 128
ASCII = frozenset(range(ALPHABET_SIZE))
OTHER = ALPHABET_SIZE            # класс «символ вне ASCII»
NUM_SYMBOLS = ALPHABET_SIZE + 1
FORMAT = "funnylex-dfa/1"


# ЭТАП 1. Зачем он в HW2.
# Лексер (ЭТАП 2) работает по готовой таблице dfa.json. В HW2 в язык добавились
# ключевые слова requires/ensures, значит в funny.lex две новые строки, и таблицу
# надо пересобрать — тем же конвейером, что в HW1. Результат:
#   HW1: 20 токенов, НКА 259 -> ДКА 98 -> min ДКА 79
#   HW2: 22 токена,  НКА 289 -> ДКА 110 -> min ДКА 91   (python3 dfa_build.py)
#
# ЭТАП 1.1. Регулярка -> AST.
# Строку вроде [A-Za-z_][A-Za-z0-9_]* разбираем рекурсивным спуском в дерево:
#   ("set", {...})     — один символ из множества (a, [a-z], \d, . — всё в множество кодов)
#   ("cat", A, B)      — сначала A, потом B
#   ("alt", A, B)      — A или B (|)
#   ("star"/"plus"/"opt", A) — A*, A+, A?
#   ("eps",)           — пустая строка
# Пример: IDENT -> ("cat", ("set", буквы_), ("star", ("set", буквы_цифры_))).
class RegexError(ValueError):
    pass


# узлы: ("eps",) ("set", frozenset) ("cat", a, b) ("alt", a, b) ("star"|"plus"|"opt", a)
_DIGITS = frozenset(range(48, 58))
_WORD = _DIGITS | frozenset(range(65, 91)) | frozenset(range(97, 123)) | {95}
_SPACE = frozenset({9, 10, 11, 12, 13, 32})
SIMPLE_ESCAPES = {"n": 10, "t": 9, "r": 13, "f": 12, "v": 11, "0": 0}
CLASS_ESCAPES = {"d": _DIGITS, "D": ASCII - _DIGITS, "w": _WORD,
                 "W": ASCII - _WORD, "s": _SPACE, "S": ASCII - _SPACE}


class _RegexParser:
    """alt := concat ('|' concat)* ; concat := repeat* ;
    repeat := atom ('*'|'+'|'?')* ; atom := '(' alt ')' | '[' class ']' | '.' | '\\' esc | literal"""

    def __init__(self, src: str):
        self.src, self.pos = src, 0

    def error(self, msg):
        raise RegexError(f"{msg} (позиция {self.pos} в {self.src!r})")

    def peek(self):
        return self.src[self.pos] if self.pos < len(self.src) else None

    def next(self):
        ch = self.peek()
        if ch is None:
            self.error("неожиданный конец выражения")
        self.pos += 1
        return ch

    def code(self, ch):
        if ord(ch) >= ALPHABET_SIZE:
            self.error(f"символ {ch!r} вне ASCII")
        return ord(ch)

    def parse(self):
        node = self.alt()
        if self.pos != len(self.src):
            self.error(f"лишний символ {self.peek()!r}")
        return node

    def alt(self):
        node = self.concat()
        while self.peek() == "|":
            self.pos += 1
            node = ("alt", node, self.concat())
        return node

    def concat(self):
        node = None
        while self.peek() is not None and self.peek() not in "|)":
            item = self.repeat()
            node = item if node is None else ("cat", node, item)
        return node if node is not None else ("eps",)

    def repeat(self):
        node = self.atom()
        while self.peek() is not None and self.peek() in "*+?":
            node = ({"*": "star", "+": "plus", "?": "opt"}[self.next()], node)
        return node

    def atom(self):
        ch = self.next()
        if ch == "(":
            node = self.alt()
            if self.peek() != ")":
                self.error("ожидалась ')'")
            self.pos += 1
            return node
        if ch == "[":
            return ("set", self.char_class())
        if ch == ".":
            return ("set", ASCII - {10})
        if ch == "\\":
            return ("set", self.escape())
        if ch in "*+?":
            self.error(f"квантификатор {ch!r} без операнда")
        return ("set", frozenset({self.code(ch)}))

    def escape(self):
        ch = self.next()
        if ch in SIMPLE_ESCAPES:
            return frozenset({SIMPLE_ESCAPES[ch]})
        if ch in CLASS_ESCAPES:
            return CLASS_ESCAPES[ch]
        if ch == "x":
            digits = self.src[self.pos:self.pos + 2]
            try:
                value = int(digits, 16)
            except ValueError:
                value = -1
            if len(digits) != 2 or not 0 <= value < ALPHABET_SIZE:
                self.error("ожидалось \\xHH")
            self.pos += 2
            return frozenset({value})
        return frozenset({self.code(ch)})

    def class_atom(self):
        ch = self.next()
        return self.escape() if ch == "\\" else frozenset({self.code(ch)})

    def char_class(self):
        negate = self.peek() == "^"
        if negate:
            self.pos += 1
        chars, first = set(), True
        while True:
            ch = self.peek()
            if ch is None:
                self.error("незакрытый '['")
            if ch == "]" and not first:
                self.pos += 1
                break
            first = False
            lo = self.class_atom()
            if self.peek() == "-" and self.pos + 1 < len(self.src) and self.src[self.pos + 1] != "]":
                self.pos += 1
                hi = self.class_atom()
                chars.update(range(min(lo), min(hi) + 1))
            else:
                chars |= lo
        return ASCII - chars if negate else frozenset(chars)


def parse_regex(src: str):
    return _RegexParser(src).parse()


# ЭТАП 1.2. AST -> НКА по Томпсону.
# Для каждого узла дерева — готовый кусочек автомата со входом и выходом:
#   символ a : вход --a--> выход
#   A B      : выход A --ε--> вход B
#   A|B      : новый вход --ε--> A и B, их выходы --ε--> новый выход
#   A*       : ε «пропустить A» + ε с конца A обратно в начало «повторить»
# combined_nfa: общий старт с ε-стрелками в начало НКА каждого токена; выход НКА
# токена i помечен номером i (номер = строка в funny.lex = приоритет).
class NFA:
    def __init__(self):
        self.eps: List[List[int]] = []
        self.edge: List[Optional[Tuple[FrozenSet[int], int]]] = []
        self.accept: Dict[int, int] = {}
        self.start = -1

    def add_state(self):
        self.eps.append([])
        self.edge.append(None)
        return len(self.eps) - 1

    def build(self, node) -> Tuple[int, int]:
        kind = node[0]
        if kind == "eps":
            s, f = self.add_state(), self.add_state()
            self.eps[s].append(f)
            return s, f
        if kind == "set":
            s, f = self.add_state(), self.add_state()
            self.edge[s] = (node[1], f)
            return s, f
        if kind == "cat":
            s1, f1 = self.build(node[1])
            s2, f2 = self.build(node[2])
            self.eps[f1].append(s2)
            return s1, f2
        if kind == "alt":
            s, f = self.add_state(), self.add_state()
            s1, f1 = self.build(node[1])
            s2, f2 = self.build(node[2])
            self.eps[s] += [s1, s2]
            self.eps[f1].append(f)
            self.eps[f2].append(f)
            return s, f
        s, f = self.add_state(), self.add_state()          # star / plus / opt
        s1, f1 = self.build(node[1])
        self.eps[s].append(s1)
        if kind != "plus":
            self.eps[s].append(f)
        if kind != "opt":
            self.eps[f1].append(s1)
        self.eps[f1].append(f)
        return s, f


def combined_nfa(asts) -> NFA:
    nfa = NFA()
    nfa.start = nfa.add_state()
    for i, ast in enumerate(asts):
        s, f = nfa.build(ast)
        nfa.eps[nfa.start].append(s)
        nfa.accept[f] = i
    return nfa


def epsilon_closure(nfa: NFA, states) -> FrozenSet[int]:
    seen = set(states)
    stack = list(seen)
    while stack:
        for t in nfa.eps[stack.pop()]:
            if t not in seen:
                seen.add(t)
                stack.append(t)
    return frozenset(seen)


# ЭТАП 1.3. НКА -> ДКА (построение подмножеств).
# Состояние ДКА = МНОЖЕСТВО состояний НКА, где мы можем быть одновременно.
#   старт ДКА = ε-closure(старт НКА);
#   для каждого состояния и символа: ε-closure(move(множество, символ)) — новое состояние,
#   если такого множества ещё не было;
#   пустое множество — ловушка (состояние 1): туда ведут все «невозможные» символы.
# Если в множестве несколько принимающих НКА-состояний (строка 'if' подходит и под IF,
# и под IDENT), берётся токен с меньшим номером — тот, что выше в funny.lex.
def subset_construction(nfa: NFA):
    start = epsilon_closure(nfa, [nfa.start])
    sets = [start, frozenset()]                    # 0 — старт, 1 — ловушка
    index = {start: 0, frozenset(): 1}
    trans = []
    i = 0
    while i < len(sets):
        row = [1] * NUM_SYMBOLS
        moves = [set() for _ in range(ALPHABET_SIZE)]
        for s in sets[i]:
            e = nfa.edge[s]
            if e is not None:
                for c in e[0]:
                    moves[c].add(e[1])
        for c in range(ALPHABET_SIZE):
            if moves[c]:
                u = epsilon_closure(nfa, moves[c])
                if u not in index:
                    index[u] = len(sets)
                    sets.append(u)
                row[c] = index[u]
        trans.append(row)
        i += 1
    accept = {}
    for st, ns in enumerate(sets):
        toks = [nfa.accept[s] for s in ns if s in nfa.accept]
        if toks:
            accept[st] = min(toks)                 # приоритет = порядок в funny.lex
    return {"trans": trans, "start": 0, "trap": 1, "accept": accept}


# ЭТАП 1.4. ДКА -> минимальный ДКА (Хопкрофт).
# 1) Стартовое разбиение: все непринимающие — одна группа, принимающие — отдельная
#    группа на КАЖДЫЙ токен (иначе склеились бы, например, IF и IDENT).
# 2) Если два состояния одной группы по какому-то символу уходят в разные группы —
#    группу дробим. В рабочее множество кладём меньшую половину (отсюда n·log n).
# 3) Когда дробить нечего, каждая группа — одно состояние min-ДКА.
def _reachable(dfa) -> List[int]:
    order, seen = [dfa["start"]], {dfa["start"]}
    q = deque(order)
    while q:
        for t in dfa["trans"][q.popleft()]:
            if t not in seen:
                seen.add(t)
                order.append(t)
                q.append(t)
    return order


def hopcroft_minimize(dfa):
    states = _reachable(dfa)
    groups: Dict[int, set] = {}
    for s in states:
        groups.setdefault(dfa["accept"].get(s, -1), set()).add(s)
    partition = [frozenset(g) for g in groups.values()]
    work = set(partition)
    inv = [dict() for _ in range(NUM_SYMBOLS)]
    for s in states:
        for a, t in enumerate(dfa["trans"][s]):
            inv[a].setdefault(t, []).append(s)
    while work:
        splitter = work.pop()
        for a in range(NUM_SYMBOLS):
            x = set()
            for t in splitter:
                x.update(inv[a].get(t, ()))
            if not x:
                continue
            refined = []
            for y in partition:
                inter = y & x
                if inter and len(inter) < len(y):
                    diff = y - inter
                    refined += [inter, diff]
                    if y in work:
                        work.discard(y)
                        work |= {inter, diff}
                    else:
                        work.add(inter if len(inter) <= len(diff) else diff)
                else:
                    refined.append(y)
            partition = refined
    block_of = {s: i for i, b in enumerate(partition) for s in b}
    rep = {}
    for s, b in block_of.items():
        rep.setdefault(b, s)
    new_id = {block_of[dfa["start"]]: 0}
    q = deque([block_of[dfa["start"]]])
    while q:
        b = q.popleft()
        for t in dfa["trans"][rep[b]]:
            if block_of[t] not in new_id:
                new_id[block_of[t]] = len(new_id)
                q.append(block_of[t])
    trans = [None] * len(new_id)
    accept = {}
    for b, nid in new_id.items():
        trans[nid] = [new_id[block_of[t]] for t in dfa["trans"][rep[b]]]
        if rep[b] in dfa["accept"]:
            accept[nid] = dfa["accept"][rep[b]]
    return {"trans": trans, "start": 0, "trap": new_id[block_of[dfa["trap"]]], "accept": accept}


# ЭТАП 1.5. Чтение funny.lex и экспорт dfa.json (формат HW1).
# Столбцы таблицы сжимаются: символы, по которым все состояния ведут себя одинаково
# (например, все буквы, кроме тех, что в ключевых словах), — один класс.
# В HW2 из 129 символов (128 ASCII + «всё остальное») получается 31 класс.
def load_spec(path) -> List[dict]:
    specs = []
    for lineno, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head, regex = line.split("=", 1)
        words = head.split()
        kind = words[1][1:] if len(words) > 1 else "token"
        specs.append({"name": words[0], "kind": kind, "regex": regex.strip(),
                      "ast": parse_regex(regex.strip())})
    return specs


def to_tables(dfa, specs) -> dict:
    column_id, class_of, n_classes = {}, [], 0
    for a in range(NUM_SYMBOLS):
        col = tuple(row[a] for row in dfa["trans"])
        if col not in column_id:
            column_id[col] = n_classes
            n_classes += 1
        class_of.append(column_id[col])
    first_symbol = {}
    for a, c in enumerate(class_of):
        first_symbol.setdefault(c, a)
    return {
        "format": FORMAT,
        "tokens": [{"name": s["name"], "kind": s["kind"], "regex": s["regex"]} for s in specs],
        "num_states": len(dfa["trans"]),
        "num_classes": n_classes,
        "start": dfa["start"],
        "trap": dfa["trap"],
        "char_class": class_of[:ALPHABET_SIZE],
        "other_class": class_of[OTHER],
        "transitions": [[row[first_symbol[c]] for c in range(n_classes)] for row in dfa["trans"]],
        "accept": [specs[dfa["accept"][s]]["name"] if s in dfa["accept"] else None
                   for s in range(len(dfa["trans"]))],
    }


def build_funny(spec_path):
    specs = load_spec(spec_path)
    nfa = combined_nfa([s["ast"] for s in specs])
    dfa = subset_construction(nfa)
    mdfa = hopcroft_minimize(dfa)
    stats = {"tokens": len(specs), "nfa": len(nfa.eps), "dfa": len(dfa["trans"]),
             "min_dfa": len(mdfa["trans"])}
    return to_tables(mdfa, specs), stats


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description="funny.lex -> dfa.json (конвейер HW1)")
    p.add_argument("--spec", default=str(here / "funny.lex"))
    p.add_argument("--out", default=str(here / "dfa.json"))
    a = p.parse_args(argv)
    tables, st = build_funny(a.spec)
    Path(a.out).write_text(json.dumps(tables, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"токенов {st['tokens']}: НКА {st['nfa']} -> ДКА {st['dfa']} (с ловушкой) "
          f"-> min ДКА {st['min_dfa']}; классов символов {tables['num_classes']}; -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
