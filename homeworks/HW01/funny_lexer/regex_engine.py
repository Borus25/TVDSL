# -*- coding: utf-8 -*-
"""
Мини-движок регулярных выражений для HW1.

Поддерживаемый синтаксис (достаточный для спецификации токенов Funny):
    a b c ...      -- литеральные символы
    \\x            -- экранирование метасимвола x (например \\+ \\* \\. \\\\ \\n \\t)
    .              -- любой символ алфавита
    (r)            -- группировка
    r1 r2          -- конкатенация (неявная)
    r1|r2          -- альтернатива
    r*             -- звезда Клини (0..inf)
    r+             -- плюс (1..inf)
    r?             -- опционально (0..1)
    [abc], [a-z], [^abc], [a-zA-Z_0-9]  -- классы символов (с диапазонами и отрицанием)

Алфавит по умолчанию -- ASCII 0..127 (см. token_specs.py / ALPHABET).

АСТ строится из узлов:
    ('char', frozenset_of_chars)   -- один символ из множества (лист)
    ('concat', [node, ...])
    ('alt',    [node, ...])
    ('star',   node)
    ('plus',   node)
    ('opt',    node)

Затем АСТ транслируется в NFA по алгоритму Томпсона.
"""

ESCAPES = {
    'n': '\n', 't': '\t', 'r': '\r', '0': '\0',
}


class RegexSyntaxError(Exception):
    pass


class _Parser:
    def __init__(self, pattern, alphabet):
        self.p = pattern
        self.i = 0
        self.n = len(pattern)
        self.alphabet = alphabet

    def peek(self):
        return self.p[self.i] if self.i < self.n else None

    def advance(self):
        c = self.p[self.i]
        self.i += 1
        return c

    def parse(self):
        node = self.parse_alt()
        if self.i != self.n:
            raise RegexSyntaxError(
                "Unexpected char %r at position %d in /%s/" % (self.peek(), self.i, self.p))
        return node

    def parse_alt(self):
        branches = [self.parse_concat()]
        while self.peek() == '|':
            self.advance()
            branches.append(self.parse_concat())
        if len(branches) == 1:
            return branches[0]
        return ('alt', branches)

    def parse_concat(self):
        parts = []
        while self.peek() is not None and self.peek() not in ('|', ')'):
            parts.append(self.parse_repeat())
        if not parts:
            return ('concat', [])  # epsilon
        if len(parts) == 1:
            return parts[0]
        return ('concat', parts)

    def parse_repeat(self):
        atom = self.parse_atom()
        while self.peek() in ('*', '+', '?'):
            op = self.advance()
            if op == '*':
                atom = ('star', atom)
            elif op == '+':
                atom = ('plus', atom)
            else:
                atom = ('opt', atom)
        return atom

    def parse_atom(self):
        c = self.peek()
        if c is None:
            raise RegexSyntaxError("Unexpected end of pattern /%s/" % self.p)
        if c == '(':
            self.advance()
            node = self.parse_alt()
            if self.peek() != ')':
                raise RegexSyntaxError("Expected ')' in /%s/" % self.p)
            self.advance()
            return node
        if c == '[':
            return self.parse_class()
        if c == '.':
            self.advance()
            return ('char', frozenset(self.alphabet))
        if c == '\\':
            self.advance()
            if self.peek() is None:
                raise RegexSyntaxError("Dangling escape in /%s/" % self.p)
            e = self.advance()
            ch = ESCAPES.get(e, e)
            return ('char', frozenset([ch]))
        # literal char
        self.advance()
        return ('char', frozenset([c]))

    def parse_class(self):
        assert self.advance() == '['
        negate = False
        if self.peek() == '^':
            self.advance()
            negate = True
        chars = set()
        first = True
        while self.peek() != ']' or first:
            first = False
            if self.peek() is None:
                raise RegexSyntaxError("Unterminated class in /%s/" % self.p)
            c1 = self._class_char()
            if self.peek() == '-' and self.i + 1 < self.n and self.p[self.i + 1] != ']':
                self.advance()  # '-'
                c2 = self._class_char()
                lo, hi = ord(c1), ord(c2)
                if lo > hi:
                    lo, hi = hi, lo
                for code in range(lo, hi + 1):
                    chars.add(chr(code))
            else:
                chars.add(c1)
        self.advance()  # ']'
        if negate:
            chars = set(self.alphabet) - chars
        return ('char', frozenset(chars))

    def _class_char(self):
        c = self.advance()
        if c == '\\':
            e = self.advance()
            return ESCAPES.get(e, e)
        return c


def parse_regex(pattern, alphabet):
    """Parse pattern string -> AST, validating against given alphabet."""
    ast = _Parser(pattern, alphabet).parse()
    return ast


# ---------------------------------------------------------------------------
# Thompson construction: AST -> NFA fragment
# ---------------------------------------------------------------------------

class NFA:
    """
    Простое NFA-представление.
    states: множество int id
    trans: dict[(state, symbol_or_None)] -> set(state)   (None = epsilon)
    start: int
    accepts: dict[int -> label]  (label произвольный объект, напр. имя токена)
    """
    def __init__(self):
        self._next_id = 0
        self.states = set()
        self.trans = {}
        self.start = None
        self.accepts = {}

    def new_state(self):
        s = self._next_id
        self._next_id += 1
        self.states.add(s)
        return s

    def add_edge(self, s_from, symbol, s_to):
        self.trans.setdefault((s_from, symbol), set()).add(s_to)

    def merge_in(self, other):
        """Merge another NFA's states/edges into self (disjoint ids assumed)."""
        self.states |= other.states
        for k, v in other.trans.items():
            self.trans.setdefault(k, set()).update(v)


class _Fragment:
    """A Thompson fragment: start state and single-out end state (no label)."""
    __slots__ = ('start', 'end')

    def __init__(self, start, end):
        self.start = start
        self.end = end


def thompson_build(ast, nfa):
    """Build a Thompson fragment for `ast` inside `nfa` (adds states/edges), return _Fragment."""
    kind = ast[0]

    if kind == 'char':
        s = nfa.new_state()
        e = nfa.new_state()
        for ch in ast[1]:
            nfa.add_edge(s, ch, e)
        return _Fragment(s, e)

    if kind == 'concat':
        parts = ast[1]
        if not parts:
            s = nfa.new_state()
            e = nfa.new_state()
            nfa.add_edge(s, None, e)
            return _Fragment(s, e)
        frags = [thompson_build(p, nfa) for p in parts]
        for a, b in zip(frags, frags[1:]):
            nfa.add_edge(a.end, None, b.start)
        return _Fragment(frags[0].start, frags[-1].end)

    if kind == 'alt':
        s = nfa.new_state()
        e = nfa.new_state()
        for branch in ast[1]:
            f = thompson_build(branch, nfa)
            nfa.add_edge(s, None, f.start)
            nfa.add_edge(f.end, None, e)
        return _Fragment(s, e)

    if kind == 'star':
        s = nfa.new_state()
        e = nfa.new_state()
        f = thompson_build(ast[1], nfa)
        nfa.add_edge(s, None, f.start)
        nfa.add_edge(s, None, e)
        nfa.add_edge(f.end, None, f.start)
        nfa.add_edge(f.end, None, e)
        return _Fragment(s, e)

    if kind == 'plus':
        f = thompson_build(ast[1], nfa)
        e = nfa.new_state()
        nfa.add_edge(f.end, None, f.start)
        nfa.add_edge(f.end, None, e)
        return _Fragment(f.start, e)

    if kind == 'opt':
        s = nfa.new_state()
        e = nfa.new_state()
        f = thompson_build(ast[1], nfa)
        nfa.add_edge(s, None, f.start)
        nfa.add_edge(s, None, e)
        nfa.add_edge(f.end, None, e)
        return _Fragment(s, e)

    raise ValueError("Unknown AST node kind: %r" % (kind,))


def regex_to_nfa(pattern, alphabet, label):
    """Compile a single regex pattern to a standalone NFA with one accepting label."""
    ast = parse_regex(pattern, alphabet)
    nfa = NFA()
    frag = thompson_build(ast, nfa)
    nfa.start = frag.start
    nfa.accepts[frag.end] = label
    return nfa
