# -*- coding: utf-8 -*-
"""
Токенизатор на основе построенного (минимизированного) ДКА.
Правило "maximal munch": из текущей позиции берём самое длинное совпадение;
приоритет токена при равной длине уже "зашит" в accepts ДКА (см. build.py).
Символы вне алфавита (код > 127) сразу считаются ошибкой (попадание в
ловушку без обхода автомата).
"""
from .token_specs import SKIP_TOKENS, ALPHABET

_ALPHABET_SET = set(ALPHABET)


class Token:
    def __init__(self, type_, lexeme, start, end):
        self.type = type_
        self.lexeme = lexeme
        self.start = start
        self.end = end

    def __repr__(self):
        return "Token(%s, %r, %d:%d)" % (self.type, self.lexeme, self.start, self.end)

    def to_tuple(self):
        return (self.type, self.lexeme)


class LexError(Exception):
    def __init__(self, position, char):
        self.position = position
        self.char = char
        super().__init__("Lexical error at position %d: unexpected char %r" % (position, char))


def tokenize(dfa, text, include_skipped=False):
    """
    Возвращает (tokens, errors):
      tokens -- список Token (без WS/COMMENT, если include_skipped=False)
      errors -- список (position, char) для символов, на которых не найдено
                ни одного принимающего пути (в т.ч. символы вне алфавита).
    Токенизация не останавливается на первой ошибке: одиночный "плохой"
    символ пропускается и разбор продолжается (типичное поведение лексера).
    """
    tokens = []
    errors = []
    i = 0
    n = len(text)

    while i < n:
        ch0 = text[i]
        if ch0 not in _ALPHABET_SET:
            errors.append((i, ch0))
            i += 1
            continue

        state = dfa.start
        last_accept_pos = None
        last_accept_label = None
        j = i
        while j < n and text[j] in _ALPHABET_SET:
            state = dfa.step(state, text[j])
            j += 1
            if state == dfa.trap_state:
                break
            if state in dfa.accepts:
                last_accept_pos = j
                last_accept_label = dfa.accepts[state]

        if last_accept_pos is None:
            errors.append((i, ch0))
            i += 1
            continue

        lexeme = text[i:last_accept_pos]
        tok = Token(last_accept_label, lexeme, i, last_accept_pos)
        if last_accept_label not in SKIP_TOKENS or include_skipped:
            tokens.append(tok)
        i = last_accept_pos

    return tokens, errors
