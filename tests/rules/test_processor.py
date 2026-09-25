import pytest

from cluedin.rules import RuleProcessor
from cluedin.rules.processor import describe_unsupported

# pylint: disable=wrong-import-order
from ..ctx import cluedin

FIXTURE = 'tests/fixtures/rules/powerfx.json'


def matching_entity():
    """An entity the fixture's condition accepts: the two names are equal."""
    return {
        'entityType': '/DPerson',
        'golden.person.firstName': 'Smith',
        'golden.person.lastName': 'Smith',
    }


def non_matching_entity():
    """An entity the fixture's condition rejects: the names differ."""
    return {
        'entityType': '/DPerson',
        'golden.person.firstName': 'Robert',
        'golden.person.lastName': 'Smith',
    }


class TestPowerFxCondition:
    # pylint: disable=missing-docstring

    def test_matches_when_the_formula_holds(self):
        rule = cluedin.json.load(FIXTURE)
        evaluator = cluedin.rules.Evaluator(
            rule['data']['management']['rule']['condition'])

        assert evaluator.object_matches_rules(matching_entity()) is True

    def test_does_not_match_when_the_formula_fails(self):
        rule = cluedin.json.load(FIXTURE)
        evaluator = cluedin.rules.Evaluator(
            rule['data']['management']['rule']['condition'])

        assert evaluator.object_matches_rules(non_matching_entity()) is False

    def test_does_not_match_when_the_plain_condition_fails(self):
        # The entity type is ANDed with the formula.
        rule = cluedin.json.load(FIXTURE)
        evaluator = cluedin.rules.Evaluator(
            rule['data']['management']['rule']['condition'])
        entity = matching_entity()
        entity['entityType'] = '/Organization'

        assert evaluator.object_matches_rules(entity) is False

    def test_entity_under_properties(self):
        rule = cluedin.json.load(FIXTURE)
        evaluator = cluedin.rules.Evaluator(
            rule['data']['management']['rule']['condition'])

        assert evaluator.object_matches_rules({
            'entityType': '/DPerson',
            'Properties': {
                'golden.person.firstName': 'Smith',
                'golden.person.lastName': 'Smith',
            },
        }) is True

    def test_custom_get_value_reaches_the_formula(self):
        rule = cluedin.json.load(FIXTURE)

        def get_value(field, obj):
            for part in field.split('.'):
                obj = obj.get(part) if isinstance(obj, dict) else None
                if obj is None:
                    return None
            return obj

        evaluator = cluedin.rules.Evaluator(
            rule['data']['management']['rule']['condition'],
            get_value=get_value)

        assert evaluator.object_matches_rules({
            'entityType': '/DPerson',
            'golden': {'person': {'firstName': 'Smith', 'lastName': 'Smith'}},
        }) is True

    def test_get_matching_objects(self):
        rule = cluedin.json.load(FIXTURE)
        evaluator = cluedin.rules.Evaluator(
            rule['data']['management']['rule']['condition'])

        result = evaluator.get_matching_objects(
            [matching_entity(), non_matching_entity()])

        assert len(result) == 1

    def test_can_explain_is_false_for_a_powerfx_rule(self):
        rule = cluedin.json.load(FIXTURE)
        evaluator = cluedin.rules.Evaluator(
            rule['data']['management']['rule']['condition'])

        assert evaluator.can_explain() is False

    def test_can_explain_is_true_for_an_ordinary_rule(self):
        rule = cluedin.json.load('tests/fixtures/rules/adult-movies.json')
        evaluator = cluedin.rules.Evaluator(
            rule['data']['management']['rule']['condition'])

        assert evaluator.can_explain() is True

    def test_explain_keeps_the_formula_visible(self):
        rule = cluedin.json.load(FIXTURE)
        evaluator = cluedin.rules.Evaluator(
            rule['data']['management']['rule']['condition'])

        result = evaluator.explain()

        assert '@powerfx(' in result
        assert 'GetVocabularyKeyValue' in result


class TestRuleProcessor:
    # pylint: disable=missing-docstring

    def test_applies_the_action_to_a_matching_entity(self):
        processor = RuleProcessor(cluedin.json.load(FIXTURE))

        result = processor.apply(matching_entity())

        assert result['golden.person.firstName'] == 'New Name'

    def test_leaves_a_non_matching_entity_alone(self):
        processor = RuleProcessor(cluedin.json.load(FIXTURE))

        result = processor.apply(non_matching_entity())

        assert result['golden.person.firstName'] == 'Robert'

    def test_reads_the_rule_metadata(self):
        processor = RuleProcessor(cluedin.json.load(FIXTURE))

        assert processor.name == 'PowerFX rule with condition and action'
        assert processor.scope == 'Entity'
        assert len(processor.actions) == 1

    def test_accepts_the_rule_model_directly(self):
        rule = cluedin.json.load(FIXTURE)['data']['management']['rule']

        processor = RuleProcessor(rule)

        assert processor.apply(matching_entity())[
            'golden.person.firstName'] == 'New Name'

    def test_prepare_separates_supported_from_unsupported(self):
        supported = cluedin.json.load(FIXTURE)
        unsupported = cluedin.json.load(FIXTURE)
        unsupported['data']['management']['rule']['rules'][0]['actions'][0][
            'type'] = 'CluedIn.Rules.Actions.Nope, CluedIn.Rules'
        unsupported['data']['management']['rule']['name'] = 'Unsupported'

        processors, skipped = RuleProcessor.prepare([supported, unsupported])

        assert len(processors) == 1
        assert len(skipped) == 1
        assert skipped[0]['name'] == 'Unsupported'
        assert 'Nope' in skipped[0]['reason']

    def test_apply_all_does_not_modify_the_input(self):
        processor = RuleProcessor(cluedin.json.load(FIXTURE))
        entity = matching_entity()

        result = RuleProcessor.apply_all(entity, [processor])

        assert result['golden.person.firstName'] == 'New Name'
        assert entity['golden.person.firstName'] == 'Smith'

    def test_apply_all_isolates_a_failing_rule(self):
        good = RuleProcessor(cluedin.json.load(FIXTURE))

        failing_rule = cluedin.json.load(FIXTURE)
        failing_rule['data']['management']['rule']['rules'][0]['actions'][0][
            'properties'][0]['value'] = \
            'SetVocabularyKeyValue(Entity,"x",1 / 0)'
        failing = RuleProcessor(failing_rule)

        errors = []
        result = RuleProcessor.apply_all(
            matching_entity(),
            [failing, good],
            on_error=lambda processor, exc: errors.append(exc))

        # The good rule still ran, and the failing one left nothing behind.
        assert result['golden.person.firstName'] == 'New Name'
        assert 'x' not in result
        assert len(errors) == 1

    def test_a_processing_rule_condition_gates_its_actions(self):
        rule = cluedin.json.load(FIXTURE)
        rule['data']['management']['rule']['rules'][0]['conditions'] = {
            'objectTypeId': '00000000-0000-0000-0000-000000000000',
            'condition': 'AND',
            'field': None,
            'id': 'x',
            'operator': '00000000-0000-0000-0000-000000000000',
            'rules': [
                {
                    'objectTypeId': '3be85371-cbe0-4180-8820-73e6e37a6c32',
                    'condition': 'AND',
                    'field': 'EntityType',
                    'id': 'y',
                    'operator': '0bafc522-8011-43ba-978a-babe222ba466',
                    'rules': [],
                    'type': 'string',
                    'value': ['/NeverMatches'],
                }
            ],
            'type': None,
            'value': None,
        }
        processor = RuleProcessor(rule)

        result = processor.apply(matching_entity())

        assert result['golden.person.firstName'] == 'Smith'

    def test_describe_unsupported(self):
        rule = cluedin.json.load(FIXTURE)
        rule['data']['management']['rule']['rules'][0]['actions'].append({
            'type': 'CluedIn.Rules.Actions.Nope, CluedIn.Rules',
            'properties': [],
        })

        assert describe_unsupported(rule) == [
            'CluedIn.Rules.Actions.Nope, CluedIn.Rules']

    def test_load_entity_by_code_reaches_the_condition(self):
        rule = cluedin.json.load(FIXTURE)
        rule['data']['management']['rule']['condition']['rules'][1]['value'] = [
            'LoadEntityByEntityCode("/Person#Acme:1").Name = "Robert"'
        ]

        processor = RuleProcessor(
            rule, load_entity_by_code=lambda code: {'Name': 'Robert'})

        assert processor.matches(matching_entity()) is True
