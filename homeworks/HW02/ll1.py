"""ЭТАП 4. LL(1)-анализ грамматики из grammar.txt.

Подэтапы (поиск: Ctrl+Shift+F -> «ЭТАП 4»):
  ЭТАП 4.1. Чтение LL(1)-формы из grammar.txt
  ЭТАП 4.2. FIRST — с каких токенов может начинаться нетерминал
  ЭТАП 4.3. FOLLOW — какие токены могут стоять сразу после нетерминала
  ЭТАП 4.4. Таблица M[A, a] и поиск конфликтов (= проверка, что грамматика LL(1))
  ЭТАП 4.5. Табличный разбор со стеком — алгоритм со слайда «LL(1): что нужно»

Табличный разбор — это независимая реализация той же грамматики.
Тест test_parser.py сравнивает с ним рекурсивный спуск из parser.py:
на одних и тех же входах оба должны либо принять, либо остановиться
на одном и том же токене. Так проверяется «AST/парсер соответствует грамматике».
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

GRAMMAR_FILE = Path(__file__).resolve().parent / "grammar.txt"
EPS = "ε"
END = "EOF"

Production = Tuple[str, ...]


def terminal_kind(sym: str) -> str:
    """'function' -> FUNCTION, '(' -> '(' (так их называет лексер)."""
    text = sym[1:-1]
    return text.upper() if text.isalpha() else text


# ЭТАП 4.1. Чтение грамматики.
# Берём из grammar.txt строки между «### LL1 BEGIN» и «### LL1 END».
# Каждая строка — «A ::= альт1 | альт2 | ...». Терминалы в кавычках переводятся в
# имена токенов, как их выдаёт лексер: 'function' -> FUNCTION, '(' -> '('.
# Пример: stmt ::= IDENT assign_tail semi | if_stmt | ...
#   -> rules["stmt"] = [("IDENT", "assign_tail", "semi"), ("if_stmt",), ...]
# После чтения сразу считаются FIRST, FOLLOW и таблица M.
class Grammar:
    def __init__(self, text: str):
        self.rules: Dict[str, List[Production]] = {}
        self.start: Optional[str] = None
        inside = False
        for raw in text.splitlines():
            line = raw.strip()
            if line == "### LL1 BEGIN":
                inside = True
                continue
            if line == "### LL1 END":
                break
            if not inside or not line:
                continue
            head, body = line.split("::=")
            head = head.strip()
            if self.start is None:
                self.start = head
            for alt in body.split(" | "):
                syms = tuple(self._sym(s) for s in alt.split() if s != EPS)
                self.rules.setdefault(head, []).append(syms)
        self.nonterminals = set(self.rules)
        self.first: Dict[str, Set[str]] = {}
        self.follow: Dict[str, Set[str]] = {}
        self._compute_first()
        self._compute_follow()
        self.table, self.conflicts = self._build_table()

    @staticmethod
    def _sym(s: str) -> str:
        return terminal_kind(s) if s.startswith("'") else s

    def is_terminal(self, s: str) -> bool:
        return s not in self.nonterminals

    # ЭТАП 4.2. FIRST.
    # FIRST(α) — все токены, с которых может начинаться строка, выводимая из α,
    # плюс ε, если α может быть пустой.
    # FIRST цепочки X1 X2 ... : берём FIRST(X1) без ε; если X1 может быть пустым —
    # добавляем FIRST(X2), и так далее; если пустыми могут быть все — добавляем ε.
    # Для нетерминалов считается «до неподвижной точки»: проходим по всем правилам и
    # дополняем множества, пока за проход ничего не изменилось.
    # Пример: FIRST(stmt) = { IDENT, IF, WHILE, ASSERT, ASSUME, '{' },
    #         FIRST(add_tail) = { '+', '-', ε }.
    def first_of(self, seq: Sequence[str]) -> Set[str]:
        """FIRST цепочки; содержит ε, если цепочка выводит пустую."""
        out: Set[str] = set()
        for s in seq:
            f = {s} if self.is_terminal(s) else self.first[s]
            out |= f - {EPS}
            if EPS not in f:
                return out
        out.add(EPS)
        return out

    def _compute_first(self) -> None:
        for a in self.nonterminals:
            self.first[a] = set()
        changed = True
        while changed:
            changed = False
            for a, prods in self.rules.items():
                for p in prods:
                    f = self.first_of(p)
                    if not f <= self.first[a]:
                        self.first[a] |= f
                        changed = True

    # ЭТАП 4.3. FOLLOW.
    # FOLLOW(B) — токены, которые могут стоять сразу после B. Нужен для ε-правил:
    # пустую альтернативу надо выбирать, когда текущий токен — то, что идёт ПОСЛЕ B.
    # Для каждого правила A ::= ... B β:
    #   в FOLLOW(B) добавляем FIRST(β) без ε;
    #   если β может быть пустым — добавляем ещё и FOLLOW(A) (после B идёт то, что после A).
    # Тоже до неподвижной точки.
    # Пример: FOLLOW(params) = { ')' } — пустой список параметров, если дальше ')'.
    #         FOLLOW(stmt) = FIRST(stmt) ∪ { '}' } — в нём нет ';', поэтому ';' может
    #         быть необязательной без конфликта.
    def _compute_follow(self) -> None:
        for a in self.nonterminals:
            self.follow[a] = set()
        changed = True
        while changed:
            changed = False
            for a, prods in self.rules.items():
                for p in prods:
                    for i, b in enumerate(p):
                        if self.is_terminal(b):
                            continue
                        rest = self.first_of(p[i + 1:])
                        add = rest - {EPS}
                        if EPS in rest:
                            add |= self.follow[a]
                        if not add <= self.follow[b]:
                            self.follow[b] |= add
                            changed = True

    # ЭТАП 4.4. Таблица предсказаний M[A, a] и проверка LL(1).
    # Для каждого правила A ::= α:
    #   M[A, a] = α для всех a из FIRST(α) (без ε);
    #   если α может быть пустой — ещё M[A, a] = α для всех a из FOLLOW(A).
    # Если в какую-то клетку попадают ДВА разных правила — это конфликт: по токену a
    # нельзя однозначно выбрать правило, и грамматика не LL(1).
    # У нас: 36 нетерминалов, 74 правила, 255 клеток, 0 конфликтов.
    # Пример клеток: M[add_tail, '+'] = add_op mul_expr add_tail,
    #                M[add_tail, ';'] = ε,   M[stmt, IDENT] = IDENT assign_tail semi.
    def _build_table(self):
        table: Dict[Tuple[str, str], Production] = {}
        conflicts = []
        for a, prods in self.rules.items():
            for p in prods:
                f = self.first_of(p)
                targets = (f - {EPS}) | (self.follow[a] if EPS in f else set())
                for t in targets:
                    if (a, t) in table and table[(a, t)] != p:
                        conflicts.append((a, t, table[(a, t)], p))
                    else:
                        table[(a, t)] = p
        return table, conflicts

    # ЭТАП 4.5. Табличный разбор со стеком (псевдокод со слайда):
    #   stack = [S]; пока стек не пуст: X = pop; a = текущий токен
    #     X терминал:   совпал с a -> съесть a, иначе ошибка;
    #     X нетерминал: правило = M[X, a]; нет правила -> ошибка; иначе push правой части
    #                   в обратном порядке (чтобы первый символ оказался сверху).
    # Это НЕЗАВИСИМАЯ от parser.py реализация той же грамматики. test_parser.py гоняет
    # оба парсера на тысячах программ и проверяет, что они принимают одно и то же
    # и спотыкаются на одном и том же токене. Так доказывается, что рекурсивный спуск
    # соответствует grammar.txt.
    def parse(self, kinds: Sequence[str]) -> Optional[int]:
        """Разбор по таблице M (stack = [$, S]). kinds — виды токенов, последний EOF.
        Возвращает None, если вход принят, иначе индекс токена, где разбор встал."""
        stack = [self.start]
        i = 0
        while stack:
            x = stack.pop()
            a = kinds[i]
            if self.is_terminal(x):
                if x != a:
                    return i
                i += 1
                continue
            prod = self.table.get((x, a))
            if prod is None:
                return i
            stack.extend(reversed(prod))
        return None if i == len(kinds) else i

    # Текстовый отчёт для python3 main.py --grammar: FIRST, FOLLOW, конфликты.
    def report(self) -> str:
        def fmt(s):
            return " ".join(sorted(s, key=lambda t: (t != EPS, t)))
        nts = list(self.rules)
        width = max(map(len, nts))
        lines = [f"Нетерминалов: {len(nts)}, правил: {sum(map(len, self.rules.values()))}, "
                 f"терминалов: {len({t for (_, t) in self.table})}, клеток M: {len(self.table)}", "",
                 "FIRST:"]
        lines += [f"  {a:<{width}}  {{ {fmt(self.first[a])} }}" for a in nts]
        lines += ["", "FOLLOW:"]
        lines += [f"  {a:<{width}}  {{ {fmt(self.follow[a])} }}" for a in nts]
        lines.append("")
        if self.conflicts:
            lines.append(f"КОНФЛИКТЫ LL(1): {len(self.conflicts)}")
            for a, t, p1, p2 in self.conflicts:
                lines.append(f"  M[{a}, {t}]: {' '.join(p1) or EPS}  vs  {' '.join(p2) or EPS}")
        else:
            lines.append("Конфликтов LL(1) нет: для каждого A и терминала a в M[A, a] ровно одно правило.")
        return "\n".join(lines)


_GRAMMAR: Optional[Grammar] = None


def load_grammar() -> Grammar:
    global _GRAMMAR
    if _GRAMMAR is None:
        _GRAMMAR = Grammar(GRAMMAR_FILE.read_text(encoding="utf-8"))
    return _GRAMMAR


if __name__ == "__main__":
    print(load_grammar().report())
