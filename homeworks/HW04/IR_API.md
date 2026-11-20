# Контракт `funny-ir/1` для следующего этапа

## Python API

```python
from ir import Generator, optimize, cfg, liveness, allocation, Interpreter, dump

# payload: JSON HW3, уже прошедший успешную семантическую проверку.
ir = Generator().build(payload)
fn = ir['functions'][0]
optimized_fn = optimize(fn, ['const', 'algebraic', 'dce', 'cse'])
blocks = cfg(optimized_fn)
blocks_with_live_sets, live_in, live_out = liveness(optimized_fn)
alloc = allocation(optimized_fn, registers=4)
```

`Generator().build` создаёт новый IR. `optimize` не меняет входной объект. `cfg`, `liveness` и `allocation` не изменяют инструкции. `Interpreter(program).run(name, args)` — проверочная виртуальная машина, не JVM backend. `main.build_artifacts(payload, passes, registers=None)` возвращает `(before, after, allocations, metrics)`.

## Корневой JSON

```json
{
  "format": "funny-ir/1",
  "functions": [
    {
      "name": "f",
      "params": ["v1_x"],
      "param_types": ["int"],
      "return_type": "int",
      "types": {"v1_x": "int", "v2_r": "int", "t1": "int"},
      "code": [
        {"op": "bin", "operator": "+", "dst": "t1", "args": [{"var": "v1_x"}, {"const": 1}]},
        {"op": "copy", "dst": "v2_r", "args": [{"var": "t1"}]},
        {"op": "return", "args": [{"var": "v2_r"}]}
      ]
    }
  ]
}
```

Порядок функций сохранён из AST. `types` может содержать имена, удалённые DCE: это допустимая избыточная информация. Число активных временных и граф вычисляются по инструкциям, не по длине `types`. Типы повторяют HW3: `int`, `bool`, `array<T>`, `func(...)->T`.

## Операнды — tagged union

Ровно один из тегов:

-   `{"var": "t1"}` — локальная переменная/временная текущей функции.
-   `{"const": 5}` или `{"const": true}` — константа; тип JSON boolean не равен int.
-   `{"func": "f"}` — ссылка на функцию программы или встроенную `length`/`store`.

Метки не маскируются под значения: они хранятся в `label`, `target`, `targets`. Функциональные значения могут копироваться в локальные и использоваться косвенным call. Пользовательские имена после разрешения областей не встречаются как необработанные строковые операнды.

## Схемы инструкций

op

Обязательные поля

copy

`dst`, `args: [value]`

bin

`dst`, `operator`, `args: [left, right]`

un

`dst`, `operator`, `args: [operand]`

load

`dst`, `args: [array, index]`

call

`dst`, `args: [callee, arg1, ...]`

label

`label`

jump

`target`

branch

`args: [bool_condition]`, `targets: [if_true, if_false]`

return

`args: [result]`

assert/assume

`args: [condition]`, необязательное `message`

`bin.operator`: `+ - * / == != < <= > >=`. `un.operator`: `- not`. `and/or` понижаются в управление, а не в eager bin.

`dst` — строковое имя; тип результата находится в `types[dst]`. `call.args` включает callee как первый операнд; количество фактических аргументов равно `len(args)-1`. Отдельного стека `param`-инструкций нет: порядок аргументов непосредственно записан в JSON.

`return` завершает текущий frame. `branch` всегда имеет две цели; не предполагает дополнительного условного fall-through. У обычной инструкции есть fall-through к следующей. `jump` и `return` fall-through не имеют.

`load`, деление, вызов и проверки могут завершиться ошибкой. `store` — функциональная операция: возвращает новый массив. Операции над массивами и точная семантика ошибок описаны в README.

## Анализ

`cfg(fn)` возвращает список блоков:

```json
{"id": 0, "start": 0, "end": 3, "successors": [1, 2], "reachable": true}
```

Диапазон инструкций полуоткрытый: `[start, end)`. После `liveness()` блок дополнительно содержит `live_in`, `live_out` — списки имён. Два других результата `liveness()` — словари `int instruction_index -> set[str]`.

`allocation()` возвращает:

-   `blocks` — CFG с живостью;
-   `instruction_live_in`, `instruction_live_out` — сериализуемые множества по индексам;
-   `graph` — имя -> соседи, граф неориентированный, без самопетель;
-   `colors` — имя -> номер цвета от 0;
-   `color_count` — `1 + max(colors)` либо 0;
-   `temp_colors` — ограничение `colors` только на имена `t...`;
-   `spills` — имена с цветами вне заданного бюджета, если он задан.

Эти данные не являются машинными регистрами или окончательными JVM local slots. Spill rewriting, ABI, параметры на фиксированных слотах, типы/ширины JVM-слотов и stack map frames должен реализовать backend.

## Совместимость

IR не является SSA: исходные локальные и temporary результата short circuit могут иметь несколько определений. Backend не должен предполагать единственное присваивание или ожидать phi.

Успешный результат HW3 — обязательное предусловие API. Генератор дополнительно отвергает явные диагностики, неизвестные/ошибочные типы выражений и неподдержанные узлы, но не подменяет полную проверку AST с произвольным враждебным JSON. Не выполняйте напрямую непроверенный IR в доверенном процессе.

Никакого JVM-байткода этот модуль не создаёт: его результат — контракт для будущего кодогенератора.