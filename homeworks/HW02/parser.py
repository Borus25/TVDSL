"""LL(1)-парсер Funny: рекурсивный спуск + режим паники.

Этапы в этом файле (поиск в PyCharm: Ctrl+Shift+F -> «ЭТАП»):
  ЭТАП 5. Каркас парсера: один токен впереди, expect / advance
  ЭТАП 6. Программа и функция
  ЭТАП 7. Операторы: block, stmt, присваивание, if, while
  ЭТАП 8. Выражения и приоритеты операторов
  ЭТАП 9. Обработка ошибок: режим паники (якоря, точки восстановления, защита от зацикливания)
  ЭТАП 11 (часть). parse() — склейка лексера и парсера
Этапы 1–4 — в dfa_build.py, lexer.py, grammar.txt, ll1.py; этап 10 — funny_ast.py;
этапы 11–12 — main.py и test_parser.py.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from funny_ast import (ArrayIndex, Assert, Assign, Assume, BinaryOp, Block, Bool, Call,
                       Function, Ident, If, Int, Program, UnaryOp, While)
from lexer import EOF, Diagnostic, Lexer, Token, describe

# ПРИОРИТЕТ: какие токены — операторы какого уровня (см. ЭТАП 8).
CMP_OPS = {"==", "!=", "<", "<=", ">", ">="}
ADD_OPS = {"+", "-"}
MUL_OPS = {"*", "/"}

# ЭТАП 9 (якоря). Синхронизирующие множества для режима паники.
# Идея со слайда: при ошибке пропускаем токены, пока не встретим «якорь» —
# токен, после которого можно спокойно продолжить разбор. Якоря берутся из
# FOLLOW того нетерминала, который сломался, плюс ';' и '}' (слайд:
# sync = FOLLOW(A) ∪ {";", "}"}).
#
#   FIRST(stmt)  = { IDENT, if, while, assert, assume, '{' } — с чего начинается оператор;
#   FOLLOW(stmt) = FIRST(stmt) ∪ { '}' } — что может стоять сразу после оператора.
#   (Числа посчитаны ll1.py по grammar.txt: python3 main.py --grammar.)
STMT_START = {"IDENT", "IF", "WHILE", "ASSERT", "ASSUME", "{"}
STMT_FOLLOW = STMT_START | {"}"}
# Якоря для оператора: FOLLOW(stmt) ∪ {';', '}'} ∪ {function, EOF}.
# IDENT из FOLLOW(stmt) сюда сознательно НЕ входит: идентификаторы стоят и внутри
# сломанного выражения (r = x @ y + z;), и если остановиться на 'y', парсер решит,
# что началось присваивание y = ..., и выдаст ещё пачку ложных ошибок.
STMT_SYNC = {";", "}", "IF", "WHILE", "ASSERT", "ASSUME", "{", "FUNCTION", EOF}
# Якоря для условия ( ... ) у if/while: закрывающая скобка или начало тела.
COND_SYNC = {")", "{", ";", "}", "FUNCTION", EOF}
# Якоря для заголовка функции: начало тела или следующая функция.
HEADER_SYNC = {"{", "FUNCTION", EOF}
# Где кончается цикл разбора операторов в блоке.
BLOCK_END = {"}", "FUNCTION", EOF}


class SyntaxErr(Exception):
    """Внутренний сигнал «ошибка уже записана, восстанавливайся»."""


def kind_name(kind: str) -> str:
    """Как вид токена показывается в «expected ...»."""
    if kind == "IDENT":
        return "identifier"
    if kind == "INT":
        return "integer"
    if kind == EOF:
        return "end of input"
    if kind.isalpha():                  # ключевое слово: FUNCTION -> 'function'
        return f"'{kind.lower()}'"
    return f"'{kind}'"


# ЭТАП 5. Каркас парсера (слайд «Демо: LL-парсер на Python»).
# Вход: лексер (ЭТАП 2), который по одному выдаёт токены {kind, lexeme, line, col}.
# Выход: AST (ЭТАП 10) + список ошибок с позициями.
#
# Главная идея LL(1): парсер всегда держит ОДИН текущий токен self.tok
# («смотрит на один токен вперёд» — это и есть «1» в LL(1)) и по нему
# однозначно решает, какое правило грамматики применить. Откатов назад нет.
#
# Каждый метод parse_X — это нетерминал X из grammar.txt (часть 2), а его тело —
# правая часть правила, прочитанная слева направо:
#   * терминал в правиле  -> self.expect('(')  — «здесь обязан быть такой токен»;
#   * нетерминал          -> вызов self.parse_Y();
#   * выбор A ::= α | β   -> if по self.tok.kind (какой альтернативе он входит в FIRST);
#   * хвост  A_tail ::= op B A_tail | ε  -> цикл while (то же самое, только без рекурсии).
#
# Пример: function f(x) returns r { r = x + 1; }
# лексер отдаёт FUNCTION@1:1 IDENT(f)@1:10 '('@1:11 IDENT(x)@1:12 ')'@1:13
# RETURNS@1:15 IDENT(r)@1:23 '{'@1:25 IDENT(r)@1:27 '='@1:29 IDENT(x)@1:31
# '+'@1:33 INT(1)@1:35 ';'@1:36 '}'@1:38 EOF@1:39,
# а парсер строит (program (function f (params x) (returns r) (block (= r (+ x 1))))).
class Parser:
    def __init__(self, lexer: Lexer):
        self.lex = lexer
        self.diagnostics: List[Diagnostic] = lexer.diagnostics   # общий список с лексером
        self.syntax_errors = 0
        self.first_error_index: Optional[int] = None   # номер токена первой синт. ошибки
        self.index = 0                                 # сколько токенов уже съедено
        self.tok: Token = self.lex.next_token()        # тот самый «один токен вперёд»

    # ЭТАП 5.1. Утилиты чтения токенов.
    #   advance()  — съесть текущий токен и взять следующий у лексера (EOF не съедается,
    #                поэтому дальше конца ввода уйти нельзя);
    #   at(...)    — текущий токен одного из видов? (подглядывание без продвижения);
    #   expect(k)  — «здесь по грамматике обязан быть k»: если да — съесть и вернуть,
    #                если нет — ошибка «expected k but got ...» с позицией текущего токена.
    def advance(self) -> Token:
        tok = self.tok
        if tok.kind != EOF:
            self.tok = self.lex.next_token()
            self.index += 1
        return tok

    def at(self, *kinds: str) -> bool:
        return self.tok.kind in kinds

    # ЭТАП 9.1. Сообщение об ошибке.
    # Формат со слайда: error: expected ')' but got ';' at 3:15 — позиция берётся
    # у токена, на котором споткнулись, поэтому у каждой ошибки своя позиция.
    # Если вторая ошибка пришлась ровно на ту же позицию, что и предыдущая, — это
    # каскад от первой (например, expected ')' и тут же expected '{' на том же токене),
    # её не печатаем, чтобы не засорять вывод.
    def report(self, message: str, tok: Optional[Token] = None, note: str = "") -> None:
        tok = tok or self.tok
        if self.first_error_index is None:
            self.first_error_index = self.index
        last = self._last_syntax_pos
        if last == (tok.line, tok.col):        # вторая ошибка в той же точке — каскад, молчим
            return
        self._last_syntax_pos = (tok.line, tok.col)
        self.syntax_errors += 1
        self.diagnostics.append(Diagnostic(tok.line, tok.col, message, note))

    _last_syntax_pos: Optional[Tuple[int, int]] = None

    # ЭТАП 9.2. error() = report() + исключение SyntaxErr.
    # Исключение «выбрасывает» нас из глубины разбора (например, из parse_primary
    # внутри выражения внутри присваивания) вверх, до ближайшей точки
    # восстановления (ЭТАП 9.3–9.6), которая его ловит (try/except SyntaxErr).
    def error(self, message: str, tok: Optional[Token] = None, note: str = ""):
        self.report(message, tok, note)
        raise SyntaxErr()

    def expect(self, kind: str) -> Token:
        if self.tok.kind != kind:
            self.error(f"expected {kind_name(kind)} but got {describe(self.tok)}")
        return self.advance()

    # ЭТАП 9 (сердце паники). Пропуск токенов до якоря — функция error_recover со слайда:
    #   while peek() not in sync and not eof(): next_token()
    # Цикл всегда кончается: в каждом множестве якорей есть EOF, а advance() двигает
    # вход вперёд, пока не дойдёт до EOF.
    def skip_until(self, sync) -> None:
        while self.tok.kind not in sync:
            self.advance()

    @staticmethod
    def pos(tok: Token) -> Tuple[int, int]:
        return (tok.line, tok.col)

    # ЭТАП 6. Программа и функция.
    # program  ::= function functions EOF      (одна или больше функций, потом конец ввода)
    # function ::= 'function' IDENT '(' params ')' 'returns' IDENT requires ensures block
    #
    # parse_program крутит цикл «пока не EOF: разобрать функцию». Если на верхнем
    # уровне стоит не 'function' (лишние токены: `{ } extra`), это ошибка
    # «unexpected 'extra'», и токены пропускаются до следующего 'function' или конца.
    # Пустой ввод — тоже ошибка (на слайде он в негативных тестах).
    def parse_program(self) -> Program:
        """program ::= function functions EOF"""
        functions = []
        if self.at(EOF):
            self.report("expected 'function' but got end of input", note="empty program")
        while not self.at(EOF):
            if self.at("FUNCTION"):
                fn = self.parse_function()
                if fn is not None:
                    functions.append(fn)
            else:
                # ЭТАП 9.6. Паника на верхнем уровне: якоря — 'function' и EOF.
                self.report(f"unexpected {describe(self.tok)}, expected 'function' or end of input")
                self.advance()
                self.skip_until({"FUNCTION", EOF})
        return Program(functions)

    # ЭТАП 6.1. Функция — почти слово в слово демо со слайда.
    # Заголовок читается строго по порядку правила: function, имя, '(', параметры, ')',
    # returns, имя результата. requires и ensures необязательны: в LL(1)-форме это
    # requires ::= 'requires' expr | ε, а в коде — просто if по текущему токену.
    # Пример: function f(x) returns r requires x > 0 { ... }
    #   -> Function(name='f', params=['x'], returns='r', requires=(> x 0), ensures=None, body=...)
    def parse_function(self) -> Optional[Function]:
        """function ::= 'function' IDENT '(' params ')' 'returns' IDENT requires ensures block"""
        start = self.tok
        try:
            self.expect("FUNCTION")
            name = self.expect("IDENT").lexeme
            self.expect("(")
            params = self.parse_params()
            if not params and not self.at(")"):
                self.error(f"expected identifier or ')' but got {describe(self.tok)}")
            self.expect(")")
            self.expect("RETURNS")
            ret = self.expect("IDENT").lexeme
            requires = ensures = None
            if self.at("REQUIRES"):
                self.advance()
                requires = self.parse_expr()
            if self.at("ENSURES"):
                self.advance()
                ensures = self.parse_expr()
        except SyntaxErr:
            # ЭТАП 9.5. Паника в заголовке функции: пропускаем до '{' (начало тела)
            # или до следующей 'function'. Тело всё равно разбираем — чтобы найти
            # ошибки и в нём (тест neg_16: ошибка в заголовке И отдельная в теле).
            self.skip_until(HEADER_SYNC)
            if self.at("{"):
                self.parse_block()
            return None
        try:
            body = self.parse_block()
        except SyntaxErr:                      # нет '{' после заголовка
            self.skip_until(HEADER_SYNC)
            if self.at("{"):
                self.parse_block()
            return None
        return Function(name, params, ret, requires, ensures, body, pos=self.pos(start))

    # ЭТАП 6.2. Параметры: params ::= IDENT params_tail | ε ; params_tail ::= ',' IDENT params_tail | ε
    # Пустой список, если сразу ')'. Иначе имя, затем цикл «пока ',' — ещё имя».
    # После списка обязана быть ')': иначе ошибка «expected ',' or ')'».
    def parse_params(self) -> List[str]:
        """params ::= IDENT params_tail | ε ;  params_tail ::= ',' IDENT params_tail | ε"""
        params = []
        if self.at("IDENT"):
            params.append(self.advance().lexeme)
            while self.at(","):
                self.advance()
                params.append(self.expect("IDENT").lexeme)
            if not self.at(")"):
                self.error(f"expected ',' or ')' but got {describe(self.tok)}")
        return params

    # ЭТАП 7. Операторы.
    # block ::= '{' stmts '}'   stmts ::= stmt stmts | ε
    # stmt  ::= IDENT assign_tail semi | if_stmt | while_stmt
    #         | 'assert' expr semi | 'assume' expr semi | block
    #
    # ЭТАП 7.1. Блок: съесть '{', затем крутить цикл «разобрать оператор», пока не
    # встретится '}' (или function / EOF — значит '}' забыли). Это нетерминал stmts:
    # stmts ::= stmt stmts | ε — ε выбирается, когда текущий токен в FOLLOW(stmts) = {'}'}.
    #
    # ЭТАП 9.3. Это же главная точка восстановления: если оператор сломался
    # (SyntaxErr), паника пропускает токены до якоря (recover_stmt), и цикл
    # продолжает со следующего оператора. Так за один проход находятся все ошибки:
    # в tests/neg_12_many_errors 8 ошибок на 8 разных строках.
    #
    # ЗАЩИТА ОТ ЗАЦИКЛИВАНИЯ (штраф −2 на слайде). Если после восстановления
    # не съеден ни один токен с начала оператора, один токен выбрасывается
    # принудительно. Значит, каждая итерация цикла двигает вход вперёд хотя бы на
    # один токен, а токенов конечное число — цикл обязательно закончится.
    def parse_block(self) -> Block:
        """block ::= '{' stmts '}'"""
        lbrace = self.expect("{")
        stmts = []
        while not self.at(*BLOCK_END):
            before = self.index
            try:
                stmts.append(self.parse_stmt())
            except SyntaxErr:
                self.recover_stmt()
                if self.index == before and not self.at(*BLOCK_END):
                    self.advance()             # страховка от зацикливания
        if self.at("}"):
            self.advance()
        else:
            # '}' не нашлась: сообщаем, где был открыт блок — так проще найти пару.
            self.report(f"expected '}}' but got {describe(self.tok)}",
                        note=f"block opened at {lbrace.line}:{lbrace.col}")
        return Block(stmts, pos=self.pos(lbrace))

    # ЭТАП 9.3 (продолжение). Паника на уровне оператора — ровно error_recover со слайда:
    # пропустить до якоря из STMT_SYNC, и если якорь — ';', съесть её.
    # Пример: `r = ; x = 1;` -> ошибка на ';', она съедается, дальше разбирается x = 1.
    def recover_stmt(self) -> None:
        """Паника на уровне оператора: до якоря, ';' съедаем."""
        self.skip_until(STMT_SYNC)
        if self.at(";"):
            self.advance()

    # ЭТАП 7.2. Конец простого оператора: semi ::= ';' | ε.
    # ';' необязательна (грамматика слайда её не содержит, а тесты слайда пишут).
    # LL(1) это не ломает: ';' нет в FOLLOW(stmt), поэтому «есть ';'» и «нет ';'»
    # различаются по одному токену. Но если после оператора стоит что-то, с чего
    # оператор начаться не может (`r = x )`), — это ошибка «expected ';'».
    def end_simple_stmt(self) -> None:
        """semi ::= ';' | ε. Если дальше не ';' и не начало следующего
        оператора / '}', то оператор не закончен — это ошибка."""
        if self.at(";"):
            self.advance()
        elif self.at("FUNCTION", EOF):
            # Конец файла / новая функция прямо после оператора: проблема не в ';',
            # а в незакрытом блоке. Не ругаемся здесь — parse_block скажет
            # «expected '}' ... (block opened at ...)», это точнее.
            return
        elif not self.at(*STMT_FOLLOW):
            self.error(f"expected ';' but got {describe(self.tok)}")

    # ЭТАП 7.3. Выбор оператора по одному токену — так работает таблица M[stmt, a]:
    #   IDENT  -> присваивание      if     -> if_stmt      while -> while_stmt
    #   assert -> Assert            assume -> Assume       '{'   -> вложенный блок
    # Любой другой токен (например, 'else' без if) — «unexpected 'else'».
    def parse_stmt(self):
        """stmt ::= IDENT assign_tail semi | if_stmt | while_stmt
                  | 'assert' expr semi | 'assume' expr semi | block"""
        tok = self.tok
        if tok.kind == "IDENT":
            return self.parse_assign()
        if tok.kind == "IF":
            return self.parse_if()
        if tok.kind == "WHILE":
            return self.parse_while()
        if tok.kind in ("ASSERT", "ASSUME"):
            self.advance()
            expr = self.parse_expr()
            self.end_simple_stmt()
            return (Assert if tok.kind == "ASSERT" else Assume)(expr, pos=self.pos(tok))
        if tok.kind == "{":
            return self.parse_block()
        self.error(f"unexpected {describe(tok)}")

    # ЭТАП 7.4. Присваивание. В исходной грамматике два правила с общим началом:
    #   assign := IDENT "=" expr | IDENT "[" expr "]" "=" expr
    # По одному токену IDENT их не различить — это конфликт LL(1). Поэтому IDENT
    # вынесен за скобку (факторизация):  IDENT assign_tail,
    #   assign_tail ::= '=' expr | '[' expr ']' '=' expr
    # и выбор делается по СЛЕДУЮЩЕМУ токену: '=' или '['.
    # Пример: a[1] = r  ->  Assign(target=ArrayIndex(a, 1), value=r).
    # Сахар a[i] = v -> a = store(a, i, v) делается отдельно, в funny_ast.desugar (ЭТАП 10.5).
    def parse_assign(self) -> Assign:
        """IDENT assign_tail semi ;  assign_tail ::= '=' expr | '[' expr ']' '=' expr"""
        name_tok = self.advance()
        target = Ident(name_tok.lexeme, pos=self.pos(name_tok))
        if self.at("["):
            self.advance()
            index = self.parse_expr()
            self.expect("]")
            target = ArrayIndex(target, index, pos=self.pos(name_tok))
        if not self.at("="):
            hint = "assignment is '='" if self.at("==") else ""
            self.error(f"expected '=' but got {describe(self.tok)}", note=hint)
        self.advance()
        value = self.parse_expr()
        self.end_simple_stmt()
        return Assign(target, value, pos=self.pos(name_tok))

    # ЭТАП 9.4. Условие '(' expr ')' у if/while — отдельная точка восстановления.
    # Если в условии ошибка (`if (x > ) {`), пропускаем до ')' или '{', и если
    # дальше начинается тело — разбираем его как обычно. Так ошибка в условии не
    # мешает найти ошибки в теле и в else.
    def parse_cond(self):
        """'(' expr ')' у if/while — со своей точкой восстановления, чтобы ошибка
        в условии не ломала разбор тела и else."""
        try:
            self.expect("(")
            cond = self.parse_expr()
            self.expect(")")
            return cond
        except SyntaxErr:
            self.skip_until(COND_SYNC)
            if self.at(")"):
                self.advance()
            if not self.at("{", "INVARIANT"):
                raise
            return None

    # ЭТАП 7.5. if и while.
    #   if_stmt    ::= 'if' '(' expr ')' block else_part     else_part ::= 'else' block | ε
    #   while_stmt ::= 'while' '(' expr ')' invariant block  invariant ::= 'invariant' expr | ε
    # else и invariant необязательны: смотрим на текущий токен, если это 'else' /
    # 'invariant' — разбираем, иначе ε. Тело — всегда block в фигурных скобках,
    # поэтому проблемы «висячего else» нет: else всегда относится к ближайшему if.
    def parse_if(self) -> If:
        """if_stmt ::= 'if' '(' expr ')' block else_part ;  else_part ::= 'else' block | ε"""
        kw = self.advance()
        cond = self.parse_cond()
        then = self.parse_block()
        else_ = None
        if self.at("ELSE"):
            self.advance()
            else_ = self.parse_block()
        return If(cond, then, else_, pos=self.pos(kw))

    def parse_while(self) -> While:
        """while_stmt ::= 'while' '(' expr ')' invariant block ;  invariant ::= 'invariant' expr | ε"""
        kw = self.advance()
        cond = self.parse_cond()
        invariant = None
        if self.at("INVARIANT"):
            self.advance()
            invariant = self.parse_expr()
        body = self.parse_block()
        return While(cond, body, invariant, pos=self.pos(kw))

    # ЭТАП 8. Выражения и приоритеты операторов.
    # Приоритет задаётся ЛЕСЕНКОЙ методов: чем слабее оператор, тем раньше (выше)
    # его метод. Каждый уровень сначала вызывает следующий, более сильный, — поэтому
    # сильные операторы «склеиваются» первыми и оказываются глубже в дереве.
    #
    #   ПРИОРИТЕТ 1 (слабее всех)  parse_or     or           левоассоциативный
    #   ПРИОРИТЕТ 2                parse_and    and          левоассоциативный
    #   ПРИОРИТЕТ 3                parse_not    not          префиксный, правоассоц.
    #   ПРИОРИТЕТ 4                parse_cmp    == != < <= > >=   неассоциативный
    #   ПРИОРИТЕТ 5                parse_add    + -          левоассоциативный
    #   ПРИОРИТЕТ 6                parse_mul    * /          левоассоциативный
    #   ПРИОРИТЕТ 7 (сильнее всех) parse_unary  унарный -    префиксный, правоассоц.
    #   операнды                   parse_primary  INT true false x a[i] f(..) length(..) (expr)
    #
    # Пример: x + 1 * 2   ->  parse_add берёт x, видит '+', вызывает parse_mul,
    #   а тот целиком забирает 1 * 2  ->  (+ x (* 1 2)).
    # Это та же таблица, что %left/%right на слайде для bison, только «вручную».
    #
    # Левая ассоциативность. Правило add_expr ::= add_expr '+' mul_expr — левая
    # рекурсия, в LL(1) она запрещена (бесконечный цикл). Поэтому в grammar.txt оно
    # переписано хвостом: add_expr ::= mul_expr add_tail, add_tail ::= add_op mul_expr add_tail | ε.
    # В коде хвост — цикл while, и новый узел строится НАД уже собранным левым:
    #   a - b - c  ->  сначала (- a b), потом (- (- a b) c)  — то есть (a - b) - c. ✓
    # Хвост заканчивается (ε), когда текущий токен не '+'/'-' — по таблице M это любой
    # токен из FOLLOW(add_tail): ';', ')', '==', 'and', '}' и т. д.
    def parse_expr(self):
        """expr ::= or_expr"""
        return self.parse_or()

    # ПРИОРИТЕТ 1. or
    def parse_or(self):
        """or_expr ::= and_expr or_tail ;  or_tail ::= 'or' and_expr or_tail | ε"""
        left = self.parse_and()
        while self.at("OR"):
            self.advance()
            left = BinaryOp("or", left, self.parse_and(), pos=left.pos)
        return left

    # ПРИОРИТЕТ 2. and
    def parse_and(self):
        """and_expr ::= not_expr and_tail ;  and_tail ::= 'and' not_expr and_tail | ε"""
        left = self.parse_not()
        while self.at("AND"):
            self.advance()
            left = BinaryOp("and", left, self.parse_not(), pos=left.pos)
        return left

    # ПРИОРИТЕТ 3. not — префиксный: `not not x` -> (not (not x)), рекурсия вправо.
    # Он слабее сравнений: `not a == b` -> (not (== a b)).
    def parse_not(self):
        """not_expr ::= 'not' not_expr | cmp_expr"""
        if self.at("NOT"):
            tok = self.advance()
            return UnaryOp("not", self.parse_not(), pos=self.pos(tok))
        return self.parse_cmp()

    # ПРИОРИТЕТ 4. Сравнения — неассоциативны: правило со знаком ? (не *), поэтому
    # максимум одно сравнение на уровень. `a < b < c` — ошибка с подсказкой про 'and'
    # (на слайде для bison это %nonassoc).
    def parse_cmp(self):
        """cmp_expr ::= add_expr cmp_tail ;  cmp_tail ::= cmp_op add_expr | ε  (неассоциативно)"""
        left = self.parse_add()
        if self.tok.kind in CMP_OPS:
            op = self.advance().kind
            left = BinaryOp(op, left, self.parse_add(), pos=left.pos)
            if self.tok.kind in CMP_OPS:
                self.error(f"unexpected {describe(self.tok)}",
                           note="comparisons cannot be chained, use 'and'")
        return left

    # ПРИОРИТЕТ 5. + и -
    def parse_add(self):
        """add_expr ::= mul_expr add_tail ;  add_tail ::= add_op mul_expr add_tail | ε"""
        left = self.parse_mul()
        while self.tok.kind in ADD_OPS:
            op = self.advance().kind
            left = BinaryOp(op, left, self.parse_mul(), pos=left.pos)
        return left

    # ПРИОРИТЕТ 6. * и /
    def parse_mul(self):
        """mul_expr ::= unary mul_tail ;  mul_tail ::= mul_op unary mul_tail | ε"""
        left = self.parse_unary()
        while self.tok.kind in MUL_OPS:
            op = self.advance().kind
            left = BinaryOp(op, left, self.parse_unary(), pos=left.pos)
        return left

    # ПРИОРИТЕТ 7. Унарный минус — сильнее всех бинарных: `-a * b` -> (* (- a) b).
    def parse_unary(self):
        """unary ::= '-' unary | primary"""
        if self.at("-"):
            tok = self.advance()
            return UnaryOp("-", self.parse_unary(), pos=self.pos(tok))
        return self.parse_primary()

    # ЭТАП 8.1. Операнды (primary) — самый нижний уровень лесенки.
    # Здесь тоже факторизация по IDENT: x, a[i] и f(x, y) начинаются одинаково,
    # поэтому сначала съедаем IDENT, а потом смотрим на следующий токен (ident_tail):
    #   '['  -> ArrayIndex(a, i)      '('  -> Call(f, [args])      иначе -> Ident(x)
    # '(' expr ')' — скобки: возвращаем внутреннее выражение, отдельного узла нет
    # (скобки нужны только для группировки и в AST не попадают).
    # Если ни один вариант не подошёл (`r = ;`) — «expected expression but got ';'».
    def parse_primary(self):
        """primary ::= INT | 'true' | 'false' | IDENT ident_tail
                     | 'length' '(' expr ')' | '(' expr ')'
           ident_tail ::= '[' expr ']' | '(' args ')' | ε"""
        tok = self.tok
        pos = self.pos(tok)
        if tok.kind == "INT":
            self.advance()
            return Int(int(tok.lexeme), pos=pos)
        if tok.kind in ("TRUE", "FALSE"):
            self.advance()
            return Bool(tok.kind == "TRUE", pos=pos)
        if tok.kind == "IDENT":
            self.advance()
            if self.at("["):
                self.advance()
                index = self.parse_expr()
                self.expect("]")
                return ArrayIndex(Ident(tok.lexeme, pos=pos), index, pos=pos)
            if self.at("("):
                self.advance()
                args = self.parse_args()
                self.expect(")")
                return Call(tok.lexeme, args, pos=pos)
            return Ident(tok.lexeme, pos=pos)
        if tok.kind == "LENGTH":
            self.advance()
            self.expect("(")
            arg = self.parse_expr()
            self.expect(")")
            return Call("length", [arg], pos=pos)
        if tok.kind == "(":
            self.advance()
            expr = self.parse_expr()
            self.expect(")")
            return expr
        self.error(f"expected expression but got {describe(tok)}")

    # ЭТАП 8.2. Аргументы вызова: args ::= expr args_tail | ε (пусто, если сразу ')').
    def parse_args(self):
        """args ::= expr args_tail | ε ;  args_tail ::= ',' expr args_tail | ε"""
        args = []
        if not self.at(")"):
            args.append(self.parse_expr())
            while self.at(","):
                self.advance()
                args.append(self.parse_expr())
        return args


class ParseResult:
    def __init__(self, program: Optional[Program], diagnostics: List[Diagnostic],
                 first_error_index: Optional[int]):
        self.program = program
        self.diagnostics = diagnostics
        self.first_error_index = first_error_index

    @property
    def ok(self) -> bool:
        return not self.diagnostics


# ЭТАП 11 (часть). parse() — склейка лексера и парсера в одну функцию.
#   1) Lexer(text) — лексер из ЭТАПА 2, выдаёт токены по одному;
#   2) Parser(lexer).parse_program() — разбор (ЭТАПЫ 5–9);
#   3) ошибки лексера (unexpected character) и парсера лежат в ОДНОМ списке,
#      сортируются по позиции, чтобы печатались в порядке текста;
#   4) AST отдаётся, только если ошибок нет (иначе дерево неполное).
# Это API для следующих этапов курса: from main import parse.
def parse(text: str, tables: Optional[dict] = None) -> ParseResult:
    """Разобрать программу. AST отдаётся только если ошибок нет."""
    lexer = Lexer(text, tables)
    parser = Parser(lexer)
    program = parser.parse_program()
    diags = sorted(lexer.diagnostics, key=lambda d: (d.line, d.col))
    return ParseResult(None if diags else program, diags, parser.first_error_index)
