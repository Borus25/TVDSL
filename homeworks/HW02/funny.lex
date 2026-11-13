# Спецификация токенов Funny (из HW1) + REQUIRES/ENSURES для HW2.
# Формат: ИМЯ [@skip] = регулярка. Порядок строк = приоритет при равной длине.

FUNCTION  = function
RETURNS   = returns
USES      = uses
WHILE     = while
IF        = if
ELSE      = else
TRUE      = true
FALSE     = false
NOT       = not
AND       = and
OR        = or
ASSERT    = assert
ASSUME    = assume
INVARIANT = invariant
LENGTH    = length
# --- добавлено в HW2 (контракты функции)
REQUIRES  = requires
ENSURES   = ensures

IDENT = [A-Za-z_][A-Za-z0-9_]*
INT   = 0|[1-9][0-9]*

WS      @skip = [ \t\r\n]+
COMMENT @skip = //[^\r\n]*

OP = ==|!=|<=|>=|<|>|=|\+|-|\*|/|\(|\)|\[|\]|\{|\}|,|;
