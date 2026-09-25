"""
Runs whole CluedIn rules – condition and actions – against Python objects.

`Evaluator` answers whether an object matches a rule. `RuleProcessor` goes the
step further and applies the rule's actions to the objects that match, which is
what CluedIn itself does during processing.

Rules that use a condition or an action this SDK cannot execute are reported
rather than silently half-applied, so a batch can be split into what can be
reproduced outside CluedIn and what cannot:

```python
processors, skipped = cluedin.rules.RuleProcessor.prepare(rules)

for rule in skipped:
    print(f'SKIPPED: {rule["name"]} -> {rule["reason"]}')

result = cluedin.rules.RuleProcessor.apply_all(obj, processors)
```
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .actions import ActionError, default_get_action, get_action_properties
from .evaluator import Evaluator


def unwrap_rule(rule: Mapping) -> Mapping:
    """
    Accepts either a `get_rule` response or the rule inside it.

    Args:
        rule (Mapping): A `get_rule` response, or a rule model.

    Returns:
        Mapping: The rule model.
    """
    if 'data' in rule and 'management' in rule.get('data', {}):
        return rule['data']['management']['rule']
    return rule


class RuleProcessor:
    """
    An executable CluedIn rule: a condition, plus the actions to apply to the
    objects that satisfy it.

    Args:
        rule (Mapping): A `get_rule` response, or the rule model inside it.
        get_action (callable, optional): `(action_json, **kwargs) -> callable`,
            translating one action. Defaults to `default_get_action`. Override
            it to support an action type this SDK does not.
        evaluator_kwargs (dict, optional): Passed to each `Evaluator`, for
            example `get_operator` or `get_value`.
        **runtime_kwargs: Passed to the action runtime: `get_value`,
            `set_value`, `add_tag`, `load_entity_by_code`.

    Raises:
        ActionError: If an action is not supported.
        ValueError: If a condition operator is not supported.
    """

    def __init__(
        self,
        rule: Mapping,
        get_action=default_get_action,
        evaluator_kwargs: dict = None,
        **runtime_kwargs,
    ) -> None:
        model = unwrap_rule(rule)
        evaluator_kwargs = dict(evaluator_kwargs or {})
        if 'load_entity_by_code' in runtime_kwargs:
            evaluator_kwargs.setdefault(
                'load_entity_by_code', runtime_kwargs['load_entity_by_code'])

        self.id = model.get('id')
        self.name = model.get('name', '<unnamed rule>')
        self.scope = model.get('scope')
        self.order = model.get('order', 0)
        self.is_active = model.get('isActive', True)
        self.evaluator = Evaluator(model['condition'], **evaluator_kwargs)

        # Each child processing rule carries its own extra conditions and its
        # own actions; both have to hold for the actions to run.
        self.steps = []
        for processing_rule in model.get('rules') or []:
            actions = [
                get_action(action, **runtime_kwargs)
                for action in processing_rule.get('actions') or []
            ]
            if not actions:
                continue
            conditions = processing_rule.get('conditions') or {}
            evaluator = None
            if conditions.get('rules'):
                evaluator = Evaluator(conditions, **evaluator_kwargs)
            self.steps.append({
                'name': processing_rule.get('name'),
                'evaluator': evaluator,
                'actions': actions,
            })

    @property
    def actions(self) -> list:
        """Every action callable in the rule, across its processing rules."""
        return [action for step in self.steps for action in step['actions']]

    def matches(self, obj: Any) -> bool:
        """
        Checks whether an object satisfies the rule's condition.

        Args:
            obj: The object to check.

        Returns:
            bool: True if the object matches.
        """
        return self.evaluator.object_matches_rules(obj)

    def apply(self, obj: Any) -> Any:
        """
        Applies the rule's actions to an object, in place, if it matches.

        Args:
            obj: The object to modify.

        Returns:
            Any: The object, modified if it matched.
        """
        if not self.matches(obj):
            return obj
        for step in self.steps:
            if step['evaluator'] is not None \
                    and not step['evaluator'].object_matches_rules(obj):
                continue
            for action in step['actions']:
                obj = action(obj)
        return obj

    @classmethod
    def prepare(cls, rules, **kwargs):
        """
        Builds a processor for every rule that can be executed here, and
        explains why the others cannot.

        Args:
            rules (iterable): `get_rule` responses, or rule models.
            **kwargs: Passed to the constructor.

        Returns:
            tuple: `(processors, skipped)`, where `skipped` holds dicts of
                `id`, `name` and `reason`.
        """
        processors = []
        skipped = []
        for rule in rules:
            model = unwrap_rule(rule)
            try:
                processors.append(cls(model, **kwargs))
            except Exception as exc:  # pylint: disable=broad-except
                skipped.append({
                    'id': model.get('id'),
                    'name': model.get('name', '<unnamed rule>'),
                    'reason': f'{type(exc).__name__}: {exc}',
                })
        return processors, skipped

    @staticmethod
    def apply_all(obj: Any, processors, on_error=None) -> Any:
        """
        Applies a sequence of rules to a copy of an object.

        Each rule is applied atomically: if evaluating or applying one raises,
        that rule's changes are discarded and the remaining rules still run,
        which keeps one unsupported formula from voiding a whole batch.

        Args:
            obj: The object to process. It is not modified.
            processors (iterable): The `RuleProcessor` instances to apply.
            on_error (callable, optional): `(processor, exception) -> None`,
                called for each rule that fails. Failures are silent without
                it.

        Returns:
            Any: A new object with the successful rules applied.
        """
        result = copy.deepcopy(obj)
        for processor in processors:
            candidate = copy.deepcopy(result)
            try:
                candidate = processor.apply(candidate)
            except Exception as exc:  # pylint: disable=broad-except
                if on_error is not None:
                    on_error(processor, exc)
                continue
            result = candidate
        return result

    def __repr__(self) -> str:
        return f'RuleProcessor({self.name!r}, actions={len(self.actions)})'


def describe_unsupported(rule: Mapping) -> list:
    """
    Lists the action types in a rule that this SDK cannot execute.

    Useful to inspect a rule before building a processor for it.

    Args:
        rule (Mapping): A `get_rule` response, or a rule model.

    Returns:
        list: The unsupported action types, sorted and deduplicated.
    """
    model = unwrap_rule(rule)
    unsupported = set()
    for processing_rule in model.get('rules') or []:
        for action in processing_rule.get('actions') or []:
            try:
                default_get_action(action)
            except ActionError:
                unsupported.add(
                    action.get('type') or '<missing action type>')
            except Exception:  # pylint: disable=broad-except
                # A supported type that is misconfigured, such as an
                # expression that does not parse.
                properties = get_action_properties(action)
                unsupported.add(
                    f'{action.get("type")} ({properties})')
    return sorted(unsupported)
