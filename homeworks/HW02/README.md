# HW2. Синтаксический анализ Funny: LL(1) + интеграция с лексером

Ветка **LL(1)**: рекурсивный спуск, написанный вручную по LL(1)-грамматике,
режим паники для ошибок, AST в JSON или S-выражениях.
Чистый Python 3.8+ без внешних зависимостей (проверено на 3.8–3.13).

## Структура

```
HW2_Parser/
├── README.md          этот файл
├── REPORT.md          метрики, отклонения от грамматики, ответы на вопросы защиты
├── DEMO.md            шпаргалка: какие команды запускать на защите и что они выведут
├── demo.funny         готовая программа для показа (python3 main.py demo.funny --sexp)
├── grammar.txt        финальная грамматика: EBNF + LL(1)-форма (её читает ll1.py)
├── funny.lex          токены из HW1 + REQUIRES/ENSURES
├── dfa.json           минимальный ДКА лексера (собран из funny.lex)
├── dfa_build.py       конвейер HW1: funny.lex -> НКА -> ДКА -> min ДКА -> dfa.json
├── lexer.py           лексер P02: табличный ДКА HW1 + line/col, next_token()/peek()
├── parser.py          LL(1)-парсер (рекурсивный спуск) + режим паники
├── funny_ast.py       узлы AST, JSON/S-выражения, from_dict, десахаризация a[i] = v
├── ll1.py             FIRST/FOLLOW, таблица M[A, a], проверка LL(1), табличный разбор
├── main.py            CLI
├── test_parser.py     юнит-тесты
└── tests/
    ├── pos_*.funny    16 позитивных программ
    ├── neg_*.funny    20 негативных программ
    └── expected/      эталоны: pos_*.json (AST), neg_*.err (ошибки)
```

## Этапы в коде

Как в HW1, каждая часть программы подписана в коде блоком `# ЭТАП N. …`. В блоке
написано, что этап делает, что получает на вход, что выдаёт, и разобран пример.
Найти все этапы в PyCharm: `Ctrl+Shift+F` → `ЭТАП`. Общая схема
со стрелками лежит в начале `main.py`.

| Этап | Что происходит | Где |
|---|---|---|
| ЭТАП 1 | Таблица лексера: `funny.lex` → НКА → ДКА → min ДКА → `dfa.json` (конвейер HW1) | `dfa_build.py` |
| ЭТАП 2 | Лексер: текст → токены `{kind, lexeme, line, col}`, `next_token()` / `peek()` | `lexer.py` |
| ЭТАП 3 | Грамматика → LL(1)-форма: убрать левую рекурсию, факторизовать | `grammar.txt` |
| ЭТАП 4 | FIRST, FOLLOW, таблица M[A, a], проверка конфликтов, табличный разбор | `ll1.py` |
| ЭТАП 5 | Каркас парсера: один токен вперёд, `advance` / `expect` | `parser.py` |
| ЭТАП 6 | Программа, функция, параметры | `parser.py` |
| ЭТАП 7 | Операторы: блок, присваивание, `if`, `while`, `assert`, `assume` | `parser.py` |
| ЭТАП 8 | Выражения: лесенка приоритетов `ПРИОРИТЕТ 1`–`7` | `parser.py` |
| ЭТАП 9 | Ошибки: режим паники, якоря, защита от зацикливания | `parser.py` |
| ЭТАП 10 | AST: узлы, JSON, S-выражения, сахар `a[i] = v` | `funny_ast.py` |
| ЭТАП 11 | `parse()` и CLI: вывод AST и ошибок | `parser.py`, `main.py` |
| ЭТАП 12 | Тесты: snapshot (`tests/`) и юнит-тесты, метки `ТЕСТ …` | `main.py`, `test_parser.py` |

Другие метки для поиска: `ПРИОРИТЕТ` (уровни операторов), `ЗАЩИТА ОТ ЗАЦИКЛИВАНИЯ`,
`ТЕСТ` (группы юнит-тестов).

## Запуск

```bash
python3 main.py tests/pos_04_if_else.funny          # AST в JSON (с позициями)
python3 main.py tests/pos_04_if_else.funny --sexp   # AST S-выражением
python3 main.py -e 'function f(x) returns r { r = x; }'
python3 main.py prog.funny --desugar                # a[i] = v  ->  a = store(a, i, v)
python3 main.py prog.funny --no-pos                 # JSON без позиций
python3 main.py prog.funny --tokens                 # что отдаёт лексер

python3 main.py --test                  # snapshot-тесты: 36 программ против tests/expected/
python3 main.py --test -v               # то же + под каждым тестом ошибки и позиции
python3 main.py --test --update         # перезаписать эталоны (после осознанных изменений)
python3 -m unittest test_parser -v      # юнит-тесты (17)
python3 main.py --grammar               # FIRST, FOLLOW и проверка LL(1)
python3 dfa_build.py                    # пересобрать dfa.json после правки funny.lex
```

AST печатается в stdout, ошибки — в stderr. Код выхода: 0 — ошибок нет,
1 — есть ошибки, 2 — неверные аргументы или файл не читается.

## Примеры

```
$ python3 main.py -e 'function f(x) returns r { if (x > 0) { r = x; } else { r = 0; } }' --sexp
(program
  (function f (params x) (returns r)
    (block
      (if (> x 0)
        (block
          (= r x))
        (block
          (= r 0))))))
```

```
$ python3 main.py tests/neg_12_many_errors.funny
error: expected expression but got ';' at 2:7
error: expected expression but got ')' at 3:11
error: expected expression but got ';' at 4:23
error: expected expression but got ';' at 5:10
error: expected ')' but got ';' at 6:13
error: expected ']' but got '=' at 7:7
error: expected identifier or ')' but got ',' at 9:12
error: expected expression but got ';' at 10:7
```

Другие сообщения: `unexpected 'else' at 3:3`,
`expected '}' but got end of input at 5:1 (block opened at 2:14)`,
`unexpected '<' at 2:16 (comparisons cannot be chained, use 'and')`,
`unexpected characters '&&' at 3:9` (ошибка лексера).

JSON-вид узла `a[1] = r;` из `tests/pos_06_arrays.funny`
(`"pos"` — где узел начинается, `"строка:столбец"`):

```json
{ "node": "Assign",
  "target": { "node": "ArrayIndex", "base": { "node": "Ident", "name": "a", "pos": "1:37" },
              "index": { "node": "Int", "value": 1, "pos": "1:39" }, "pos": "1:37" },
  "value":  { "node": "Ident", "name": "r", "pos": "1:44" },
  "pos": "1:37" }
```

## API для следующих этапов (T0/T1)

```python
from main import parse                     # (импорт через main работает на любом Python 3.8+)
from funny_ast import to_dict, from_dict, desugar, Function, Assign, ...

r = parse(source)
if r.ok:
    program = r.program                    # funny_ast.Program
else:
    for d in r.diagnostics:                # d.line, d.col, d.message, str(d)
        print(d)

data = to_dict(program)                    # dict для json.dumps
program2 = from_dict(data)                 # обратно в узлы; program2 == program
```

Узлы — ровно список со слайда «AST: что строим»: `Program, Function, Block, Assign,
If, While, Assert, Assume, ArrayIndex, BinaryOp, UnaryOp, Call, Ident, Int, Bool`.
У `While` есть поле `invariant`, у всех узлов — `pos = (line, col)`.

## Лексер (связь с HW1)

`lexer.py` — это лексер из HW1 (табличный ДКА, maximal munch по `dfa.json`,
метод `run_dfa` перенесён без изменений) с тем, что требует HW2:

- позиции `line`, `col` у каждого токена, считаются с 1, столбец — в символах;
- интерфейс со слайда: `next_token()` и `peek()`, в конце поток отдаёт `EOF`;
- у токенов `OP` вид равен лексеме (`'('`, `'=='`, `';'`), поэтому в парсере
  `expect('(')`, как в демо со слайда; ключевые слова — `FUNCTION`, `IF`, …;
- в `funny.lex` добавлены `REQUIRES` и `ENSURES` (в HW1 их не было, а в HW2 они
  нужны), `dfa.json` пересобран тем же конвейером;
- символ, уводящий ДКА в ловушку, превращается в ошибку `unexpected character`
  с позицией, подряд идущие такие символы — в одну ошибку;
- комментарий тянется до конца строки, даже если в нём не-ASCII. В HW1 регулярка
  `//[^\r\n]*` обрывалась на русской букве, и остаток комментария лексировался как код.

Чтобы подключить свой HW1 напрямую: добавь в его `funny.lex` строки
`REQUIRES = requires` и `ENSURES = ensures` выше `IDENT`, собери
`python3 funnylex.py --spec funny.lex build` и положи `build/dfa.json` сюда.
Тест `test_dfa_json_matches_funny_lex` упадёт, если `dfa.json` не соответствует `funny.lex`.

## Почему `funny_ast.py`, а не `ast.py`

В формате сдачи файл назван `ast.py`, но так назвать нельзя: файл рядом с `main.py`
перекрывает стандартный модуль Python `ast`, а его импортирует `dataclasses`
(через `inspect`). Проверено: с `ast.py` программа падает при запуске на Python
3.9–3.12 с `AttributeError: partially initialized module 'ast' has no attribute 'NodeVisitor'`.

С `parser.py` похожая история: в Python 3.8–3.9 есть встроенный модуль `parser`,
который перекрывает файл. Тут имя оставлено, а `main.py` в этом случае загружает
`parser.py` явно по пути. Поэтому другим модулям лучше импортировать `parse` из `main`.
