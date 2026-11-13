# Шпаргалка по запуску HW2

Все команды выполняются в терминале из папки `HW2_Parser`.

## 0. Перед началом

- Открыть терминал в PyCharm: `Alt+F12`. Он сразу открывается в папке проекта.
- Проверить, что ты в нужной папке: `ls` должен показать `main.py`. Если нет, перейди: `cd путь/к/HW2_Parser`.
- Проверить Python: `python3 --version`, нужен 3.8 или новее. Если пишет «command not found», используй `python` вместо `python3`.

## 1. Тесты

| Команда | Что покажет |
|---|---|
| `python3 main.py --test` | 36 программ из `tests/` против эталонов, в конце `ИТОГО: 36/36 PASS` |
| `python3 main.py --test -v` | то же, плюс под каждым тестом ошибки и позиции |
| `python3 -m unittest test_parser -v` | 17 юнит-тестов, в конце `OK` (около 3 с) |

`--test --update` перезаписывает эталоны. На защите её **не запускай**.

## 2. Разобрать программу

Готовая программа для показа лежит в проекте: `demo.funny` (функции `max` и `sum`: `if/else`, `while` с `invariant`, `requires`/`ensures`, массивы, `length`, вызов функции).

| Команда | Что покажет |
|---|---|
| `python3 main.py demo.funny --sexp` | дерево (AST) S-выражением — удобнее всего читать |
| `python3 main.py demo.funny` | AST в JSON, у каждого узла `"pos": "строка:столбец"` |
| `python3 main.py demo.funny --no-pos` | JSON без позиций |
| `python3 main.py demo.funny --tokens` | что выдаёт лексер: позиция, вид, лексема |
| `python3 main.py demo.funny --sexp --desugar` | `a[i] = v` превращается в `a = store(a, i, v)` |
| `python3 main.py -e 'function f(x) returns r { r = x; }' --sexp` | программа прямо в команде |

Если препод даёт свою программу: создай в PyCharm файл `my.funny`, вставь код и запусти `python3 main.py my.funny --sexp`.

## 3. Показать ошибки

Сломай что-нибудь в `demo.funny`, запусти `python3 main.py demo.funny`, потом верни как было (`Ctrl+Z`).

| Что сломать | Что выведет |
|---|---|
| строка 5: убрать `)` в `if (a > b)` | `error: expected ')' but got '{' at 5:13` |
| строка 14: `s = s + ;` | `error: expected expression but got ';' at 14:13` |
| строка 15: `i == i + 1;` | `error: expected '=' but got '==' at 15:7 (assignment is '=')` |
| строка 13: `while i < n` без скобок | `error: expected '(' but got 'i' at 13:9` |
| строка 2: `max(a b)` без запятой | `error: expected ',' or ')' but got 'b' at 2:16` |
| строка 11: `s = 0 @;` | `error: unexpected character '@' at 11:9` (ошибка лексера) |
| удалить последнюю `}` | `error: expected '}' but got end of input at 18:1 (block opened at 10:1)` |

Готовые примеры из тестов:
- `python3 main.py tests/neg_12_many_errors.funny` — 8 ошибок за один запуск, все на разных строках: после ошибки разбор продолжается;
- `python3 main.py tests/neg_08_bad_operator.funny` — неверные операторы `=<`, `<>`, `&`, `**`;
- `python3 main.py tests/neg_05_empty_input.funny` — пустой ввод.

## 4. Приоритеты операторов

```bash
python3 main.py -e 'function f(x) returns r { r = 2 + 3 * 4 - x; }' --sexp
# (= r (- (+ 2 (* 3 4)) x))      * раньше +, вычитание левоассоциативно
```
Ещё пример: `tests/pos_09_precedence.funny --sexp`.

## 5. Грамматика LL(1)

```bash
python3 main.py --grammar
```
Печатает FIRST и FOLLOW всех нетерминалов, в конце «Конфликтов LL(1) нет».

## 6. Не зацикливается

```bash
python3 main.py -e 'x = ((((( } } ; ;'
```
Сразу выдаёт ошибку и завершается. Ещё это проверяет юнит-тест `test_no_hang_on_garbage` (1000 строк мусора), а `--test` прерывает тест, если он идёт дольше 5 секунд.

## 7. Код выхода

После любой команды `echo $?`: `0` — ошибок нет, `1` — в программе есть ошибки, `2` — неверные аргументы или файл не найден.

## 8. Чего нет в Funny (если попросят написать свою программу)

- нет `return`: результат присваивается переменной из `returns` (`r = x;`);
- нет `for`, только `while`;
- нет `else if`: пиши `else { if (...) { ... } }`;
- нет строк, `print`, типов, дробных чисел;
- сравнения нельзя писать цепочкой: `a < b < c` — ошибка, нужно `a < b and b < c`;
- `;` после операторов можно ставить или не ставить.

## 9. Если что-то пошло не так

| Проблема | Что делать |
|---|---|
| `python3: command not found` | писать `python` вместо `python3` |
| `can't open file 'main.py'` / `No such file` | ты не в той папке: `cd` в `HW2_Parser` |
| PyCharm: «No Python interpreter configured» | Create a virtual environment или Custom Environment → `/usr/bin/python3` |
| Запустил `--test --update` случайно | эталоны перезаписаны текущим выводом; если код не менял, ничего не изменилось |
| `-e '...'` ругается на кавычки | внутри одинарных кавычек не используй `'`; или положи код в файл |
