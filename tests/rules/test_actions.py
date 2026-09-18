import pytest

from cluedin.rules.actions import (ActionError, CompiledExpressionAction,
                                   ExpressionActionRuntime,
                                   default_get_action)
from cluedin.rules.powerfx import PowerFxError

SET_NAME = {
    'name': 'Formula Action',
    'type': 'CluedIn.Rules.Actions.ExpressionAction, CluedIn.Rules',
    'properties': [
        {
            'name': 'Expression',
            'value': 'SetVocabularyKeyValue(Entity,"golden.person.firstName","New Name")',
        }
    ],
}


class TestExpressionAction:
    # pylint: disable=missing-docstring

    def test_set_vocabulary_key_value_on_a_flat_entity(self):
        entity = {'golden.person.firstName': 'Robert'}

        default_get_action(SET_NAME)(entity)

        assert entity['golden.person.firstName'] == 'New Name'

    def test_set_vocabulary_key_value_under_properties(self):
        entity = {'Properties': {'golden.person.firstName': 'Robert'}}

        default_get_action(SET_NAME)(entity)

        assert entity['Properties']['golden.person.firstName'] == 'New Name'

    def test_set_entity_property(self):
        entity = {'client.city': 'SINGAPORE'}
        action = CompiledExpressionAction(
            'SetEntityProperty(Entity,"Source","[\'ABC\']");')

        action.apply(entity)

        assert entity['Source'] == "['ABC']"

    def test_trailing_semicolon_is_optional(self):
        assert len(CompiledExpressionAction('SetEntityProperty(Entity,"a",1)')
                   .statements) == 1
        assert len(CompiledExpressionAction('SetEntityProperty(Entity,"a",1);')
                   .statements) == 1

    def test_multiple_statements_run_in_order(self):
        entity = {}
        action = CompiledExpressionAction(
            'SetVocabularyKeyValue(Entity,"a","1");'
            'SetVocabularyKeyValue(Entity,"b","2");'
        )

        action.apply(entity)

        assert entity == {'a': '1', 'b': '2'}

    def test_value_can_be_an_expression_over_the_entity(self):
        entity = {'golden.person.firstName': 'robert'}
        action = CompiledExpressionAction(
            'SetVocabularyKeyValue(Entity,"golden.person.firstName",'
            'Upper(GetVocabularyKeyValue(Entity,"golden.person.firstName")))'
        )

        action.apply(entity)

        assert entity['golden.person.firstName'] == 'ROBERT'

    def test_statements_see_earlier_writes(self):
        entity = {'a': 'x'}
        action = CompiledExpressionAction(
            'SetVocabularyKeyValue(Entity,"a","y");'
            'SetVocabularyKeyValue(Entity,"b",GetVocabularyKeyValue(Entity,"a"));'
        )

        action.apply(entity)

        assert entity['b'] == 'y'

    def test_remove_vocabulary_key(self):
        entity = {'a': 'x'}

        CompiledExpressionAction('RemoveVocabularyKey(Entity,"a")').apply(entity)

        assert entity['a'] is None

    def test_add_tag(self):
        entity = {}

        CompiledExpressionAction('AddTag(Entity,"Reviewed")').apply(entity)

        assert entity['tags'] == ['Reviewed']

    def test_custom_set_value(self):
        entity = {}
        written = {}

        default_get_action(
            SET_NAME,
            set_value=lambda key, value, obj: written.__setitem__(key, value),
        )(entity)

        assert written == {'golden.person.firstName': 'New Name'}
        assert entity == {}

    @pytest.mark.parametrize('expression', [
        '',
        '   ',
        '"just a value"',
        'Entity.Name',
        'SetVocabularyKeyValue(Entity,"a","b") SetVocabularyKeyValue(Entity,"c","d")',
    ])
    def test_rejects_expressions_that_are_not_statements(self, expression):
        with pytest.raises((ActionError, PowerFxError)):
            CompiledExpressionAction(expression)

    @pytest.mark.parametrize('function', [
        'DeleteEverything',
        # Functions that reach into CluedIn's entity model have no equivalent
        # when a rule runs against a plain object.
        'SetEntityName', 'SetEntityType', 'RemoveTag', 'AddAlias',
        'AddEntityCode',
    ])
    def test_unsupported_statement_function_is_rejected_when_parsed(self, function):
        # Parse time, not apply time, so RuleProcessor.prepare can report the
        # rule instead of it failing partway through a batch.
        with pytest.raises(ActionError, match='Unsupported expression action'):
            CompiledExpressionAction(f'{function}(Entity,"x")')

    def test_a_subclass_can_add_a_statement_function(self):
        class Extended(ExpressionActionRuntime):
            # pylint: disable=missing-docstring
            STATEMENTS = ExpressionActionRuntime.STATEMENTS + ('SetEntityName',)

            def call(self, name, args):
                if name.lower() == 'setentityname':
                    args[0]['name'] = args[1]
                    return args[1]
                return super().call(name, args)

        entity = {'name': 'Old'}

        CompiledExpressionAction(
            'SetEntityName(Entity,"New")', Extended).apply(entity)

        assert entity['name'] == 'New'


class TestStandardActions:
    # pylint: disable=missing-docstring

    def test_set_value(self):
        entity = {'client.city': 'SINGAPORE'}
        action = default_get_action({
            'type': 'CluedIn.Rules.Actions.SetValue, CluedIn.Rules',
            'properties': [
                {'name': 'FieldName', 'value': 'client.city'},
                {'name': 'Value', 'value': 'Singapore'},
            ],
        })

        assert action(entity)['client.city'] == 'Singapore'

    def test_add_tag(self):
        entity = {'tags': ['Existing']}
        action = default_get_action({
            'type': 'CluedIn.Rules.Actions.AddTag, CluedIn.Rules',
            'properties': [{'name': 'Value', 'value': 'Equals'}],
        })

        assert action(entity)['tags'] == ['Existing', 'Equals']

    def test_add_tag_is_idempotent(self):
        entity = {'tags': ['Equals']}
        action = default_get_action({
            'type': 'CluedIn.Rules.Actions.AddTag, CluedIn.Rules',
            'properties': [{'name': 'Value', 'value': 'Equals'}],
        })

        assert action(entity)['tags'] == ['Equals']

    def test_unsupported_action_raises(self):
        with pytest.raises(ActionError):
            default_get_action({'type': 'CluedIn.Rules.Actions.Nope, CluedIn.Rules'})

    def test_set_value_without_a_field_name_raises(self):
        with pytest.raises(ActionError):
            default_get_action({
                'type': 'CluedIn.Rules.Actions.SetValue, CluedIn.Rules',
                'properties': [{'name': 'Value', 'value': 'x'}],
            })
