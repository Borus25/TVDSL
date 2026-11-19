"""Лексер Funny (P02): табличный ДКА из HW1 + позиции токенов.

Этапы в этом файле (поиск: Ctrl+Shift+F -> «ЭТАП 2»):
  ЭТАП 2.   Лексер: текст программы -> поток токенов {kind, lexeme, line, col}
  ЭТАП 2.1. Прогон ДКА с самым длинным совпадением (run_dfa, из HW1 без изменений)
  ЭТАП 2.2. Подсчёт позиций line:col
  ЭТАП 2.3. Нарезка одного токена: ловушка, пропуск WS/COMMENT, вид OP-токенов
  ЭТАП 2.4. Интерфейс со слайда: next_token() и peek()
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

HERE = Path(__file__).resolve().parent
DEFAULT_TABLES = HERE / "dfa.json"
EOF = "EOF"


# ЭТАП 2. Лексер: текст -> токены.
# Вход: строка с программой + таблица минимального ДКА dfa.json (собрана в ЭТАПЕ 1).
# Выход: токены по одному, каждый — {kind, lexeme, line, col} (слайд «Интеграция с лексером»).
#
#   kind   — вид токена: ключевые слова FUNCTION, IF, REQUIRES...; IDENT; INT;
#            для операторов и скобок вид = сама лексема: '(', '==', ';' ...;
#            в конце потока — EOF;
#   lexeme — кусок текста, из которого получился токен;
#   line, col — где токен начинается (с 1). Нужны для ошибок: «... at 3:15».
#
# Пример: "function f(x) returns r { r = x + 1; }"
#   FUNCTION 'function' 1:1 | IDENT 'f' 1:10 | '(' 1:11 | IDENT 'x' 1:12 | ')' 1:13
#   RETURNS 1:15 | IDENT 'r' 1:23 | '{' 1:25 | IDENT 'r' 1:27 | '=' 1:29 | IDENT 'x' 1:31
#   '+' 1:33 | INT '1' 1:35 | ';' 1:36 | '}' 1:38 | EOF 1:39
# (пробелы распознаются как WS, но не выдаются — поэтому их в списке нет).
@dataclass(frozen=True)
class Token:
    kind: str       # FUNCTION, IDENT, INT, '(' , '==', ..., EOF
    lexeme: str
    line: int
    col: int

    def to_dict(self) -> dict:
        return {"kind": self.kind, "lexeme": self.lexeme, "line": self.line, "col": self.col}


# Одна ошибка (и лексера, и парсера — у них общий список).
# Печатается в формате слайда: error: expected ')' but got ';' at 3:15 (пояснение)
@dataclass(frozen=True)
class Diagnostic:
    line: int
    col: int
    message: str
    note: str = ""          # пояснение, печатается после позиции

    def __str__(self) -> str:
        tail = f" ({self.note})" if self.note else ""
        return f"error: {self.message} at {self.line}:{self.col}{tail}"


def describe(tok: Token) -> str:
    """Как токен показывается в сообщении об ошибке."""
    if tok.kind == EOF:
        return "end of input"
    return f"'{tok.lexeme}'"


class Lexer:
    def __init__(self, text: str, tables: Optional[dict] = None,
                 diagnostics: Optional[List[Diagnostic]] = None):
        # Таблица ДКА из dfa.json (формат HW1):
        #   char_class[код]   — номер класса символов (столбец таблицы) для ASCII-кода;
        #   other_class       — класс для любого символа вне ASCII;
        #   transitions[s][c] — куда идти из состояния s по классу c;
        #   accept[s]         — какой токен принимает состояние s (или None);
        #   trap              — ловушка: из неё выхода нет, токена тоже.
        if tables is None:
            tables = load_tables()
        self.char_class: List[int] = tables["char_class"]
        self.other_class: int = tables["other_class"]
        self.trans: List[List[int]] = tables["transitions"]
        self.start: int = tables["start"]
        self.trap: int = tables["trap"]
        self.accept: List[Optional[str]] = tables["accept"]
        self.kind = {t["name"]: t["kind"] for t in tables["tokens"]}

        self.text = text
        self.pos = 0            # индекс текущего символа в тексте
        self.line = 1           # ЭТАП 2.2: строка и столбец этого символа
        self.col = 1
        self.diagnostics: List[Diagnostic] = [] if diagnostics is None else diagnostics
        self._peeked: Optional[Token] = None   # ЭТАП 2.4: токен, на который уже посмотрели

    def _class(self, ch: str) -> int:
        c = ord(ch)
        return self.char_class[c] if c < len(self.char_class) else self.other_class

    # ЭТАП 2.1. Прогон ДКА с самым длинным совпадением (maximal munch) — код HW1.
    # Идём по таблице от позиции pos символ за символом и запоминаем ПОСЛЕДНЕЕ
    # принимающее состояние. Упёрлись в ловушку (или конец текста) — возвращаем
    # последний запомненный, то есть самый длинный токен.
    # Поэтому '>=' — один токен, а не '>' и '=', а 'iff' — IDENT, а не IF + 'f'.
    # При равной длине побеждает токен, записанный в funny.lex выше: 'if' -> IF, не IDENT.
    # Если принимающего состояния не было вообще — возвращаем None (символ-ловушка).
    def run_dfa(self, text: str, pos: int) -> Tuple[Optional[str], int]:
        """Самый длинный токен, начинающийся с pos: (имя | None, конец)."""
        state, best, end = self.start, None, pos
        for i in range(pos, len(text)):
            state = self.trans[state][self._class(text[i])]
            if state == self.trap:
                break
            if self.accept[state] is not None:
                best, end = self.accept[state], i + 1
        return best, end

    # ЭТАП 2.2. Позиции. Сдвигаемся до end и пересчитываем line/col по пройденным
    # символам: '\n' — новая строка, столбец снова 1; любой другой символ — col + 1.
    # Столбец считается в символах, а не в байтах (русская буква — один столбец).
    # '\r' из CRLF просто +1 к столбцу, но потом '\n' всё равно переводит строку,
    # поэтому файлы с Windows-переводами строк дают те же номера строк.
    def _advance(self, end: int) -> None:
        for ch in self.text[self.pos:end]:
            if ch == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
        self.pos = end

    # ЭТАП 2.3. Вырезать следующий токен.
    #   1) запоминаем позицию начала (line, col) — она и станет позицией токена;
    #   2) run_dfa находит самый длинный токен;
    #   3) не нашёл (ловушка) — это лексическая ошибка: символ вроде '@', '&' или
    #      русская буква вне комментария. Подряд идущие плохие символы ('&&')
    #      объединяются в ОДНУ ошибку, пропускаются, и лексер продолжает — парсер
    #      их не видит;
    #   4) WS и COMMENT (в funny.lex помечены @skip) распознаются, но не выдаются;
    #   5) у токена OP вид заменяется на саму лексему: OP '(' -> вид '('.
    #      Так парсер пишет expect('('), как в демо со слайда;
    #   6) текст кончился — выдаём EOF (позиция — сразу после последнего символа).
    def _scan(self) -> Token:
        while self.pos < len(self.text):
            line, col = self.line, self.col
            name, end = self.run_dfa(self.text, self.pos)
            if name is None:                       # ловушка: пропустить символы
                stop = self.pos + 1                # подряд идущие — одна ошибка
                while stop < len(self.text) and self.run_dfa(self.text, stop)[0] is None:
                    stop += 1
                bad = self.text[self.pos:stop]
                shown = "".join(c if c.isprintable() else f"\\u{ord(c):04x}" for c in bad)
                what = "character" if len(bad) == 1 else "characters"
                self.diagnostics.append(Diagnostic(line, col, f"unexpected {what} '{shown}'"))
                self._advance(stop)
                continue
            if name == "COMMENT":
                # Регулярка COMMENT из HW1 ASCII-only и обрывается на русской букве.
                # В P02 комментарий всегда тянется до конца строки.
                while end < len(self.text) and self.text[end] not in "\r\n":
                    end += 1
            lexeme = self.text[self.pos:end]
            self._advance(end)
            if self.kind[name] == "skip":          # WS, COMMENT
                continue
            kind = lexeme if name == "OP" else name
            return Token(kind, lexeme, line, col)
        return Token(EOF, "", self.line, self.col)

    # ЭТАП 2.4. Интерфейс со слайда «Интеграция с лексером».
    #   next_token() — отдать следующий токен и продвинуться;
    #   peek()       — посмотреть на следующий токен, НЕ продвигаясь.
    # peek() один раз вырезает токен и кладёт его в _peeked; следующий next_token()
    # отдаёт именно его, а не режет текст заново. После конца текста оба метода
    # всегда возвращают EOF — парсер не может «уехать» за конец ввода.
    def next_token(self) -> Token:
        """Возвращает {kind, lexeme, line, col} и продвигается дальше."""
        if self._peeked is not None:
            tok, self._peeked = self._peeked, None
            return tok
        return self._scan()

    def peek(self) -> Token:
        """Смотрит на следующий токен без продвижения."""
        if self._peeked is None:
            self._peeked = self._scan()
        return self._peeked

    def tokens(self) -> List[Token]:
        """Весь поток до EOF включительно (для --tokens и тестов)."""
        out = []
        while True:
            tok = self.next_token()
            out.append(tok)
            if tok.kind == EOF:
                return out


_TABLE_CACHE: dict = {}


def load_tables(path=DEFAULT_TABLES) -> dict:
    """Прочитать dfa.json один раз и дальше брать из кэша."""
    key = str(path)
    if key not in _TABLE_CACHE:
        _TABLE_CACHE[key] = json.loads(Path(path).read_text(encoding="utf-8"))
    return _TABLE_CACHE[key]
