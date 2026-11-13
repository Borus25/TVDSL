"""ЭТАП 10. AST: узлы дерева и их вывод (JSON и S-выражения).

Подэтапы (поиск: Ctrl+Shift+F -> «ЭТАП 10»):
  ЭТАП 10.1. Узлы выражений
  ЭТАП 10.2. Узлы операторов и верхнего уровня
  ЭТАП 10.3. AST -> JSON и обратно (from_dict)
  ЭТАП 10.4. AST -> S-выражение
  ЭТАП 10.5. Сахар массивов: a[i] = v -> a = store(a, i, v)

Файл назван funny_ast.py, а не ast.py, как в формате сдачи: модуль ast.py
рядом с main.py перекрывает стандартный модуль Python `ast`, а его
импортирует dataclasses (через inspect) — программа падает при старте.
Подробнее в README.

Узлы — ровно список со слайда «AST: что строим». Дополнительно:
  * у каждого узла есть pos = (line, col) — где он начинается в исходнике;
  * у While есть поле invariant (None, если не задан) — см. grammar.txt [Δ3].
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass, replace
from typing import List, Optional, Tuple, Union

Pos = Tuple[int, int]


# ЭТАП 10. Что такое AST и чем он отличается от дерева разбора.
# Парсер (ЭТАПЫ 5–8) проходит по правилам грамматики, но в дерево кладёт только
# СМЫСЛ, без синтаксического шума:
#   * скобки, ';', запятые, ключевые слова в AST не попадают;
#   * вспомогательные нетерминалы LL(1)-формы (*_tail, semi, ident_tail) тоже —
#     цепочка хвостов сворачивается в BinaryOp с нужной ассоциативностью;
#   * каждому «содержательному» правилу — свой узел:
#       if_stmt -> If,  assign -> Assign,  IDENT '[' expr ']' -> ArrayIndex, ...
# Пример: r = (x + 1);  ->  Assign(target=Ident r, value=BinaryOp('+', Ident x, Int 1)),
# скобки и ';' исчезли.
#
# Узлы — ровно список со слайда «AST: что строим» (dataclass на каждый).
# У каждого узла есть pos = (строка, столбец), где он начинается: пригодится
# следующим этапам курса для сообщений об ошибках. pos не участвует в сравнении
# узлов (compare=False), поэтому тесты сравнивают только структуру дерева.
@dataclass
class Node:
    pass


# ЭТАП 10.1. Узлы выражений.
#   Int(5)  Bool(true)  Ident(x)                — листья (primary)
#   ArrayIndex(base=a, index=i)                 — a[i]
#   Call(name='f', args=[...])                  — f(x, y), length(a)
#   UnaryOp(op='-' | 'not', operand)            — -x, not b
#   BinaryOp(op, left, right)                   — x + y, a and b, x < y ...
@dataclass
class Int(Node):
    value: int
    pos: Pos = field(default=(0, 0), compare=False)


@dataclass
class Bool(Node):
    value: bool
    pos: Pos = field(default=(0, 0), compare=False)


@dataclass
class Ident(Node):
    name: str
    pos: Pos = field(default=(0, 0), compare=False)


@dataclass
class ArrayIndex(Node):
    base: "Expr"
    index: "Expr"
    pos: Pos = field(default=(0, 0), compare=False)


@dataclass
class Call(Node):
    name: str
    args: List["Expr"]
    pos: Pos = field(default=(0, 0), compare=False)


@dataclass
class UnaryOp(Node):
    op: str            # '-' | 'not'
    operand: "Expr"
    pos: Pos = field(default=(0, 0), compare=False)


@dataclass
class BinaryOp(Node):
    op: str            # or and == != < <= > >= + - * /
    left: "Expr"
    right: "Expr"
    pos: Pos = field(default=(0, 0), compare=False)


Expr = Union[Int, Bool, Ident, ArrayIndex, Call, UnaryOp, BinaryOp]


# ЭТАП 10.2. Узлы операторов.
#   Block(stmts)                         — { ... }
#   Assign(target, value)                — x = e  или  a[i] = e (target = ArrayIndex)
#   If(cond, then, else_)                — else_ = None, если else нет
#   While(cond, body, invariant)         — invariant = None, если не задан (отклонение Δ3)
#   Assert(expr), Assume(expr)
@dataclass
class Block(Node):
    stmts: List["Stmt"]
    pos: Pos = field(default=(0, 0), compare=False)


@dataclass
class Assign(Node):
    target: Union[Ident, ArrayIndex]
    value: Expr
    pos: Pos = field(default=(0, 0), compare=False)


@dataclass
class If(Node):
    cond: Expr
    then: Block
    else_: Optional[Block] = None
    pos: Pos = field(default=(0, 0), compare=False)


@dataclass
class While(Node):
    cond: Expr
    body: Block
    invariant: Optional[Expr] = None
    pos: Pos = field(default=(0, 0), compare=False)


@dataclass
class Assert(Node):
    expr: Expr
    pos: Pos = field(default=(0, 0), compare=False)


@dataclass
class Assume(Node):
    expr: Expr
    pos: Pos = field(default=(0, 0), compare=False)


Stmt = Union[Block, Assign, If, While, Assert, Assume]


# ЭТАП 10.2 (продолжение). Верхний уровень.
#   Function(name, params, returns, requires, ensures, body) — requires/ensures = None, если нет
#   Program(functions)
@dataclass
class Function(Node):
    name: str
    params: List[str]
    returns: str
    requires: Optional[Expr]
    ensures: Optional[Expr]
    body: Block
    pos: Pos = field(default=(0, 0), compare=False)


@dataclass
class Program(Node):
    functions: List[Function]
    pos: Pos = field(default=(1, 1), compare=False)


# ЭТАП 10.3. AST -> JSON (формат для snapshot-тестов, слайд «AST: что строим»).
# Каждый узел превращается в словарь: "node" — имя класса, дальше поля по именам,
# в конце "pos": "строка:столбец". Списки — списками, None — null.
# Пример: x + 1  ->  {"node": "BinaryOp", "op": "+",
#                     "left": {"node": "Ident", "name": "x", "pos": "1:31"},
#                     "right": {"node": "Int", "value": 1, "pos": "1:35"}, "pos": "1:31"}
# Поле else_ называется в JSON просто "else" (в Python else_ — потому что else занято).
# from_dict делает обратное: из JSON снова узлы. Тест проверяет, что
# from_dict(to_dict(ast)) == ast для всех тестовых программ.
def _key(name: str) -> str:
    return "else" if name == "else_" else name


def to_dict(node, with_pos: bool = True):
    """AST -> обычные dict/list, пригодные для json.dumps. Поле "node" — имя узла."""
    if isinstance(node, list):
        return [to_dict(x, with_pos) for x in node]
    if not is_dataclass(node):
        return node
    out = {"node": type(node).__name__}
    for f in fields(node):
        if f.name == "pos":
            continue
        out[_key(f.name)] = to_dict(getattr(node, f.name), with_pos)
    if with_pos:
        out["pos"] = f"{node.pos[0]}:{node.pos[1]}"     # "строка:столбец"
    return out


def to_json(node, with_pos: bool = True) -> str:
    return json.dumps(to_dict(node, with_pos), ensure_ascii=False, indent=2)


_CLASSES = {c.__name__: c for c in (Int, Bool, Ident, ArrayIndex, Call, UnaryOp, BinaryOp,
                                    Block, Assign, If, While, Assert, Assume, Function, Program)}


def from_dict(data):
    """Обратное к to_dict — для следующих этапов (T0/T1), читающих AST из JSON."""
    if isinstance(data, list):
        return [from_dict(x) for x in data]
    if not isinstance(data, dict) or "node" not in data:
        return data
    cls = _CLASSES[data["node"]]
    kwargs = {}
    for f in fields(cls):
        key = _key(f.name)
        if f.name == "pos":
            if "pos" in data:
                line, col = data["pos"].split(":")
                kwargs["pos"] = (int(line), int(col))
        elif key in data:
            kwargs[f.name] = from_dict(data[key])
    return cls(**kwargs)


# ЭТАП 10.4. AST -> S-выражение (флаг --sexp): то же дерево в виде скобок, удобно читать.
# Операторы — по строке с отступом, выражения — в одну строку в префиксной записи:
#   x + 1 * 2   ->  (+ x (* 1 2))      a[i]  ->  (index a i)      f(x)  ->  (call f x)
# Пример целиком:
#   (program
#     (function f (params x) (returns r)
#       (block
#         (= r (+ x 1)))))
def to_sexp(node, indent: int = 0) -> str:
    pad = "  " * indent
    if node is None:
        return pad + "nil"
    if isinstance(node, Int):
        return pad + str(node.value)
    if isinstance(node, Bool):
        return pad + ("true" if node.value else "false")
    if isinstance(node, Ident):
        return pad + node.name
    if isinstance(node, (ArrayIndex, Call, UnaryOp, BinaryOp)):
        return pad + _inline(node)
    if isinstance(node, Program):
        return pad + "(program" + "".join("\n" + to_sexp(f, indent + 1) for f in node.functions) + ")"
    if isinstance(node, Function):
        head = (f"(function {node.name} (params{''.join(' ' + p for p in node.params)}) "
                f"(returns {node.returns})")
        parts = [pad + head]
        if node.requires is not None:
            parts.append(pad + f"  (requires {_inline(node.requires)})")
        if node.ensures is not None:
            parts.append(pad + f"  (ensures {_inline(node.ensures)})")
        parts.append(to_sexp(node.body, indent + 1) + ")")
        return "\n".join(parts)
    if isinstance(node, Block):
        if not node.stmts:
            return pad + "(block)"
        return pad + "(block" + "".join("\n" + to_sexp(s, indent + 1) for s in node.stmts) + ")"
    if isinstance(node, Assign):
        return pad + f"(= {_inline(node.target)} {_inline(node.value)})"
    if isinstance(node, Assert):
        return pad + f"(assert {_inline(node.expr)})"
    if isinstance(node, Assume):
        return pad + f"(assume {_inline(node.expr)})"
    if isinstance(node, If):
        s = pad + f"(if {_inline(node.cond)}\n" + to_sexp(node.then, indent + 1)
        if node.else_ is not None:
            s += "\n" + to_sexp(node.else_, indent + 1)
        return s + ")"
    if isinstance(node, While):
        s = pad + f"(while {_inline(node.cond)}"
        if node.invariant is not None:
            s += f" (invariant {_inline(node.invariant)})"
        return s + "\n" + to_sexp(node.body, indent + 1) + ")"
    raise TypeError(node)


def _inline(e) -> str:
    if isinstance(e, (Int, Bool, Ident)):
        return to_sexp(e)
    if isinstance(e, ArrayIndex):
        return f"(index {_inline(e.base)} {_inline(e.index)})"
    if isinstance(e, Call):
        return f"(call {e.name}{''.join(' ' + _inline(a) for a in e.args)})"
    if isinstance(e, UnaryOp):
        return f"({e.op} {_inline(e.operand)})"
    if isinstance(e, BinaryOp):
        return f"({e.op} {_inline(e.left)} {_inline(e.right)})"
    raise TypeError(e)


# ЭТАП 10.5. Сахар для обновления массива (требование задания).
# Массивы в Funny — значения, как числа: их нельзя «изменить на месте».
# Поэтому  a[i] = v  — это сокращение для  a = store(a, i, v):
# store строит НОВЫЙ массив, такой же, как a, но с v в ячейке i, и его присваивают a.
# Парсер хранит в AST исходную форму (как в грамматике), а desugar переписывает
# дерево по запросу (флаг --desugar):
#   a[j + 0] = t   ->   (= a (call store a (+ j 0) t))
def desugar(node):
    """a[i] = v  ->  a = store(a, i, v).

    Обновление массива — сахар для функционального копирования: создаётся
    новый массив, отличающийся от старого в одной ячейке, и он присваивается
    переменной a. Для a[i][j] = v получится вложенный store.
    """
    if isinstance(node, list):
        return [desugar(x) for x in node]
    if isinstance(node, Assign) and isinstance(node.target, ArrayIndex):
        target, value = node.target, desugar(node.value)
        while isinstance(target, ArrayIndex):
            value = Call("store", [target.base, target.index, value], pos=node.pos)
            target = target.base
        return Assign(target, value, pos=node.pos)
    if is_dataclass(node):
        changes = {f.name: desugar(getattr(node, f.name)) for f in fields(node) if f.name != "pos"}
        return replace(node, **changes)
    return node
