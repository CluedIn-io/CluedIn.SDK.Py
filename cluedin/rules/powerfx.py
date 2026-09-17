"""
A sandboxed evaluator for the subset of Power Fx used by CluedIn Rules.

Formulas are tokenized, parsed into an AST, and interpreted. They are never
passed to `eval` or `exec`, so rules authored by customers cannot reach Python.

Supported expressions:

- literals: strings, numbers, `true`, `false`, `Blank()`
- `Entity`, `Entity.Name`, and nested members such as `Entity.Properties.Foo`
- operators: `=`, `<>`, `<`, `<=`, `>`, `>=`, `+`, `-`, `*`, `/`, `&`,
  `in`, `exactin`, `And`/`&&`, `Or`/`||`, `Not`/`!`
- functions: see `PowerFxRuntime.FUNCTIONS`

Anything else raises `PowerFxError`.
"""

from __future__ import annotations

import calendar
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from typing import Any, Callable, Mapping, Optional
from urllib.parse import quote


class PowerFxError(ValueError):
    """Raised when a Power Fx formula cannot be parsed or evaluated."""


def _days_in_month(year: int, month: int) -> int:
    """
    Returns the number of days in a month, so DateAdd can clamp to it.

    Args:
        year (int): The year.
        month (int): The month.

    Returns:
        int: The last day of that month.
    """
    return calendar.monthrange(year, month)[1]


# ---------------------------------------------------------------------------
# Member access
# ---------------------------------------------------------------------------

def get_member(obj: Any, name: str) -> Any:
    """
    Returns a member of an object by name.

    Mappings are looked up by key, with a case-insensitive fallback, because
    CluedIn entities reach Python as JSON with inconsistent casing. Everything
    else is looked up by attribute. Missing members are `None` (Power Fx
    `Blank()`), never an error.

    Args:
        obj: The object to read from.
        name (str): The member name.

    Returns:
        Any: The member value, or None if it does not exist.
    """
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        if name in obj:
            return obj[name]
        lowered = name.lower()
        for key, value in obj.items():
            if isinstance(key, str) and key.lower() == lowered:
                return value
        return None
    return getattr(obj, name, None)


def flatten(value: Any) -> list:
    """
    Flattens nested lists into a single list. Scalars become a list of one.

    Args:
        value: The value to flatten.

    Returns:
        list: The flattened values.
    """
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(flatten(item))
        return result
    return [value]


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Token:
    """A lexical token: its kind, its decoded value, and its position."""

    kind: str
    value: Any
    pos: int


_TOKEN_RE = re.compile(
    r"""
    (?P<WS>\s+)
  | (?P<STRING>"(?:[^"]|"")*")
  | (?P<QUOTEDIDENT>'(?:[^']|'')*')
  | (?P<NUMBER>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<LE><=)
  | (?P<GE>>=)
  | (?P<NE><>)
  | (?P<ANDSYM>&&)
  | (?P<ORSYM>\|\|)
  | (?P<EQ>=)
  | (?P<LT><)
  | (?P<GT>>)
  | (?P<PLUS>\+)
  | (?P<MINUS>-)
  | (?P<MUL>\*)
  | (?P<DIV>/)
  | (?P<CONCAT>&)
  | (?P<NOTSYM>!)
  | (?P<LPAREN>\()
  | (?P<RPAREN>\))
  | (?P<COMMA>,)
  | (?P<SEMICOLON>;)
  | (?P<DOT>\.)
  | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)


def tokenize(text: str) -> list:
    """
    Splits a Power Fx formula into tokens.

    Args:
        text (str): The formula.

    Returns:
        list: The tokens, terminated by an EOF token.

    Raises:
        PowerFxError: If the formula contains a character we cannot lex.
    """
    tokens = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if not match:
            raise PowerFxError(
                f'Unexpected character at position {pos}: {text[pos:pos + 20]!r}')
        kind = match.lastgroup
        raw = match.group()
        if kind != 'WS':
            if kind == 'STRING':
                # Power Fx escapes a double quote inside a string as "".
                value = raw[1:-1].replace('""', '"')
            elif kind == 'QUOTEDIDENT':
                # 'Quoted names' hold identifiers with spaces or punctuation.
                kind = 'IDENT'
                value = raw[1:-1].replace("''", "'")
            elif kind == 'NUMBER':
                value = float(raw) if any(
                    c in raw for c in '.eE') else int(raw)
            else:
                value = raw
            tokens.append(Token(kind, value, pos))
        pos = match.end()
    tokens.append(Token('EOF', None, len(text)))
    return tokens


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Literal:
    """A constant value."""

    value: Any


@dataclass(frozen=True)
class Name:
    """A dotted name, such as `Entity.Name`, split into its parts."""

    parts: tuple


@dataclass(frozen=True)
class Member:
    """A member read from the result of an expression, as in `Foo(x).Name`."""

    expr: Any
    name: str


@dataclass(frozen=True)
class Unary:
    """A prefix operator applied to one operand."""

    op: str
    expr: Any


@dataclass(frozen=True)
class Binary:
    """An infix operator applied to two operands."""

    op: str
    left: Any
    right: Any


@dataclass(frozen=True)
class Call:
    """A function call."""

    name: str
    args: tuple


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_PRECEDENCE = {
    'or': 10,
    'and': 20,
    '=': 30, '<>': 30, '<': 30, '<=': 30, '>': 30, '>=': 30,
    'in': 30, 'exactin': 30,
    '&': 40,
    '+': 50, '-': 50,
    '*': 60, '/': 60,
}

_UNARY_PRECEDENCE = 70


class Parser:
    """
    A Pratt (precedence-climbing) parser for the supported Power Fx subset.

    Args:
        text (str): The formula to parse.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = tokenize(text)
        self.i = 0

    @property
    def current(self) -> Token:
        """The token the parser is positioned on."""
        return self.tokens[self.i]

    def take(self, kind: Optional[str] = None) -> Token:
        """
        Consumes and returns the current token.

        Args:
            kind (str, optional): If given, the kind the token must have.

        Returns:
            Token: The consumed token.

        Raises:
            PowerFxError: If `kind` is given and does not match.
        """
        token = self.current
        if kind and token.kind != kind:
            raise PowerFxError(
                f'Expected {kind} at position {token.pos}, got {token.kind}')
        self.i += 1
        return token

    def match(self, kind: str) -> bool:
        """
        Consumes the current token if it has the given kind.

        Args:
            kind (str): The kind to look for.

        Returns:
            bool: True if a token was consumed.
        """
        if self.current.kind == kind:
            self.i += 1
            return True
        return False

    def parse(self):
        """
        Parses the whole formula as a single expression.

        Returns:
            The root AST node.

        Raises:
            PowerFxError: If anything remains after the expression.
        """
        expr = self.expression(0)
        if self.current.kind != 'EOF':
            raise PowerFxError(
                f'Unexpected token {self.current.value!r} '
                f'at position {self.current.pos}')
        return expr

    def expression(self, min_precedence: int):
        """
        Parses an expression, consuming operators at or above a precedence.

        Args:
            min_precedence (int): The lowest precedence to bind.

        Returns:
            The AST node for the expression.
        """
        left = self.prefix()
        while True:
            op = self.binary_op()
            if op is None:
                break
            precedence = _PRECEDENCE[op]
            if precedence < min_precedence:
                break
            self.i += 1
            # Left-associative: the right operand binds tighter.
            right = self.expression(precedence + 1)
            left = Binary(op, left, right)
        return left

    def prefix(self):
        """
        Parses a prefix expression: a literal, name, call, group, or unary.

        Returns:
            The AST node.

        Raises:
            PowerFxError: If the token cannot start an expression.
        """
        token = self.current

        if token.kind == 'MINUS':
            self.take()
            return Unary('-', self.expression(_UNARY_PRECEDENCE))
        if token.kind == 'PLUS':
            self.take()
            return Unary('+', self.expression(_UNARY_PRECEDENCE))
        if token.kind == 'NOTSYM':
            self.take()
            return Unary('not', self.expression(_UNARY_PRECEDENCE))
        if token.kind == 'IDENT' and str(token.value).lower() == 'not' \
                and self.tokens[self.i + 1].kind != 'LPAREN':
            # `Not x`. `Not(x)` is parsed below as an ordinary call.
            self.take()
            return Unary('not', self.expression(_UNARY_PRECEDENCE))

        if token.kind in ('STRING', 'NUMBER'):
            self.take()
            return Literal(token.value)

        if token.kind == 'LPAREN':
            self.take()
            expr = self.expression(0)
            self.take('RPAREN')
            return self.postfix(expr)

        if token.kind == 'IDENT':
            return self.identifier()

        raise PowerFxError(
            f'Unexpected token {token.value!r} at position {token.pos}')

    def postfix(self, expr):
        """
        Wraps an expression in member reads for any `.name` that follows it,
        so that `LoadEntityByEntityCode(code).Name` resolves.

        Args:
            expr: The expression the members are read from.

        Returns:
            The AST node.
        """
        while self.match('DOT'):
            expr = Member(expr, str(self.take('IDENT').value))
        return expr

    def identifier(self):
        """
        Parses an identifier: a boolean literal, a call, or a dotted name.

        Returns:
            The AST node.
        """
        ident = str(self.take().value)
        lowered = ident.lower()

        if lowered == 'true':
            return Literal(True)
        if lowered == 'false':
            return Literal(False)

        if self.current.kind == 'LPAREN':
            self.take('LPAREN')
            args = []
            if self.current.kind != 'RPAREN':
                while True:
                    args.append(self.expression(0))
                    if not self.match('COMMA'):
                        break
            self.take('RPAREN')
            return self.postfix(Call(ident, tuple(args)))

        parts = [ident]
        while self.match('DOT'):
            parts.append(str(self.take('IDENT').value))
        return Name(tuple(parts))

    def binary_op(self) -> Optional[str]:
        """
        Returns the binary operator at the current token, without consuming it.

        Returns:
            str: The normalized operator, or None if there is no operator here.
        """
        kind = self.current.kind
        symbols = {
            'EQ': '=', 'NE': '<>', 'LT': '<', 'LE': '<=', 'GT': '>', 'GE': '>=',
            'PLUS': '+', 'MINUS': '-', 'MUL': '*', 'DIV': '/', 'CONCAT': '&',
            'ANDSYM': 'and', 'ORSYM': 'or',
        }
        if kind in symbols:
            return symbols[kind]
        if kind == 'IDENT':
            lowered = str(self.current.value).lower()
            if lowered in ('and', 'or', 'in', 'exactin'):
                return lowered
        return None


def parse(formula: str):
    """
    Parses a Power Fx formula into an AST.

    Args:
        formula (str): The formula.

    Returns:
        The root AST node.

    Raises:
        PowerFxError: If the formula is not valid.
    """
    return Parser(formula).parse()


# ---------------------------------------------------------------------------
# Coercion
# ---------------------------------------------------------------------------

def to_bool(value: Any) -> bool:
    """
    Coerces a value to a Power Fx boolean. `Blank()` is false.

    Args:
        value: The value to coerce.

    Returns:
        bool: The coerced value.
    """
    return bool(value)


def to_number(value: Any):
    """
    Coerces a value to a number. `Blank()` and empty text are 0.

    Text is read with the invariant conventions: `,` groups thousands, `.` is
    the decimal separator, a trailing `%` divides by 100, and a value wrapped
    in parentheses is negative. Locales that swap `,` and `.` are not
    supported – `"1.000,50"` reads as 1.0, not 1000.5.

    Args:
        value: The value to coerce.

    Returns:
        int or float: The coerced value.

    Raises:
        PowerFxError: If the value is not numeric.
    """
    if value is None or value == '':
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return value

    text = str(value).strip()
    original = text

    # Accounting-style negatives: (1,234.50) is -1234.50.
    negative = False
    if len(text) > 1 and text.startswith('(') and text.endswith(')'):
        negative = True
        text = text[1:-1].strip()

    percent = text.endswith('%')
    if percent:
        text = text[:-1].strip()

    # Group separators, but only where they actually separate groups, so that
    # a decimal comma is not silently swallowed.
    if _GROUPED_NUMBER_RE.fullmatch(text):
        text = text.replace(',', '')

    try:
        number = int(text)
    except ValueError:
        try:
            number = float(text)
        except ValueError as exc:
            raise PowerFxError(f'Value {original!r} is not numeric') from exc

    if percent:
        number = number / 100
    return -number if negative else number


_GROUPED_NUMBER_RE = re.compile(r'[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?')


def round_half_up(value: float, digits: int = 0):
    """
    Rounds half away from zero, as Power Fx and .NET do.

    Python's built-in `round` rounds half to even, so `round(2.5)` is 2 where
    Power Fx `Round(2.5)` is 3.

    Args:
        value (float): The number to round.
        digits (int, optional): Decimal places. Defaults to 0.

    Returns:
        int or float: The rounded value; an int when rounding to whole numbers.
    """
    quantum = Decimal(1).scaleb(-digits)
    try:
        rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise PowerFxError(f'Cannot round {value!r} to {digits} places') from exc
    if digits <= 0:
        return int(rounded)
    return float(rounded)


def to_text(value: Any) -> str:
    """
    Coerces a value to text. `Blank()` is the empty string.

    Args:
        value: The value to coerce.

    Returns:
        str: The coerced value.
    """
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e16:
        # Power Fx has one number type, so 2.0 reads back as "2", not "2.0".
        return str(int(value))
    return str(value)


def to_date(value: Any):
    """
    Coerces a value to a date or datetime.

    Args:
        value: The value to coerce.

    Returns:
        date or datetime: The coerced value.

    Raises:
        PowerFxError: If the value is blank or is not a recognized date.
    """
    if isinstance(value, (date, datetime)):
        return value
    if value is None:
        raise PowerFxError('Cannot convert Blank() to a date')
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise PowerFxError(
                f'Unsupported date value: {value!r}') from exc


def _as_comparable(value: Any, other: Any):
    """
    Aligns a value with the type of the value it is compared against, so that
    text from a data part can be ordered against a number or date in a rule.

    Args:
        value: The value to align.
        other: The value it will be compared against.

    Returns:
        The aligned value, or the original if no alignment applies.
    """
    if isinstance(value, str) and isinstance(other, (int, float)) \
            and not isinstance(other, bool):
        try:
            return to_number(value)
        except PowerFxError:
            return value
    if isinstance(value, str) and isinstance(other, (date, datetime)):
        try:
            return to_date(value)
        except PowerFxError:
            return value
    return value


def compare(left: Any, right: Any, op: str) -> bool:
    """
    Applies a Power Fx comparison operator.

    Multi-valued properties (CluedIn vocabulary keys can hold lists) compare
    with ANY semantics, except `<>`, which holds only if every value differs.
    Ordering against `Blank()` is false rather than an error.

    Args:
        left: The left operand.
        right: The right operand.
        op (str): One of `=`, `<>`, `<`, `<=`, `>`, `>=`.

    Returns:
        bool: The result of the comparison.

    Raises:
        PowerFxError: If the operator is not a comparison.
    """
    if isinstance(left, list):
        values = flatten(left)
        if op == '<>':
            return all(compare(x, right, op) for x in values)
        return any(compare(x, right, op) for x in values)
    if isinstance(right, list):
        values = flatten(right)
        if op == '<>':
            return all(compare(left, x, op) for x in values)
        return any(compare(left, x, op) for x in values)

    if op == '=':
        return left == right
    if op == '<>':
        return left != right

    if left is None or right is None:
        # Power Fx orders Blank() as 0 against numbers; against anything else
        # an ordering comparison is simply not satisfied.
        if isinstance(left, (int, float)) or isinstance(right, (int, float)):
            left = 0 if left is None else left
            right = 0 if right is None else right
        else:
            return False

    left = _as_comparable(left, right)
    right = _as_comparable(right, left)

    try:
        if op == '<':
            return left < right
        if op == '<=':
            return left <= right
        if op == '>':
            return left > right
        if op == '>=':
            return left >= right
    except TypeError as exc:
        raise PowerFxError(
            f'Cannot compare {left!r} and {right!r} with {op}') from exc

    raise PowerFxError(f'Unknown comparison operator: {op}')


_DATE_FORMAT_MAP = (
    ('yyyy', '%Y'), ('yy', '%y'),
    ('MMMM', '%B'), ('MMM', '%b'), ('MM', '%m'),
    ('dddd', '%A'), ('ddd', '%a'), ('dd', '%d'),
    ('HH', '%H'), ('hh', '%I'),
    ('mm', '%M'), ('ss', '%S'),
    ('tt', '%p'),
)


def format_value(value: Any, fmt: Optional[str] = None) -> str:
    """
    Implements Power Fx `Text()`.

    Args:
        value: The value to format.
        fmt (str, optional): A Power Fx format string.

    Returns:
        str: The formatted value.
    """
    if fmt is None:
        return to_text(value)
    if isinstance(value, (date, datetime)):
        # Translate the .NET-style placeholders CluedIn rules use. Longest
        # first, so `MM` cannot consume half of `MMM`.
        pattern = fmt
        placeholders = {}
        for index, (net, py) in enumerate(_DATE_FORMAT_MAP):
            if net in pattern:
                token = f'\x00{index}\x00'
                pattern = pattern.replace(net, token)
                placeholders[token] = py
        for token, py in placeholders.items():
            pattern = pattern.replace(token, py)
        return value.strftime(pattern)
    return format_number(to_number(value), fmt)


_STANDARD_NUMBER_RE = re.compile(r'^([NnFfPpEeGgDdXx])(\d*)$')


def _group_digits(digits: str) -> str:
    """
    Inserts `,` every three digits from the right.

    Args:
        digits (str): The integer digits.

    Returns:
        str: The grouped digits.
    """
    out = []
    for index, digit in enumerate(reversed(digits)):
        if index and index % 3 == 0:
            out.append(',')
        out.append(digit)
    return ''.join(reversed(out))


def _format_custom_number(number: float, fmt: str) -> str:
    """
    Applies a custom .NET numeric pattern built from `#`, `0`, `,` and `.`,
    such as `0.00` or `#,##0.00`.

    Args:
        number (float): The number to format.
        fmt (str): The pattern.

    Returns:
        str: The formatted number.

    Raises:
        PowerFxError: If the pattern uses anything else.
    """
    integer_pattern, _, fraction_pattern = fmt.partition('.')

    if any(c not in '#0,' for c in integer_pattern) \
            or any(c not in '#0' for c in fraction_pattern):
        raise PowerFxError(f'Unsupported numeric format: {fmt!r}')

    decimals = len(fraction_pattern)
    required_decimals = fraction_pattern.count('0')
    required_integers = integer_pattern.count('0')

    negative = number < 0
    text = f'{abs(round_half_up(number, decimals)):.{decimals}f}'
    integer_digits, _, fraction_digits = text.partition('.')

    # `#` marks an optional digit, so drop trailing zeros it did not require.
    while len(fraction_digits) > required_decimals \
            and fraction_digits.endswith('0'):
        fraction_digits = fraction_digits[:-1]

    integer_digits = integer_digits.lstrip('0')
    if len(integer_digits) < required_integers:
        integer_digits = integer_digits.rjust(required_integers, '0')
    if not integer_digits and not fraction_digits:
        integer_digits = '0'

    if ',' in integer_pattern:
        integer_digits = _group_digits(integer_digits)

    out = integer_digits
    if fraction_digits:
        out = f'{out}.{fraction_digits}'
    # -0 is 0.
    return f'-{out}' if negative and float(text) else out


def format_number(number: float, fmt: str) -> str:
    """
    Implements the .NET numeric format strings Power Fx `Text()` accepts.

    Standard specifiers `N`, `F`, `P`, `E`, `G`, `D` and `X` are supported,
    each with an optional precision, as are custom patterns built from `#`,
    `0`, `,` and `.`. Anything else raises rather than returning a number that
    does not match what was asked for.

    Args:
        number (float): The number to format.
        fmt (str): The format string.

    Returns:
        str: The formatted number.

    Raises:
        PowerFxError: If the format is not supported.
    """
    standard = _STANDARD_NUMBER_RE.match(fmt)
    if standard:
        specifier = standard.group(1).upper()
        precision = int(standard.group(2)) if standard.group(2) else None

        if specifier == 'N':
            return _format_custom_number(
                number, '#,##0.' + '0' * (2 if precision is None else precision)
                if (precision is None or precision > 0) else '#,##0')
        if specifier == 'F':
            return f'{number:.{2 if precision is None else precision}f}'
        if specifier == 'P':
            digits = 2 if precision is None else precision
            return _format_custom_number(
                number * 100,
                '#,##0.' + '0' * digits if digits else '#,##0') + '%'
        if specifier == 'E':
            digits = 6 if precision is None else precision
            return f'{number:.{digits}E}'
        if specifier == 'G':
            return to_text(number)
        if specifier == 'D':
            # D is integer-only in .NET, zero padded to the given width.
            integer = int(number)
            width = 0 if precision is None else precision
            return f'-{abs(integer):0{width}d}' if integer < 0 \
                else f'{integer:0{width}d}'
        if specifier == 'X':
            integer = int(number)
            width = 0 if precision is None else precision
            digits = f'{abs(integer):0{width}X}'
            return f'-{digits}' if integer < 0 else digits

    if fmt and all(c in '#0,.' for c in fmt):
        return _format_custom_number(number, fmt)

    raise PowerFxError(
        f'Unsupported numeric format: {fmt!r}. Supported are N, F, P, E, G, '
        'D and X with an optional precision, and custom patterns of #, 0, '
        ', and .')


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------

class PowerFxRuntime:
    """
    Interprets a parsed Power Fx formula against a CluedIn entity.

    Args:
        entity: The object the formula is evaluated against. `Entity` in a
            formula resolves to this.
        get_value (callable, optional): `(key, entity) -> value`, used by
            `GetVocabularyKeyValue` to read a vocabulary key. Defaults to
            looking in a `Properties` mapping, then in the entity itself.
        load_entity_by_code (callable, optional): `(code) -> entity`, used by
            `LoadEntityByEntityCode`. Without it, that function raises.
    """

    FUNCTIONS = (
        'Abs', 'And', 'Average', 'Blank', 'Boolean', 'Char', 'Coalesce',
        'Concatenate', 'CountRows', 'DateAdd', 'DateDiff', 'DateTimeValue',
        'DateValue', 'Day', 'EncodeUrl', 'EndsWith', 'Find',
        'GetVocabularyKeyValue', 'Hour', 'If', 'IfError', 'Int', 'IsBlank',
        'IsBlankOrError', 'IsEmpty', 'IsError', 'IsMatch', 'Left', 'Len',
        'LoadEntityByEntityCode', 'Lower', 'Max', 'Mid', 'Min', 'Minute',
        'Mod', 'Month', 'Not', 'Now', 'Or', 'Power', 'Proper', 'Replace',
        'Right', 'Round', 'Second', 'Split', 'Sqrt', 'StartsWith',
        'Substitute', 'Sum', 'Switch', 'Text', 'Today', 'Trim', 'Trunc',
        'Upper', 'Value', 'Weekday', 'Year',
    )

    def __init__(
        self,
        entity: Any,
        get_value: Optional[Callable[[str, Any], Any]] = None,
        load_entity_by_code: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.entity = entity
        self.get_value = get_value
        self.load_entity_by_code = load_entity_by_code

    def evaluate(self, node: Any) -> Any:
        """
        Evaluates an AST node.

        Args:
            node: The node to evaluate.

        Returns:
            Any: The value of the node.

        Raises:
            PowerFxError: If the node cannot be evaluated.
        """
        if isinstance(node, Literal):
            return node.value
        if isinstance(node, Name):
            return self.resolve(node)
        if isinstance(node, Member):
            return get_member(self.evaluate(node.expr), node.name)
        if isinstance(node, Unary):
            return self.evaluate_unary(node)
        if isinstance(node, Binary):
            return self.evaluate_binary(node)
        if isinstance(node, Call):
            return self.evaluate_call(node)
        raise PowerFxError(f'Unknown AST node: {node!r}')

    def resolve(self, node: Name) -> Any:
        """
        Resolves a dotted name against the entity.

        Args:
            node (Name): The name node.

        Returns:
            Any: The resolved value.

        Raises:
            PowerFxError: If the name is not rooted at `Entity`.
        """
        if node.parts[0].lower() != 'entity':
            raise PowerFxError(
                f'Unknown identifier: {".".join(node.parts)}. '
                'Only names rooted at Entity are supported.')
        current = self.entity
        for part in node.parts[1:]:
            current = get_member(current, part)
        return current

    def evaluate_unary(self, node: Unary) -> Any:
        """
        Evaluates a prefix operator.

        Args:
            node (Unary): The node.

        Returns:
            Any: The result.

        Raises:
            PowerFxError: If the operator is not supported.
        """
        value = self.evaluate(node.expr)
        if node.op == 'not':
            return not to_bool(value)
        if node.op == '-':
            return -to_number(value)
        if node.op == '+':
            return +to_number(value)
        raise PowerFxError(f'Unsupported unary operator: {node.op}')

    def evaluate_binary(self, node: Binary) -> Any:
        """
        Evaluates an infix operator. `And` and `Or` short-circuit.

        Args:
            node (Binary): The node.

        Returns:
            Any: The result.

        Raises:
            PowerFxError: If the operator is not supported.
        """
        if node.op == 'and':
            return to_bool(self.evaluate(node.left)) \
                and to_bool(self.evaluate(node.right))
        if node.op == 'or':
            return to_bool(self.evaluate(node.left)) \
                or to_bool(self.evaluate(node.right))

        left = self.evaluate(node.left)
        right = self.evaluate(node.right)

        if node.op in ('=', '<>', '<', '<=', '>', '>='):
            return compare(left, right, node.op)
        if node.op in ('in', 'exactin'):
            return self.contains(left, right, case_sensitive=node.op == 'exactin')
        if node.op == '&':
            return to_text(left) + to_text(right)
        if node.op == '+':
            return to_number(left) + to_number(right)
        if node.op == '-':
            return to_number(left) - to_number(right)
        if node.op == '*':
            return to_number(left) * to_number(right)
        if node.op == '/':
            divisor = to_number(right)
            if divisor == 0:
                raise PowerFxError('Division by zero')
            return to_number(left) / divisor
        raise PowerFxError(f'Unsupported binary operator: {node.op}')

    @staticmethod
    def contains(needle: Any, haystack: Any, case_sensitive: bool) -> bool:
        """
        Implements the `in` and `exactin` operators. `in` ignores case.

        Args:
            needle: The value to look for.
            haystack: Text to search within, or a collection to search in.
            case_sensitive (bool): True for `exactin`, False for `in`.

        Returns:
            bool: True if the needle was found.
        """
        if haystack is None:
            return False
        if isinstance(haystack, str):
            left, right = to_text(needle), haystack
            if not case_sensitive:
                left, right = left.lower(), right.lower()
            return left in right
        if isinstance(haystack, (list, tuple, set)):
            values = flatten(list(haystack))
            if case_sensitive:
                return any(needle == x for x in values)
            return any(to_text(needle).lower() == to_text(x).lower()
                       for x in values)
        return False

    def evaluate_call(self, node: Call) -> Any:
        """
        Evaluates a function call. `If`, `And`, `Or` and `Coalesce` evaluate
        their arguments lazily, as Power Fx does; everything else is eager.

        Args:
            node (Call): The node.

        Returns:
            Any: The result.

        Raises:
            PowerFxError: If the function is not supported or is misused.
        """
        name = node.name.lower()

        if name == 'if':
            return self.call_if(node.args)
        if name == 'and':
            return all(to_bool(self.evaluate(arg)) for arg in node.args)
        if name == 'or':
            return any(to_bool(self.evaluate(arg)) for arg in node.args)
        if name == 'coalesce':
            for arg in node.args:
                value = self.evaluate(arg)
                if value is not None and value != '':
                    return value
            return None
        if name == 'isblankorerror':
            # The point of IsBlankOrError is to swallow the error.
            self.expects(node.name, node.args, 1)
            try:
                value = self.evaluate(node.args[0])
            except PowerFxError:
                return True
            return value is None or value == ''
        if name == 'iserror':
            self.expects(node.name, node.args, 1)
            try:
                self.evaluate(node.args[0])
            except PowerFxError:
                return True
            return False
        if name == 'iferror':
            return self.call_if_error(node.args)
        if name == 'switch':
            return self.call_switch(node.args)

        return self.call(node.name, [self.evaluate(arg) for arg in node.args])

    def call_if(self, args: tuple) -> Any:
        """
        Implements Power Fx `If`, including the `If(c1, v1, c2, v2, ..., else)`
        form, evaluating only the branch that is taken.

        Args:
            args (tuple): The unevaluated argument nodes.

        Returns:
            Any: The value of the branch taken, or None if none was.

        Raises:
            PowerFxError: If fewer than two arguments were given.
        """
        if len(args) < 2:
            raise PowerFxError(
                f'If expects at least 2 arguments, got {len(args)}')
        index = 0
        while index + 1 < len(args):
            if to_bool(self.evaluate(args[index])):
                return self.evaluate(args[index + 1])
            index += 2
        # A trailing odd argument is the else branch.
        if index < len(args):
            return self.evaluate(args[index])
        return None

    def call_if_error(self, args: tuple) -> Any:
        """
        Implements `IfError(value, fallback, [value2, fallback2, ...], [else])`,
        returning the first value that evaluates without error.

        This engine raises on an error rather than carrying a Power Fx error
        value, so the error is caught here instead of flowing through the
        expression.

        Args:
            args (tuple): The unevaluated argument nodes.

        Returns:
            Any: The first value that evaluated, or the trailing else branch.

        Raises:
            PowerFxError: If fewer than two arguments were given, or if the
                last fallback itself errors.
        """
        if len(args) < 2:
            raise PowerFxError(
                f'IfError expects at least 2 arguments, got {len(args)}')
        index = 0
        while index + 1 < len(args):
            try:
                return self.evaluate(args[index])
            except PowerFxError:
                pass
            # An odd trailing argument is the else branch, so only take this
            # fallback when it is the last pair.
            if index + 3 > len(args):
                return self.evaluate(args[index + 1])
            index += 2
        return self.evaluate(args[index]) if index < len(args) else None

    def call_switch(self, args: tuple) -> Any:
        """
        Implements `Switch(value, match1, result1, ..., [default])`, evaluating
        only the branch that is taken.

        Args:
            args (tuple): The unevaluated argument nodes.

        Returns:
            Any: The matching result, the default, or None.

        Raises:
            PowerFxError: If fewer than three arguments were given.
        """
        if len(args) < 3:
            raise PowerFxError(
                f'Switch expects at least 3 arguments, got {len(args)}')
        value = self.evaluate(args[0])
        index = 1
        while index + 1 < len(args):
            if compare(value, self.evaluate(args[index]), '='):
                return self.evaluate(args[index + 1])
            index += 2
        # A trailing odd argument is the default.
        if index < len(args):
            return self.evaluate(args[index])
        return None

    # pylint: disable=too-many-return-statements,too-many-branches
    def call(self, name: str, args: list) -> Any:
        """
        Dispatches an eagerly-evaluated Power Fx function.

        Functions are listed explicitly so that an unsupported formula fails
        loudly instead of reaching anything it should not.

        Args:
            name (str): The function name as written.
            args (list): The evaluated arguments.

        Returns:
            Any: The result.

        Raises:
            PowerFxError: If the function is not supported or is misused.
        """
        key = name.lower()

        if key == 'blank':
            self.expects(name, args, 0)
            return None

        if key == 'getvocabularykeyvalue':
            self.expects(name, args, 2)
            return self.vocabulary_key_value(args[0], to_text(args[1]))

        if key == 'left':
            self.expects(name, args, 2)
            count = int(to_number(args[1]))
            return to_text(args[0])[:max(count, 0)]
        if key == 'right':
            self.expects(name, args, 2)
            count = int(to_number(args[1]))
            return to_text(args[0])[-count:] if count > 0 else ''
        if key == 'mid':
            self.expects(name, args, (2, 3))
            # Power Fx string positions are 1-based.
            start = max(int(to_number(args[1])) - 1, 0)
            text = to_text(args[0])
            if len(args) == 2:
                return text[start:]
            count = int(to_number(args[2]))
            return text[start:start + max(count, 0)]
        if key == 'len':
            self.expects(name, args, 1)
            return len(to_text(args[0]))
        if key == 'startswith':
            self.expects(name, args, 2)
            # Power Fx StartsWith/EndsWith ignore case.
            return to_text(args[0]).lower().startswith(to_text(args[1]).lower())
        if key == 'endswith':
            self.expects(name, args, 2)
            return to_text(args[0]).lower().endswith(to_text(args[1]).lower())
        if key == 'lower':
            self.expects(name, args, 1)
            return to_text(args[0]).lower()
        if key == 'upper':
            self.expects(name, args, 1)
            return to_text(args[0]).upper()
        if key == 'proper':
            self.expects(name, args, 1)
            return to_text(args[0]).title()
        if key == 'trim':
            self.expects(name, args, 1)
            # Power Fx Trim also collapses runs of internal whitespace.
            return ' '.join(to_text(args[0]).split())
        if key == 'substitute':
            self.expects(name, args, (3, 4))
            text, old, new = to_text(args[0]), to_text(args[1]), to_text(args[2])
            if not old:
                return text
            if len(args) == 3:
                return text.replace(old, new)
            # The 4th argument picks a single occurrence, 1-based.
            occurrence = int(to_number(args[3]))
            if occurrence < 1:
                return text
            parts = text.split(old)
            if len(parts) <= occurrence:
                return text
            return old.join(parts[:occurrence]) + new + old.join(parts[occurrence:])
        if key == 'replace':
            self.expects(name, args, 4)
            text = to_text(args[0])
            start = max(int(to_number(args[1])) - 1, 0)
            count = max(int(to_number(args[2])), 0)
            return text[:start] + to_text(args[3]) + text[start + count:]
        if key == 'concatenate':
            return ''.join(to_text(arg) for arg in args)

        if key == 'isblank':
            self.expects(name, args, 1)
            return args[0] is None or args[0] == ''
        if key == 'isempty':
            self.expects(name, args, 1)
            return not args[0] if isinstance(args[0], (list, tuple)) \
                else args[0] is None
        if key == 'not':
            self.expects(name, args, 1)
            return not to_bool(args[0])

        if key == 'value':
            self.expects(name, args, 1)
            return to_number(args[0])
        if key == 'text':
            self.expects(name, args, (1, 2))
            return format_value(args[0], args[1] if len(args) == 2 else None)
        if key == 'abs':
            self.expects(name, args, 1)
            return abs(to_number(args[0]))
        if key == 'round':
            self.expects(name, args, (1, 2))
            digits = int(to_number(args[1])) if len(args) == 2 else 0
            return round_half_up(to_number(args[0]), digits)

        if key == 'datevalue':
            self.expects(name, args, 1)
            # DateValue drops any time component, so that a date-only rule
            # value compares equal to a timestamped property.
            value = to_date(args[0])
            return value.date() if isinstance(value, datetime) else value
        if key == 'datetimevalue':
            self.expects(name, args, 1)
            value = to_date(args[0])
            return value if isinstance(value, datetime) \
                else datetime(value.year, value.month, value.day)
        if key == 'today':
            self.expects(name, args, 0)
            return date.today()
        if key == 'now':
            self.expects(name, args, 0)
            return datetime.now(timezone.utc)
        if key == 'datediff':
            return self.date_diff(args)

        if key == 'countrows':
            self.expects(name, args, 1)
            if args[0] is None:
                return 0
            return len(args[0]) if isinstance(args[0], (list, tuple)) else 1

        if key == 'ismatch':
            self.expects(name, args, (2, 3))
            return self.is_match(
                to_text(args[0]), to_text(args[1]),
                to_text(args[2]) if len(args) == 3 else '')
        if key == 'find':
            self.expects(name, args, (2, 3))
            start = max(int(to_number(args[2])) - 1, 0) if len(args) == 3 else 0
            found = to_text(args[1]).find(to_text(args[0]), start)
            # Power Fx returns Blank() when the text is not found, and its
            # string positions are 1-based.
            return None if found < 0 else found + 1
        if key == 'split':
            self.expects(name, args, 2)
            separator = to_text(args[1])
            text = to_text(args[0])
            # A real Power Fx Split returns a single-column table. This engine
            # has no table type, so it returns a list, which comparisons and
            # CountRows already understand.
            return list(text) if not separator else text.split(separator)

        if key == 'dateadd':
            self.expects(name, args, (2, 3))
            return self.date_add(
                to_date(args[0]), int(to_number(args[1])),
                to_text(args[2]).lower() if len(args) == 3 else 'days')
        if key in ('year', 'month', 'day', 'hour', 'minute', 'second',
                   'weekday'):
            self.expects(name, args, (1, 2) if key == 'weekday' else 1)
            return self.date_part(key, args)

        if key in ('sum', 'max', 'min', 'average'):
            values = [to_number(x) for x in flatten(list(args))
                      if x is not None and x != '']
            if not values:
                return 0 if key == 'sum' else None
            if key == 'sum':
                return sum(values)
            if key == 'max':
                return max(values)
            if key == 'min':
                return min(values)
            return sum(values) / len(values)
        if key == 'int':
            self.expects(name, args, 1)
            return math.floor(to_number(args[0]))
        if key == 'trunc':
            self.expects(name, args, (1, 2))
            if len(args) == 2:
                digits = int(to_number(args[1]))
                factor = 10 ** digits
                return math.trunc(to_number(args[0]) * factor) / factor
            return math.trunc(to_number(args[0]))
        if key == 'mod':
            self.expects(name, args, 2)
            divisor = to_number(args[1])
            if divisor == 0:
                raise PowerFxError('Mod by zero')
            # Power Fx follows Excel: the result takes the divisor's sign,
            # which is what Python's % already does.
            return to_number(args[0]) % divisor
        if key == 'power':
            self.expects(name, args, 2)
            try:
                return to_number(args[0]) ** to_number(args[1])
            except (OverflowError, ZeroDivisionError) as exc:
                raise PowerFxError(f'Power is out of range: {exc}') from exc
        if key == 'sqrt':
            self.expects(name, args, 1)
            number = to_number(args[0])
            if number < 0:
                raise PowerFxError('Sqrt of a negative number')
            return math.sqrt(number)

        if key == 'char':
            self.expects(name, args, 1)
            code = int(to_number(args[0]))
            if not 0 < code < 0x110000:
                raise PowerFxError(f'Char is out of range: {code}')
            return chr(code)
        if key == 'encodeurl':
            self.expects(name, args, 1)
            return quote(to_text(args[0]), safe='')
        if key == 'boolean':
            self.expects(name, args, 1)
            return self.to_boolean(args[0])

        if key == 'loadentitybyentitycode':
            self.expects(name, args, 1)
            if self.load_entity_by_code is None:
                raise PowerFxError(
                    'LoadEntityByEntityCode requires a load_entity_by_code '
                    'callback, which was not provided.')
            return self.load_entity_by_code(to_text(args[0]))

        raise PowerFxError(f'Unsupported Power Fx function: {name}')

    def vocabulary_key_value(self, entity: Any, key: str) -> Any:
        """
        Implements `GetVocabularyKeyValue`.

        Args:
            entity: The entity to read from.
            key (str): The vocabulary key.

        Returns:
            Any: The value, or None if the key is not set.
        """
        if self.get_value is not None:
            return self.get_value(key, entity)
        properties = get_member(entity, 'Properties')
        if isinstance(properties, Mapping):
            value = get_member(properties, key)
            if value is not None:
                return value
        # CluedIn entities also reach Python flattened, with vocabulary keys
        # as top-level keys.
        return get_member(entity, key)

    @staticmethod
    def is_match(text: str, pattern: str, options: str) -> bool:
        """
        Implements `IsMatch`, which matches the whole text by default.

        Args:
            text (str): The text to test.
            pattern (str): A regular expression.
            options (str): Comma-separated options: `Complete` (the default),
                `Contains`, `BeginsWith`, `EndsWith`, `IgnoreCase`.

        Returns:
            bool: True if the text matches.

        Raises:
            PowerFxError: If an option or the pattern is not supported.
        """
        flags = 0
        mode = 'complete'
        for option in (o.strip().lower() for o in options.split(',') if o.strip()):
            if option in ('matchoptions.ignorecase', 'ignorecase'):
                flags |= re.IGNORECASE
            elif option in ('matchoptions.contains', 'contains'):
                mode = 'contains'
            elif option in ('matchoptions.beginswith', 'beginswith'):
                mode = 'beginswith'
            elif option in ('matchoptions.endswith', 'endswith'):
                mode = 'endswith'
            elif option in ('matchoptions.complete', 'complete'):
                mode = 'complete'
            else:
                raise PowerFxError(f'Unsupported IsMatch option: {option!r}')

        try:
            if mode == 'contains':
                return re.search(pattern, text, flags) is not None
            if mode == 'beginswith':
                return re.match(pattern, text, flags) is not None
            if mode == 'endswith':
                return re.search(f'(?:{pattern})$', text, flags) is not None
            return re.fullmatch(pattern, text, flags) is not None
        except re.error as exc:
            raise PowerFxError(
                f'Invalid regular expression {pattern!r}: {exc}') from exc

    @staticmethod
    def to_boolean(value: Any) -> Optional[bool]:
        """
        Implements `Boolean`, which reads text and numbers as true or false.

        Args:
            value: The value to convert.

        Returns:
            bool: The converted value, or None for Blank().

        Raises:
            PowerFxError: If the text is not a boolean.
        """
        if value is None or value == '':
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        text = to_text(value).strip().lower()
        if text in ('true', '1'):
            return True
        if text in ('false', '0'):
            return False
        raise PowerFxError(f'Value {value!r} is not a boolean')

    @staticmethod
    def date_add(value, number: int, unit: str):
        """
        Implements `DateAdd(date, number, [unit])`.

        Args:
            value: The date or datetime to add to.
            number (int): How many units to add.
            unit (str): days, months, quarters, years, hours, minutes,
                seconds or milliseconds.

        Returns:
            date or datetime: The shifted value.

        Raises:
            PowerFxError: If the unit is not supported.
        """
        deltas = {
            'day': 'days', 'days': 'days',
            'hour': 'hours', 'hours': 'hours',
            'minute': 'minutes', 'minutes': 'minutes',
            'second': 'seconds', 'seconds': 'seconds',
            'millisecond': 'milliseconds', 'milliseconds': 'milliseconds',
        }
        if unit in deltas:
            if deltas[unit] != 'days' and not isinstance(value, datetime):
                value = datetime(value.year, value.month, value.day)
            return value + timedelta(**{deltas[unit]: number})

        if unit in ('month', 'months', 'quarter', 'quarters', 'year', 'years'):
            if unit in ('quarter', 'quarters'):
                number *= 3
            if unit in ('year', 'years'):
                months = value.month - 1
                year = value.year + number
            else:
                total = (value.year * 12) + (value.month - 1) + number
                year, months = divmod(total, 12)
            month = months + 1
            # Clamp to the end of a shorter month, as Power Fx does: 31 Jan
            # plus one month is 28 or 29 Feb.
            day = min(value.day, _days_in_month(year, month))
            return value.replace(year=year, month=month, day=day)

        raise PowerFxError(f'Unsupported DateAdd unit: {unit!r}')

    @staticmethod
    def date_part(part: str, args: list):
        """
        Implements `Year`, `Month`, `Day`, `Hour`, `Minute`, `Second` and
        `Weekday`.

        Args:
            part (str): Which part to read.
            args (list): The evaluated arguments.

        Returns:
            int: The requested part.

        Raises:
            PowerFxError: If a Weekday start day is not supported.
        """
        value = to_date(args[0])

        if part == 'weekday':
            # Power Fx numbers the week from Sunday by default.
            start = int(to_number(args[1])) if len(args) == 2 else 1
            if start == 1:
                return (value.isoweekday() % 7) + 1
            if start == 2:
                return value.isoweekday()
            raise PowerFxError(f'Unsupported Weekday start day: {start}')

        if part in ('hour', 'minute', 'second'):
            if not isinstance(value, datetime):
                return 0
            return getattr(value, part)

        return getattr(value, part)

    @staticmethod
    def date_diff(args: list) -> int:
        """
        Implements `DateDiff(start, end, [unit])`.

        Args:
            args (list): The evaluated arguments.

        Returns:
            int: The difference, truncated toward zero, in the given unit.

        Raises:
            PowerFxError: If the argument count or the unit is not supported.
        """
        if len(args) not in (2, 3):
            raise PowerFxError(
                f'DateDiff expects 2 or 3 arguments, got {len(args)}')
        start, end = to_date(args[0]), to_date(args[1])
        if isinstance(start, datetime) != isinstance(end, datetime):
            # Comparing a date with a datetime raises; normalize to datetime.
            start = start if isinstance(start, datetime) \
                else datetime(start.year, start.month, start.day)
            end = end if isinstance(end, datetime) \
                else datetime(end.year, end.month, end.day)
            if start.tzinfo != end.tzinfo:
                start = start.replace(tzinfo=None)
                end = end.replace(tzinfo=None)
        seconds = (end - start).total_seconds()
        unit = to_text(args[2]).lower() if len(args) == 3 else 'days'
        divisors = {
            'second': 1, 'seconds': 1,
            'minute': 60, 'minutes': 60,
            'hour': 3600, 'hours': 3600,
            'day': 86400, 'days': 86400,
        }
        if unit in divisors:
            return int(seconds / divisors[unit])
        if unit in ('year', 'years'):
            return end.year - start.year
        if unit in ('month', 'months'):
            return (end.year - start.year) * 12 + end.month - start.month
        raise PowerFxError(f'Unsupported DateDiff unit: {unit!r}')

    @staticmethod
    def expects(name: str, args, count) -> None:
        """
        Checks a function's argument count.

        Args:
            name (str): The function name, for the error message.
            args: The arguments.
            count (int or tuple): The allowed count, or allowed counts.

        Raises:
            PowerFxError: If the count does not match.
        """
        allowed = count if isinstance(count, tuple) else (count,)
        if len(args) not in allowed:
            expected = ' or '.join(str(x) for x in allowed)
            raise PowerFxError(
                f'{name} expects {expected} arguments, got {len(args)}')


class CompiledPowerFx:
    """
    A parsed Power Fx formula, ready to run against many entities.

    Args:
        formula (str): The formula.

    Raises:
        PowerFxError: If the formula is not valid.
    """

    def __init__(self, formula: str) -> None:
        self.formula = formula
        self.ast = parse(formula)

    def evaluate(self, entity: Any, get_value=None, load_entity_by_code=None) -> Any:
        """
        Evaluates the formula against an entity.

        Args:
            entity: The entity.
            get_value (callable, optional): See `PowerFxRuntime`.
            load_entity_by_code (callable, optional): See `PowerFxRuntime`.

        Returns:
            Any: The value of the formula.
        """
        return PowerFxRuntime(
            entity, get_value, load_entity_by_code).evaluate(self.ast)

    def matches(self, entity: Any, get_value=None, load_entity_by_code=None) -> bool:
        """
        Evaluates the formula as a predicate.

        Args:
            entity: The entity.
            get_value (callable, optional): See `PowerFxRuntime`.
            load_entity_by_code (callable, optional): See `PowerFxRuntime`.

        Returns:
            bool: The truthiness of the formula's value.
        """
        return to_bool(self.evaluate(entity, get_value, load_entity_by_code))

    def __repr__(self) -> str:
        return f'CompiledPowerFx({self.formula!r})'


@lru_cache(maxsize=512)
def compile_powerfx(formula: str) -> CompiledPowerFx:
    """
    Parses a formula, reusing the result for formulas seen before.

    A rule is evaluated once per object, so parsing is cached to keep large
    batches cheap.

    Args:
        formula (str): The formula.

    Returns:
        CompiledPowerFx: The compiled formula.

    Raises:
        PowerFxError: If the formula is not valid.
    """
    return CompiledPowerFx(formula)


def evaluate_powerfx(
    formula: str,
    entity: Any,
    get_value=None,
    load_entity_by_code=None,
) -> Any:
    """
    Evaluates a Power Fx formula against an entity.

    Args:
        formula (str): The formula.
        entity: The entity.
        get_value (callable, optional): See `PowerFxRuntime`.
        load_entity_by_code (callable, optional): See `PowerFxRuntime`.

    Returns:
        Any: The value of the formula.

    Raises:
        PowerFxError: If the formula is not valid or cannot be evaluated.
    """
    return compile_powerfx(formula).evaluate(
        entity, get_value, load_entity_by_code)


def matches_powerfx(
    formula: str,
    entity: Any,
    get_value=None,
    load_entity_by_code=None,
) -> bool:
    """
    Evaluates a Power Fx formula against an entity as a predicate.

    Args:
        formula (str): The formula.
        entity: The entity.
        get_value (callable, optional): See `PowerFxRuntime`.
        load_entity_by_code (callable, optional): See `PowerFxRuntime`.

    Returns:
        bool: True if the formula holds for the entity.

    Raises:
        PowerFxError: If the formula is not valid or cannot be evaluated.
    """
    return compile_powerfx(formula).matches(
        entity, get_value, load_entity_by_code)
