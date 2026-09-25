import json
from typing import Any, Mapping, Optional

from .operators import default_get_operator, pandas_get_operator
from .powerfx import get_member as powerfx_get_member
from .powerfx import matches_powerfx
from .rule import Rule
from .rule_group import RuleGroup

# CluedIn identifies a Power Fx condition by its objectTypeId. Such a condition
# carries no field and its operator is the empty GUID, so it cannot be told
# apart from a malformed ordinary condition by any other means.
POWERFX_OBJECT_TYPE_ID = '96102979-e952-43d8-afe6-987676c0698b'


def get_powerfx_formula(rule_object: dict) -> Optional[str]:
    """
    Returns the Power Fx formula of a condition, if it is a Power Fx condition.

    Args:
        rule_object (dict): A condition from a rule's `condition` tree.

    Returns:
        str: The formula, or None if this is not a Power Fx condition.
    """
    if str(rule_object.get('objectTypeId', '')).lower() != POWERFX_OBJECT_TYPE_ID:
        return None
    value = rule_object.get('value')
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None or not str(value).strip():
        return None
    return str(value)


def default_get_property_name(field: Optional[str]) -> Optional[str]:
    """
    Returns the property name for a given field.
    Used to map CluedIn Rules fields to your fields.

    Args:
        field (str): The field name.

    Returns:
        str: The property name.

    """
    if field is None:
        return None
    if field == "EntityType":
        field = "entityType"
    return field.replace("Properties[", "").replace("]", "")


def default_get_value(field: str, obj: dict) -> Any:
    """
    Get the value of a field from a dictionary object.

    Args:
        field (str): The field name.
        obj (dict): The dictionary object.

    Returns:
        Any: The value of the field in the dictionary object.
    """
    return obj.get(field)


class Evaluator:
    """
    The Evaluator class is responsible for evaluating rules against objects and returning
    a list of objects that match the rules.

    Args:
        rule_set (str or list): The rule set to be evaluated. It can be either a JSON string
            representing the rule set or a list of rule objects.
        get_operator (function, optional): A function that returns the operator based on the
            operator ID. Defaults to default_get_operator.
        get_property_name (function, optional): A function that returns the property name based
            on the field ID. Defaults to default_get_property_name.
        get_value (function, optional): A function that returns the value based on the property
            name and the object. Defaults to default_get_value.
        load_entity_by_code (function, optional): A function that loads an entity by its entity
            code, used by the Power Fx `LoadEntityByEntityCode` function. Without it, a formula
            calling that function raises PowerFxError.

    Attributes:
        rule_group (RuleGroup): The rule group representing the rule set.

    Methods:
        get_matching_objects(objects): Returns a list of objects that match the rules.
        object_matches_rules(obj): Checks if the given object matches the rules.
        explain(): Generates a pandas query string based on the rules.

    Raises:
        ValueError: If the condition of the rule group is invalid.
    """

    def __init__(
        self,
        rule_set,
        get_operator=default_get_operator,
        get_property_name=default_get_property_name,
        get_value=default_get_value,
        load_entity_by_code=None,
    ):
        self.get_operator = get_operator
        self.get_property_name = get_property_name
        self.get_value = get_value
        self.load_entity_by_code = load_entity_by_code
        if isinstance(rule_set, str):
            self.rule_group = RuleGroup(json.loads(rule_set))
        else:
            self.rule_group = RuleGroup(rule_set)

    def get_matching_objects(self, objects) -> list:
        """
        Returns a list of objects that match the rules.

        Args:
            objects (list): The list of objects to be evaluated.

        Returns:
            list: A list of objects that match the rules.
        """
        return list(filter(self.object_matches_rules, objects))

    def object_matches_rules(self, obj) -> bool:
        """
        Checks if the given object matches the rules defined in the rule group.

        Args:
            obj: The object to be evaluated against the rules.

        Returns:
            bool: True if the object matches the rules, False otherwise.
        """
        return self.__evaluate_rule_group(self.rule_group, obj)

    def __evaluate_rule_group(self, rule_group, obj):
        """
        Evaluates a rule group based on the given condition and rules.

        Args:
            rule_group (RuleGroup): The rule group to evaluate.
            obj (object): The object to evaluate against the rules.

        Returns:
            bool: True if the rule group evaluates to True, False otherwise.

        Raises:
            ValueError: If the condition of the rule group is invalid.
        """
        if rule_group.condition == "AND":
            return all(
                map(lambda x: self.__evaluate_rule_object(
                    x, obj), rule_group.rules)
            )
        if rule_group.condition == "OR":
            return any(
                map(lambda x: self.__evaluate_rule_object(
                    x, obj), rule_group.rules)
            )
        raise ValueError(f"Invalid condition: {rule_group.condition}")

    def __evaluate_rule(self, rule: Rule, obj: dict) -> bool:
        """
        Evaluates a rule against an object.

        Args:
            rule (Rule): The rule to evaluate.
            obj (Object): The object to evaluate the rule against.

        Returns:
            bool: True if the rule is satisfied, False otherwise.
        """
        return self.get_operator(rule.operator_id)(
            # left - value from the evaluated object
            rule.typecast_value(
                self.get_value(self.get_property_name(rule.field), obj)
            ),
            # right - value from the rule
            rule.get_value(),
            obj,
        )

    def powerfx_get_value(self, key: str, entity) -> Any:
        """
        Reads a vocabulary key for the Power Fx `GetVocabularyKeyValue`
        function, so that a formula sees the same fields as the rest of the
        rule, including any custom `get_property_name`/`get_value`.

        Args:
            key (str): The vocabulary key.
            entity: The entity to read from.

        Returns:
            Any: The value, or None if the key is not set.
        """
        try:
            value = self.get_value(self.get_property_name(key), entity)
        except (AttributeError, TypeError):
            value = None
        if value is not None:
            return value
        # Fall back to the CluedIn shape, where vocabulary keys sit under
        # Properties rather than at the top level.
        properties = powerfx_get_member(entity, 'Properties')
        if isinstance(properties, Mapping):
            return powerfx_get_member(properties, key)
        return None

    def __evaluate_powerfx(self, formula: str, obj) -> bool:
        """
        Evaluates a Power Fx condition against an object.

        Args:
            formula (str): The Power Fx formula.
            obj: The object to evaluate the formula against.

        Returns:
            bool: True if the formula holds for the object.
        """
        return matches_powerfx(
            formula,
            obj,
            get_value=self.powerfx_get_value,
            load_entity_by_code=self.load_entity_by_code,
        )

    def __evaluate_rule_object(self, rule_object: dict, obj) -> bool:
        """
        Evaluates a rule object against the given object.

        Args:
            rule_object (dict): The rule object to evaluate.
            obj: The object to evaluate the rule against.

        Returns:
            The result of the evaluation.
        """
        if "rules" in rule_object and len(rule_object["rules"]) > 0:
            return self.__evaluate_rule_group(RuleGroup(rule_object), obj)
        formula = get_powerfx_formula(rule_object)
        if formula is not None:
            return self.__evaluate_powerfx(formula, obj)
        return self.__evaluate_rule(Rule(rule_object), obj)

    def __explain_rule_object(self, rule_object):
        """
        Generates a pandas query string based on the given rule.

        Args:
            rule (Rule): The rule to generate the query for.

        Returns:
            str: The pandas query string.
        """
        if "rules" in rule_object and len(rule_object["rules"]) > 0:
            return self.__explain_rule_group(RuleGroup(rule_object))
        formula = get_powerfx_formula(rule_object)
        if formula is not None:
            # A Power Fx formula has no pandas equivalent. Emit it verbatim so
            # the explanation stays complete and visibly not runnable, rather
            # than silently dropping a condition from the query.
            return f'@powerfx({formula})'
        return self.__explain_rule(Rule(rule_object))

    def __explain_rule(self, rule):
        """
        Generates a pandas query string based on the given rule.

        Args:
            rule (Rule): The rule to generate the query for.

        Returns:
            str: The pandas query string.
        """
        # return f"{rule.field} {rule.operator_id} {rule.get_value()}"
        if rule.type in ["string", "datetime", "date"]:
            return pandas_get_operator(
                # pylint: disable=line-too-long
                f"`{self.get_property_name(rule.field)}`",
                rule.operator_id,
                f'"{rule.get_value()}"',
            )
        return pandas_get_operator(
            f"`{self.get_property_name(rule.field)}`",
            rule.operator_id,
            rule.get_value(),
        )

    def __explain_rule_group(self, rule_group):
        """
        Generates a pandas query string based on the given rule group.

        Args:
            rule_group (RuleGroup): The rule group to generate the query for.

        Returns:
            str: The pandas query string.
        """
        if rule_group.condition == "AND":
            return " & ".join(map(self.__explain_rule_object, rule_group.rules))
        if rule_group.condition == "OR":
            return " | ".join(map(self.__explain_rule_object, rule_group.rules))
        raise ValueError(f"Invalid condition: {rule_group.condition}")

    def explain(self) -> str:
        """
        Generates a pandas query string based on the rules.

        A Power Fx condition has no pandas equivalent and is emitted as
        `@powerfx(<formula>)`, which pandas cannot run. Use `can_explain` to
        check before passing the result to `DataFrame.query`.
        """
        return f"df.query('{self.__explain_rule_group(self.rule_group)}')"

    def can_explain(self) -> bool:
        """
        Checks whether `explain` produces a query pandas can actually run.

        Returns:
            bool: False if any condition is a Power Fx formula, which has no
                pandas equivalent.
        """
        def is_translatable(rule_object) -> bool:
            if "rules" in rule_object and len(rule_object["rules"]) > 0:
                return all(map(is_translatable, rule_object["rules"]))
            return get_powerfx_formula(rule_object) is None

        return all(map(is_translatable, self.rule_group.rules))
