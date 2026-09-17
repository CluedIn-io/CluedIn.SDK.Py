"""Tests for the Power Fx functions and coercions added after the first pass."""

import pytest

from cluedin.rules.powerfx import (PowerFxError, PowerFxRuntime,
                                   evaluate_powerfx)


def ev(formula, entity=None):
    """Evaluates a formula against an empty entity by default."""
    return evaluate_powerfx(formula, entity if entity is not None else {})


class TestNumberCoercion:
    # pylint: disable=missing-docstring

    @pytest.mark.parametrize('formula, expected', [
        ('Value("42")', 42),
        ('Value("4.5")', 4.5),
        ('Value("1,000")', 1000),
        ('Value("1,234.50")', 1234.5),
        ('Value("1,234,567")', 1234567),
        ('Value("50%")', 0.5),
        ('Value("(1,234)")', -1234),
        ('Value("  7  ")', 7),
        ('Value("")', 0),
        ('Value(Blank())', 0),
    ])
    def test_value(self, formula, expected):
        assert ev(formula) == expected

    def test_a_decimal_comma_is_not_treated_as_a_group_separator(self):
        # "1,5" is not grouped (groups are 3 digits), so it must not become 15.
        with pytest.raises(PowerFxError):
            ev('Value("1,5")')

    def test_non_numeric_text_still_raises(self):
        with pytest.raises(PowerFxError):
            ev('Value("abc")')

    def test_integral_floats_render_without_a_decimal_point(self):
        # Power Fx has one number type, so 2.0 reads back as "2".
        assert ev('Text(2.0)') == '2'
        assert ev('1 + 1.0 & ""') == '2'


class TestRounding:
    # pylint: disable=missing-docstring

    @pytest.mark.parametrize('formula, expected', [
        ('Round(0.5)', 1),
        ('Round(1.5)', 2),
        ('Round(2.5)', 3),
        ('Round(-0.5)', -1),
        ('Round(-2.5)', -3),
        ('Round(1.005, 2)', 1.01),
        ('Round(3.14159, 2)', 3.14),
        ('Round(2.675, 2)', 2.68),
    ])
    def test_rounds_half_away_from_zero(self, formula, expected):
        # Python's round() rounds half to even, so round(2.5) is 2. Power Fx
        # and .NET round half away from zero.
        assert ev(formula) == expected


class TestTextFormatting:
    # pylint: disable=missing-docstring

    @pytest.mark.parametrize('formula, expected', [
        ('Text(1234.5, "0.00")', '1234.50'),
        ('Text(1234.5, "#,##0")', '1,235'),
        ('Text(1234.5, "#,##0.00")', '1,234.50'),
        ('Text(0.5, "0.##")', '0.5'),
        ('Text(0.5, "0.00")', '0.50'),
        ('Text(7, "000")', '007'),
        ('Text(-1234.5, "#,##0.00")', '-1,234.50'),
        ('Text(1234567, "#,##0")', '1,234,567'),
    ])
    def test_custom_numeric_patterns(self, formula, expected):
        assert ev(formula) == expected

    @pytest.mark.parametrize('formula, expected', [
        ('Text(1234.5, "N2")', '1,234.50'),
        ('Text(1234.5, "N0")', '1,235'),
        ('Text(1234.5, "F1")', '1234.5'),
        ('Text(0.1234, "P1")', '12.3%'),
        ('Text(5, "D3")', '005'),
        ('Text(255, "X")', 'FF'),
        ('Text(255, "X4")', '00FF'),
    ])
    def test_standard_numeric_specifiers(self, formula, expected):
        assert ev(formula) == expected

    @pytest.mark.parametrize('fmt', ['C2', 'Q', 'yyyy', 'junk'])
    def test_unsupported_numeric_format_raises(self, fmt):
        # Better to raise than to silently emit a number that is not what was
        # asked for.
        with pytest.raises(PowerFxError, match='Unsupported numeric format'):
            ev(f'Text(1234.5, "{fmt}")')

    def test_date_formats_still_work(self):
        assert ev('Text(DateValue("2024-02-26"), "dd MMM yyyy")') == '26 Feb 2024'


class TestConditionals:
    # pylint: disable=missing-docstring

    @pytest.mark.parametrize('formula, expected', [
        ('Switch(2, 1, "a", 2, "b", "z")', 'b'),
        ('Switch(9, 1, "a", 2, "b", "z")', 'z'),
        ('Switch("x", "x", 1, 2)', 1),
        ('Switch(9, 1, "a")', None),
    ])
    def test_switch(self, formula, expected):
        assert ev(formula) == expected

    def test_switch_is_lazy(self):
        assert ev('Switch(1, 1, "taken", 2, 1 / 0)') == 'taken'

    def test_switch_needs_three_arguments(self):
        with pytest.raises(PowerFxError):
            ev('Switch(1, 2)')

    @pytest.mark.parametrize('formula, expected', [
        ('IfError(1 / 0, "safe")', 'safe'),
        ('IfError(5, "safe")', 5),
        ('IfError(1 / 0, 1 / 0, "last")', 'last'),
    ])
    def test_if_error(self, formula, expected):
        assert ev(formula) == expected

    def test_if_error_does_not_evaluate_the_fallback_when_not_needed(self):
        assert ev('IfError("ok", 1 / 0)') == 'ok'

    @pytest.mark.parametrize('formula, expected', [
        ('IsError(1 / 0)', True),
        ('IsError(1)', False),
        ('IsError(Blank())', False),
    ])
    def test_is_error(self, formula, expected):
        assert ev(formula) is expected


class TestRegex:
    # pylint: disable=missing-docstring

    @pytest.mark.parametrize('formula, expected', [
        ('IsMatch("abc", "a.c")', True),
        # IsMatch matches the whole text by default.
        ('IsMatch("xabcx", "a.c")', False),
        ('IsMatch("xabcx", "a.c", "Contains")', True),
        ('IsMatch("abcx", "a.c", "BeginsWith")', True),
        ('IsMatch("xabc", "a.c", "EndsWith")', True),
        ('IsMatch("ABC", "abc", "IgnoreCase")', True),
        ('IsMatch("xABCx", "abc", "Contains,IgnoreCase")', True),
        ('IsMatch("abc", "\\d+")', False),
        ('IsMatch("123", "\\d+")', True),
    ])
    def test_is_match(self, formula, expected):
        assert ev(formula) is expected

    def test_matchoptions_prefix_is_accepted(self):
        assert ev('IsMatch("xabcx", "a.c", "MatchOptions.Contains")') is True

    def test_unknown_option_raises(self):
        with pytest.raises(PowerFxError, match='Unsupported IsMatch option'):
            ev('IsMatch("a", "a", "Sideways")')

    def test_invalid_pattern_raises(self):
        with pytest.raises(PowerFxError, match='Invalid regular expression'):
            ev('IsMatch("a", "(")')


class TestTextFunctions:
    # pylint: disable=missing-docstring

    @pytest.mark.parametrize('formula, expected', [
        ('Find("b", "abc")', 2),
        ('Find("a", "abc")', 1),
        ('Find("z", "abc")', None),
        ('Find("a", "abcabc", 2)', 4),
        ('Char(65)', 'A'),
        ('EncodeUrl("a b&c")', 'a%20b%26c'),
    ])
    def test_functions(self, formula, expected):
        assert ev(formula) == expected

    def test_split_returns_a_list(self):
        assert ev('Split("a,b,c", ",")') == ['a', 'b', 'c']

    def test_split_works_with_countrows_and_comparison(self):
        assert ev('CountRows(Split("a,b,c", ","))') == 3
        # Lists compare with ANY semantics, as multi-valued properties do.
        assert ev('Split("a,b,c", ",") = "b"') is True

    def test_char_out_of_range_raises(self):
        with pytest.raises(PowerFxError, match='Char is out of range'):
            ev('Char(0)')


class TestMath:
    # pylint: disable=missing-docstring

    @pytest.mark.parametrize('formula, expected', [
        ('Sum(1, 2, 3)', 6),
        ('Max(1, 5, 3)', 5),
        ('Min(1, 5, 3)', 1),
        ('Average(2, 4)', 3),
        ('Int(1.7)', 1),
        ('Int(-1.7)', -2),
        ('Trunc(1.7)', 1),
        ('Trunc(-1.7)', -1),
        ('Trunc(1.789, 2)', 1.78),
        ('Mod(5, 2)', 1),
        ('Mod(-1, 3)', 2),
        ('Power(2, 10)', 1024),
        ('Sqrt(9)', 3),
    ])
    def test_functions(self, formula, expected):
        assert ev(formula) == expected

    def test_aggregates_ignore_blanks(self):
        assert ev('Sum(1, Blank(), 2)') == 3

    def test_aggregates_flatten_lists(self):
        assert ev('Sum(Split("1,2,3", ","))') == 6

    def test_sum_of_nothing_is_zero_and_max_of_nothing_is_blank(self):
        assert ev('Sum(Blank())') == 0
        assert ev('Max(Blank())') is None

    def test_mod_by_zero_raises(self):
        with pytest.raises(PowerFxError, match='Mod by zero'):
            ev('Mod(1, 0)')

    def test_sqrt_of_a_negative_raises(self):
        with pytest.raises(PowerFxError, match='Sqrt of a negative'):
            ev('Sqrt(-1)')


class TestBoolean:
    # pylint: disable=missing-docstring

    @pytest.mark.parametrize('formula, expected', [
        ('Boolean("true")', True),
        ('Boolean("TRUE")', True),
        ('Boolean("false")', False),
        ('Boolean("1")', True),
        ('Boolean(0)', False),
        ('Boolean(2)', True),
        ('Boolean(Blank())', None),
    ])
    def test_boolean(self, formula, expected):
        assert ev(formula) is expected

    def test_non_boolean_text_raises(self):
        with pytest.raises(PowerFxError, match='is not a boolean'):
            ev('Boolean("yes")')


class TestDateFunctions:
    # pylint: disable=missing-docstring

    @pytest.mark.parametrize('formula, expected', [
        ('Year(DateValue("2024-02-26"))', 2024),
        ('Month(DateValue("2024-02-26"))', 2),
        ('Day(DateValue("2024-02-26"))', 26),
        ('Hour(DateTimeValue("2024-02-26T13:45:07"))', 13),
        ('Minute(DateTimeValue("2024-02-26T13:45:07"))', 45),
        ('Second(DateTimeValue("2024-02-26T13:45:07"))', 7),
    ])
    def test_date_parts(self, formula, expected):
        assert ev(formula) == expected

    def test_time_parts_of_a_plain_date_are_zero(self):
        assert ev('Hour(DateValue("2024-02-26"))') == 0

    @pytest.mark.parametrize('day, expected', [
        # 2024-02-25 is a Sunday, which Power Fx numbers 1 by default.
        ('2024-02-25', 1),
        ('2024-02-26', 2),
        ('2024-03-02', 7),
    ])
    def test_weekday_starts_on_sunday(self, day, expected):
        assert ev(f'Weekday(DateValue("{day}"))') == expected

    def test_weekday_can_start_on_monday(self):
        assert ev('Weekday(DateValue("2024-02-25"), 2)') == 7

    @pytest.mark.parametrize('formula, expected', [
        ('DateAdd(DateValue("2024-02-26"), 5)', '2024-03-02'),
        ('DateAdd(DateValue("2024-02-26"), -5)', '2024-02-21'),
        ('DateAdd(DateValue("2024-02-26"), 1, "months")', '2024-03-26'),
        ('DateAdd(DateValue("2024-02-26"), -1, "years")', '2023-02-26'),
        ('DateAdd(DateValue("2024-11-15"), 1, "quarters")', '2025-02-15'),
        # Clamps to the end of a shorter month.
        ('DateAdd(DateValue("2024-01-31"), 1, "months")', '2024-02-29'),
        ('DateAdd(DateValue("2023-01-31"), 1, "months")', '2023-02-28'),
        # Leap day plus a year has no 29 February to land on.
        ('DateAdd(DateValue("2024-02-29"), 1, "years")', '2025-02-28'),
    ])
    def test_date_add(self, formula, expected):
        assert ev(f'Text({formula}, "yyyy-MM-dd")') == expected

    def test_date_add_with_a_time_unit_promotes_a_date(self):
        assert ev('Hour(DateAdd(DateValue("2024-02-26"), 3, "hours"))') == 3

    def test_unsupported_unit_raises(self):
        with pytest.raises(PowerFxError, match='Unsupported DateAdd unit'):
            ev('DateAdd(Today(), 1, "fortnights")')


class TestDeclaredFunctions:
    # pylint: disable=missing-docstring

    def test_every_declared_function_is_dispatched(self):
        # FUNCTIONS documents the supported set and the README repeats it, but
        # dispatch lives in call(). This keeps the two from drifting apart.
        undispatched = []
        for name in PowerFxRuntime.FUNCTIONS:
            try:
                evaluate_powerfx(f'{name}()', {})
            except PowerFxError as exc:
                if 'Unsupported Power Fx function' in str(exc):
                    undispatched.append(name)
            except Exception:  # pylint: disable=broad-except
                pass

        assert not undispatched

    def test_declared_functions_are_sorted_and_unique(self):
        names = list(PowerFxRuntime.FUNCTIONS)

        assert names == sorted(names, key=str.lower)
        assert len(names) == len(set(names))
