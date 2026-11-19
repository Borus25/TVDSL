"""HW3 type algebra; the name avoids shadowing Python's standard `types`."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Type:
    name: str
    args: Tuple['Type', ...] = ()

    def __str__(self) -> str:
        if self.name == 'array':
            return f'array<{self.args[0]}>'
        if self.name == 'func':
            return f"func({', '.join(map(str, self.args[:-1]))})->{self.args[-1]}"
        return self.name

    @property
    def elem(self) -> 'Type':
        if self.name != 'array':
            raise ValueError('not an array type')
        return self.args[0]


INT = Type('int')
BOOL = Type('bool')
ERROR = Type('<error>')


def array_type(elem: Type) -> Type:
    return Type('array', (elem,))


def func_type(params, result: Type) -> Type:
    return Type('func', tuple(params) + (result,))


def parse_type(text: str) -> Type:
    if text == 'int':
        return INT
    if text == 'bool':
        return BOOL
    if text.startswith('array<') and text.endswith('>'):
        return array_type(parse_type(text[6:-1]))
    raise ValueError(f'unsupported type {text!r}')


class UnificationError(ValueError):
    pass


def unify(left: Type, right: Type) -> Type:
    """Structural unification of ground types; no implicit conversions.

    ERROR is a recovery sentinel, not a language type. It absorbs a constraint
    that already contains an invalid subexpression without producing cascades.
    """
    if ERROR in (left, right):
        return ERROR
    if left.name != right.name or len(left.args) != len(right.args):
        raise UnificationError(f'cannot unify {left} and {right}')
    if not left.args:
        return left
    return Type(left.name, tuple(unify(a, b) for a, b in zip(left.args, right.args)))
