"""
Executable Python equivalents of CluedIn Rule actions.

A rule's `rules[].actions[]` entries become callables that take an object and
return it, modified. Three action types are supported out of the box:

- `CluedIn.Rules.Actions.SetValue` – sets a property to a constant.
- `CluedIn.Rules.Actions.AddTag` – appends a tag.
- `CluedIn.Rules.Actions.ExpressionAction` – runs a Power Fx formula action,
  such as `SetVocabularyKeyValue(Entity,"golden.person.firstName","New Name")`.

Expression actions are statements rather than predicates, so they are handled
here rather than in `powerfx`, which evaluates expressions. Their arguments are
ordinary Power Fx expressions and are evaluated by that same sandboxed runtime.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from .powerfx import (
    Call,
    Name,
    Parser,
    PowerFxError,
    PowerFxRuntime,
    get_member,
    to_text,
)

SET_VALUE_ACTION = 'CluedIn.Rules.Actions.SetValue, CluedIn.Rules'
ADD_TAG_ACTION = 'CluedIn.Rules.Actions.AddTag, CluedIn.Rules'
EXPRESSION_ACTION = 'CluedIn.Rules.Actions.ExpressionAction, CluedIn.Rules'


class ActionError(ValueError):
    """Raised when a rule action cannot be translated or applied."""


def get_action_properties(action_json: Mapping) -> dict:
    """
    Flattens an action's `properties` list into a name-to-value dictionary.

    Args:
        action_json (Mapping): The action, as returned by `get_rule`.

    Returns:
        dict: The action's properties by name.
    """
    return {
        prop['name']: prop.get('value')
        for prop in action_json.get('properties') or []
        if 'name' in prop
    }


# ---------------------------------------------------------------------------
# Power Fx expression actions
# ---------------------------------------------------------------------------

def default_set_value(key: str, value: Any, obj: Any) -> None:
    """
    Writes a vocabulary key onto an object.

    If the object carries a `Properties` mapping, the key is written there,
    matching the shape CluedIn returns. Otherwise it is written as a top-level
    key, matching the flattened shape `cluedin.gql.entries(flat=True)` returns.

    Args:
        key (str): The vocabulary key or property name.
        value: The value to write.
        obj: The object to modify.

    Raises:
        ActionError: If the object cannot be written to.
    """
    properties = get_member(obj, 'Properties')
    if isinstance(properties, dict):
        properties[key] = value
        return
    if isinstance(obj, dict):
        obj[key] = value
        return
    raise ActionError(
        f'Cannot set {key!r} on an object of type {type(obj).__name__}.')


def default_add_tag(tag: str, obj: Any) -> None:
    """
    Appends a tag to an object's `tags` list, creating it if needed.

    Args:
        tag (str): The tag to add.
        obj: The object to modify.

    Raises:
        ActionError: If the object cannot be written to.
    """
    if not isinstance(obj, dict):
        raise ActionError(
            f'Cannot add a tag to an object of type {type(obj).__name__}.')
    for candidate in ('tags', 'Tags'):
        if candidate in obj:
            tags = obj[candidate]
            if isinstance(tags, list):
                if tag not in tags:
                    tags.append(tag)
                return
            obj[candidate] = [tags, tag] if tags is not None else [tag]
            return
    obj['tags'] = [tag]


class ExpressionActionRuntime(PowerFxRuntime):
    """
    A Power Fx runtime that also permits the statement functions a CluedIn
    Formula Action may call.

    Args:
        entity: The object the action modifies.
        get_value (callable, optional): See `PowerFxRuntime`.
        set_value (callable, optional): `(key, value, entity) -> None`, used to
            write a vocabulary key. Defaults to `default_set_value`.
        add_tag (callable, optional): `(tag, entity) -> None`. Defaults to
            `default_add_tag`.
        load_entity_by_code (callable, optional): See `PowerFxRuntime`.
    """

    STATEMENTS = (
        'AddTag', 'RemoveVocabularyKey', 'SetEntityProperty',
        'SetVocabularyKeyValue',
    )

    def __init__(
        self,
        entity: Any,
        get_value: Optional[Callable[[str, Any], Any]] = None,
        set_value: Optional[Callable[[str, Any, Any], None]] = None,
        add_tag: Optional[Callable[[str, Any], None]] = None,
        load_entity_by_code: Optional[Callable[[str], Any]] = None,
    ) -> None:
        super().__init__(entity, get_value, load_entity_by_code)
        self.set_value = set_value or default_set_value
        self.add_tag = add_tag or default_add_tag

    def call(self, name: str, args: list) -> Any:
        """
        Dispatches a statement function, falling back to the expression
        functions of the base runtime.

        Args:
            name (str): The function name as written.
            args (list): The evaluated arguments.

        Returns:
            Any: The value written, for statements; otherwise the base result.

        Raises:
            PowerFxError: If the function is not supported or is misused.
        """
        key = name.lower()

        if key in ('setvocabularykeyvalue', 'setentityproperty'):
            self.expects(name, args, 3)
            target, vocabulary_key, value = args
            self.set_value(to_text(vocabulary_key), value, target)
            return value

        if key == 'removevocabularykey':
            self.expects(name, args, 2)
            target, vocabulary_key = args
            self.set_value(to_text(vocabulary_key), None, target)
            return None

        if key == 'addtag':
            self.expects(name, args, 2)
            target, tag = args
            self.add_tag(to_text(tag), target)
            return tag

        return super().call(name, args)


class CompiledExpressionAction:
    """
    A parsed CluedIn Formula Action: one or more `;`-separated Power Fx
    statements, such as `SetVocabularyKeyValue(Entity,"a","b");`.

    Args:
        expression (str): The expression from the action's `Expression`
            property.
        runtime_class (type, optional): The runtime whose `STATEMENTS` the
            expression is checked against, and which runs it. Defaults to
            `ExpressionActionRuntime`. Subclass it to support a statement
            function this SDK does not.

    Raises:
        PowerFxError: If the expression is not valid.
        ActionError: If a statement is not a call to a supported statement
            function.
    """

    def __init__(self, expression: str, runtime_class=None) -> None:
        self.expression = expression
        self.runtime_class = runtime_class or ExpressionActionRuntime
        self.statements = self.parse_statements(expression, self.runtime_class)

    @staticmethod
    def parse_statements(expression: str, runtime_class=None) -> list:
        """
        Parses `;`-separated statements into a list of AST nodes.

        The statement name is checked here rather than when the action runs,
        so that an unsupported formula is reported while rules are being
        prepared instead of failing partway through a batch.

        Args:
            expression (str): The expression.
            runtime_class (type, optional): The runtime whose `STATEMENTS` to
                accept. Defaults to `ExpressionActionRuntime`.

        Returns:
            list: The parsed statement nodes.

        Raises:
            PowerFxError: If a statement is not valid.
            ActionError: If a statement is not a function call, or calls a
                function that is not a supported statement. An expression
                action has to do something; a bare value would be discarded.
        """
        runtime_class = runtime_class or ExpressionActionRuntime
        supported = {name.lower() for name in runtime_class.STATEMENTS}

        parser = Parser(expression)
        statements = []
        while parser.current.kind != 'EOF':
            if parser.match('SEMICOLON'):
                # Tolerate empty statements, including a trailing semicolon.
                continue
            node = parser.expression(0)
            if not isinstance(node, Call):
                raise ActionError(
                    f'An expression action must be a function call, '
                    f'got {type(node).__name__} in {expression!r}.')
            if node.name.lower() not in supported:
                raise ActionError(
                    f'Unsupported expression action function: {node.name}. '
                    f'Supported are {", ".join(runtime_class.STATEMENTS)}. '
                    'Functions that modify the entity itself, such as '
                    'SetEntityName or AddEntityCode, have no equivalent when '
                    'a rule runs against a plain object.')
            statements.append(node)
            if parser.current.kind not in ('SEMICOLON', 'EOF'):
                raise PowerFxError(
                    f'Expected ; or end of expression at position '
                    f'{parser.current.pos}, got {parser.current.value!r}')
        if not statements:
            raise ActionError(f'Expression action is empty: {expression!r}')
        return statements

    def apply(self, obj: Any, **runtime_kwargs) -> Any:
        """
        Runs the statements against an object, modifying it in place.

        Args:
            obj: The object to modify.
            **runtime_kwargs: Passed to the runtime.

        Returns:
            Any: The modified object.

        Raises:
            PowerFxError: If a statement cannot be evaluated.
        """
        runtime = self.runtime_class(obj, **runtime_kwargs)
        for statement in self.statements:
            runtime.evaluate(statement)
        return obj

    def __repr__(self) -> str:
        return f'CompiledExpressionAction({self.expression!r})'


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def default_get_action(action_json: Mapping, **runtime_kwargs) -> Callable[[Any], Any]:
    """
    Translates a CluedIn rule action into a callable.

    Args:
        action_json (Mapping): The action, as returned by `get_rule`.
        **runtime_kwargs: Passed to `ExpressionActionRuntime` for expression
            actions: `get_value`, `set_value`, `add_tag`,
            `load_entity_by_code`.

    Returns:
        callable: `(obj) -> obj`, applying the action in place.

    Raises:
        ActionError: If the action type is not supported, or if a supported
            action is missing the properties it needs.
    """
    action_type = action_json.get('type')
    properties = get_action_properties(action_json)
    set_value = runtime_kwargs.get('set_value') or default_set_value
    add_tag = runtime_kwargs.get('add_tag') or default_add_tag

    if action_type == SET_VALUE_ACTION:
        field = properties.get('FieldName')
        if not field:
            raise ActionError('A SetValue action has no FieldName property.')
        value = properties.get('Value')

        def apply_set_value(obj):
            set_value(field, value, obj)
            return obj

        return apply_set_value

    if action_type == ADD_TAG_ACTION:
        tag = properties.get('Value')
        if not tag:
            raise ActionError('An AddTag action has no Value property.')

        def apply_add_tag(obj):
            add_tag(tag, obj)
            return obj

        return apply_add_tag

    if action_type == EXPRESSION_ACTION:
        expression = properties.get('Expression')
        if not expression or not str(expression).strip():
            raise ActionError(
                'An ExpressionAction has no Expression property.')
        # runtime_class selects the statement functions; the rest configure
        # the runtime instance, so it is not passed on to apply().
        runtime_kwargs = dict(runtime_kwargs)
        compiled = CompiledExpressionAction(
            str(expression), runtime_kwargs.pop('runtime_class', None))

        def apply_expression(obj):
            return compiled.apply(obj, **runtime_kwargs)

        return apply_expression

    raise ActionError(f'Unsupported rule action: {action_type}')


def iter_actions(rule_model: Mapping):
    """
    Yields every action in a rule.

    A rule's actions live on its child processing rules
    (`rule['rules'][]['actions'][]`), not on the rule itself.

    Args:
        rule_model (Mapping): A rule, as returned at
            `get_rule(...)['data']['management']['rule']`.

    Yields:
        dict: Each action.
    """
    for processing_rule in rule_model.get('rules') or []:
        for action in processing_rule.get('actions') or []:
            yield action
