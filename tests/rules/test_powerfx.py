from datetime import date, datetime

import pytest

from cluedin.rules.powerfx import (PowerFxError, compile_powerfx,
                                   evaluate_powerfx, matches_powerfx)


class TestPowerFxExpressions:
    # pylint: disable=missing-docstring

    @pytest.mark.parametrize('formula, expected', [
        ('1 + 2', 3),
        ('10 / 4', 2.5),
        ('2 * 3 + 1', 7),
        ('1 + 2 * 3', 7),
        ('(1 + 2) * 3', 9),
        ('10 - 3 - 2', 5),
        ('-5 + 1', -4),
        ('"a" & "b" & "c"', 'abc'),
        ('1 = 1', True),
        ('1 <> 2', True),
        ('2 > 1', True),
        ('1 >= 1', True),
        ('true And false', False),
        ('true Or false', True),
        ('Not true', False),
        ('!false', True),
        ('true && true', True),
        ('false || true', True),
    ])
    def test_operators(self, formula, expected):
        assert evaluate_powerfx(formula, {}) == expected

    def test_left_associative_subtraction(self):
        # A right-associative parse would give 9.
        assert evaluate_powerfx('10 - 3 - 2', {}) == 5

    def test_identifier_is_not_lexed_across_a_minus(self):
        # `a-1` must not lex as a single identifier named "a-1".
        assert evaluate_powerfx('Len("abc")-1', {}) == 2

    @pytest.mark.parametrize('formula, expected', [
        ('Left("Robert", 3)', 'Rob'),
        ('Right("Robert", 3)', 'ert'),
        ('Right("Robert", 0)', ''),
        ('Mid("Robert", 2, 3)', 'obe'),
        ('Mid("Robert", 2)', 'obert'),
        ('Len("Robert")', 6),
        ('Lower("RoBert")', 'robert'),
        ('Upper("robert")', 'ROBERT'),
        ('Proper("robert smith")', 'Robert Smith'),
        ('Trim("  a   b  ")', 'a b'),
        ('StartsWith("Robert", "rob")', True),
        ('EndsWith("Robert", "ERT")', True),
        ('Substitute("a-b-c", "-", "+")', 'a+b+c'),
        ('Substitute("a-b-c", "-", "+", 2)', 'a-b+c'),
        ('Replace("abcdef", 2, 3, "X")', 'aXef'),
        ('Concatenate("a", "b", "c")', 'abc'),
        ('Value("42")', 42),
        ('Value("4.5")', 4.5),
        ('Abs(-3)', 3),
        ('Round(3.14159, 2)', 3.14),
        ('IsBlank(Blank())', True),
        ('IsBlank("")', True),
        ('IsBlank("a")', False),
        ('Coalesce(Blank(), "", "x")', 'x'),
        ('CountRows(Blank())', 0),
    ])
    def test_functions(self, formula, expected):
        assert evaluate_powerfx(formula, {}) == expected

    def test_string_escaping(self):
        assert evaluate_powerfx('"say ""hi"""', {}) == 'say "hi"'

    def test_if_is_lazy(self):
        # The untaken branch must not be evaluated; if it were, the division
        # by zero would raise.
        assert evaluate_powerfx('If(false, 1 / 0, "safe")', {}) == 'safe'

    def test_if_chained(self):
        formula = 'If(false, "a", true, "b", "c")'
        assert evaluate_powerfx(formula, {}) == 'b'

    def test_if_without_else_is_blank(self):
        assert evaluate_powerfx('If(false, "a")', {}) is None

    def test_and_or_short_circuit(self):
        assert evaluate_powerfx('false And (1 / 0) = 1', {}) is False
        assert evaluate_powerfx('true Or (1 / 0) = 1', {}) is True

    def test_not_as_a_function(self):
        # `Not(x)` is a call, not the prefix operator.
        assert evaluate_powerfx('Not(true)', {}) is False

    def test_and_or_as_functions(self):
        assert evaluate_powerfx('And(true, true, false)', {}) is False
        assert evaluate_powerfx('Or(false, false, true)', {}) is True

    def test_is_blank_or_error_swallows_errors(self):
        assert evaluate_powerfx('IsBlankOrError(1 / 0)', {}) is True

    def test_division_by_zero_raises(self):
        with pytest.raises(PowerFxError):
            evaluate_powerfx('1 / 0', {})

    def test_in_ignores_case_and_exactin_does_not(self):
        assert evaluate_powerfx('"OB" in "Robert"', {}) is True
        assert evaluate_powerfx('"OB" exactin "Robert"', {}) is False
        assert evaluate_powerfx('"ob" exactin "Robert"', {}) is True

    def test_dates(self):
        assert evaluate_powerfx(
            'DateValue("2024-02-26")', {}) == date(2024, 2, 26)
        assert evaluate_powerfx(
            'DateDiff(DateValue("2024-01-01"), DateValue("2024-01-31"))',
            {}) == 30
        assert evaluate_powerfx(
            'DateDiff(DateValue("2024-01-01"), DateValue("2025-01-01"), "years")',
            {}) == 1
        assert isinstance(evaluate_powerfx('Today()', {}), date)
        assert isinstance(evaluate_powerfx('Now()', {}), datetime)

    def test_text_formats_dates(self):
        formula = 'Text(DateValue("2024-02-26"), "yyyy-MM-dd")'
        assert evaluate_powerfx(formula, {}) == '2024-02-26'

    def test_text_format_does_not_clobber_month_names(self):
        # A naive replace of "MM" would corrupt "MMM".
        formula = 'Text(DateValue("2024-02-26"), "dd MMM yyyy")'
        assert evaluate_powerfx(formula, {}) == '26 Feb 2024'

    def test_quoted_identifiers(self):
        entity = {'Properties': {'a key': 'value'}}
        assert evaluate_powerfx("Entity.Properties.'a key'", entity) == 'value'


class TestPowerFxEntities:
    # pylint: disable=missing-docstring

    def test_entity_member_access_ignores_case(self):
        assert evaluate_powerfx('Entity.Name', {'name': 'Robert'}) == 'Robert'

    def test_missing_member_is_blank(self):
        assert evaluate_powerfx('Entity.Nope', {'name': 'Robert'}) is None

    def test_nested_member_access(self):
        entity = {'Properties': {'finance': {'salary': 120000}}}
        assert evaluate_powerfx(
            'Entity.Properties.finance.salary', entity) == 120000

    def test_unknown_root_identifier_raises(self):
        with pytest.raises(PowerFxError):
            evaluate_powerfx('Foo.Bar', {})

    def test_vocabulary_key_on_a_flat_entity(self):
        entity = {'golden.person.firstName': 'Robert'}
        formula = 'GetVocabularyKeyValue(Entity,"golden.person.firstName")'
        assert evaluate_powerfx(formula, entity) == 'Robert'

    def test_vocabulary_key_under_properties(self):
        entity = {'Properties': {'golden.person.firstName': 'Robert'}}
        formula = 'GetVocabularyKeyValue(Entity,"golden.person.firstName")'
        assert evaluate_powerfx(formula, entity) == 'Robert'

    def test_missing_vocabulary_key_is_blank(self):
        formula = 'GetVocabularyKeyValue(Entity,"nope")'
        assert evaluate_powerfx(formula, {'a': 1}) is None

    def test_custom_get_value(self):
        entity = {'golden': {'person': {'firstName': 'Robert'}}}

        def get_value(key, obj):
            for part in key.split('.'):
                obj = obj.get(part) if isinstance(obj, dict) else None
                if obj is None:
                    return None
            return obj

        formula = 'GetVocabularyKeyValue(Entity,"golden.person.firstName")'
        assert evaluate_powerfx(formula, entity, get_value=get_value) == 'Robert'

    def test_load_entity_by_entity_code(self):
        formula = 'LoadEntityByEntityCode("/Person#Acme:1").Name'
        assert evaluate_powerfx(
            formula, {},
            load_entity_by_code=lambda code: {'Name': 'Robert'}) == 'Robert'

    def test_load_entity_by_entity_code_requires_a_callback(self):
        with pytest.raises(PowerFxError):
            evaluate_powerfx('LoadEntityByEntityCode("x")', {})

    def test_multi_valued_property_matches_any(self):
        entity = {'imdb.title.genres': ['Crime', 'Drama']}
        formula = 'GetVocabularyKeyValue(Entity,"imdb.title.genres") = "Drama"'
        assert matches_powerfx(formula, entity) is True

    def test_multi_valued_property_not_equal_requires_all(self):
        entity = {'imdb.title.genres': ['Crime', 'Drama']}
        formula = 'GetVocabularyKeyValue(Entity,"imdb.title.genres") <> "Drama"'
        assert matches_powerfx(formula, entity) is False


class TestPowerFxSafety:
    # pylint: disable=missing-docstring

    @pytest.mark.parametrize('formula', [
        '__import__("os").system("echo hi")',
        'open("secrets.txt")',
        'eval("1+1")',
        'Len("a") ; Len("b")',
        '1 +',
        '"unterminated',
        'Unsupported(1)',
    ])
    def test_rejects_anything_outside_the_subset(self, formula):
        with pytest.raises((PowerFxError, ValueError)):
            evaluate_powerfx(formula, {})

    def test_dunder_members_are_not_reachable(self):
        # `Entity.__class__` parses as a name, but member access on a dict
        # resolves keys, not Python attributes, so it is simply blank.
        assert evaluate_powerfx('Entity.__class__', {'a': 1}) is None

    def test_compilation_is_cached(self):
        first = compile_powerfx('1 = 1')
        second = compile_powerfx('1 = 1')
        assert first is second
