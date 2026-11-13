# -*- coding: utf-8 -*-
"""
Спецификация токенов языка Funny (HW1).

Алфавит входа: ASCII 0..127 (символы с кодом > 127 -- вне алфавита, ведут в
ловушку, см. тесты "non_ascii").

Порядок списка задаёт ПРИОРИТЕТ при равной длине совпадения (правило
"maximal munch + первым выигрывает более приоритетный токен", как в
классическом lex/flex): если при максимальной длине совпадения несколько
токенов принимают строку одинаковой длины (например ключевое слово
`function` совпадает и как IDENT, и как литерал `function`), побеждает
токен с МЕНЬШИМ индексом в этом списке. Поэтому ключевые слова перечислены
раньше, чем общее правило IDENT.

SKIP_TOKENS -- типы токенов, которые лексер строит и распознаёт, но не
включает в выходной поток (пробелы, комментарии).
"""

ALPHABET = [chr(c) for c in range(0, 128)]

KEYWORDS = [
    "function", "returns", "uses", "while", "if", "else",
    "assert", "assume", "invariant", "length",
    "true", "false", "not", "and", "or",
]


# Односимвольные разделители/скобки
DELIMS = [
    ("LPAREN", r"\("), ("RPAREN", r"\)"),
    ("LBRACKET", r"\["), ("RBRACKET", r"\]"),
    ("LBRACE", r"\{"), ("RBRACE", r"\}"),
    ("COMMA", r"\,"), ("SEMI", r"\;"),
]

# Операторы (важно: многосимвольные раньше односимвольных с тем же префиксом,
# порядок влияет только на приоритет при РАВНОЙ длине совпадения; т.к.
# maximal munch и так выберет "==" вместо "=" на входе "==", порядок здесь
# для читаемости отчёта не критичен, но соблюдаем "длинные первыми").
OPERATORS = [
    ("EQEQ", r"\=\="),
    ("NEQ", r"\!\="),
    ("LE", r"\<\="),
    ("GE", r"\>\="),
    ("LT", r"\<"),
    ("GT", r"\>"),
    ("ASSIGN", r"\="),
    ("PLUS", r"\+"),
    ("MINUS", r"\-"),
    ("STAR", r"\*"),
    ("SLASH", r"\/"),
]

# Полный упорядоченный список (name, regex)
TOKEN_SPECS = []

for kw in KEYWORDS:
    TOKEN_SPECS.append(("KW_" + kw.upper(), kw))

TOKEN_SPECS.extend(DELIMS)
TOKEN_SPECS.extend(OPERATORS)

TOKEN_SPECS.append(("IDENT", r"[a-zA-Z_][a-zA-Z_0-9]*"))
TOKEN_SPECS.append(("INT", r"0|[1-9][0-9]*"))
TOKEN_SPECS.append(("WS", r"[ \t\r\n]+"))
TOKEN_SPECS.append(("COMMENT", r"\/\/[^\n]*"))

SKIP_TOKENS = {"WS", "COMMENT"}
