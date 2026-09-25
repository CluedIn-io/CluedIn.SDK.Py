# CluedIn

[cluedin](https://pypi.org/project/cluedin/) is a Python SDK for [CluedIn](https://www.cluedin.com/) API.

## Installation

From [PyPi](https://pypi.org/project/cluedin/):

```shell
pip install cluedin
```

## Quick start

### CluedIn context configuration

Create a JSON file with context configuration to your CluedIn instance:

In this file, parameters have the following meaning:

- `protocol` - `http` if your CluedIn instance is not secured with a TLS certificate. Otherwise, `https` by default.
- `domain` – CluedIn instance domain without the Organization prefix.
- `org_name` – the name of Organization (a.k.a. Organization prefix).
- `user_email` – the user's email.
- `user_password` – the user's password.
- `verify_tls` – `false`, if an unknown CA signs the TLS certificate. Otherwise, `true` by default.

Here is an example of a file for a CluedIn instance running locally from a [Home](https://cluedin-io.github.io/Home/) repository:

```json
{
  "domain": "mdm.saas-cluedin.com",
  "org_name": "foobar",
  "user_email": "admin@foobar.com",
  "user_password": "Foobar23!"
}
```

We add the `protocol`, but we can skip this parameter if the URL starts with `https`.
If you use self-signed certificates, you can add `verify_tls: false` to avoid certificate verification.

Alternatively, to provide email and password, you can obtain an API access token from CluedIn UI and provide it in the file:

```json
{
  "domain": "mdm.saas-cluedin.com",
  "org_name": "foobar",
  "access_token": "..."
}
```

When the configuration file exists, you can export its path to an environment variable:

```shell
export CLUEDIN_CONTEXT=~/.cluedin/home.json
```

Now, you can load this file from your Python code and get an access token (if not already provided):

```python
import cluedin

context = Context.from_json_file(os.environ['CLUEDIN_CONTEXT'])
context.get_token() # call it only if access_token is not provided in the context file
```

You could also do it without the context file:

```python
context = {
    "domain": "mdm.saas-cluedin.com",
    "org_name": "foobar",
    "user_email": "admin@foobar.com",
    "user_password": "Foobar23!"
}

context = Context.from_dict(context)
context.get_token()
```

Or, you can infer the context from the JWT token:

```python
context = Context.from_jwt(API_TOKEN)
```

### GraphQL

Get entities:

```python
context = Context.from_json_file(os.environ['CLUEDIN_CONTEXT'])
context.get_token()

query = """
    query searchEntities($cursor: PagingCursor, $query: String, $pageSize: Int) {
      search(
        query: $query,
        sort: FIELDS,
        cursor: $cursor,
        pageSize: $pageSize
        sortFields: {field: "id", direction: ASCENDING}
      ) {
        totalResults
        cursor
        entries {
          id
          name
          entityType
        }
      }
    }
"""

variables = {
    "query": "*",
    "pageSize": 10_000
}

# it's important to request cursor in your GraphQL query,
# so cluedin.gql.entries would be able to request and return all pages
entities = cluedin.gql.entries(context, query, variables):
```

## API

### Environment

- `CLUEDIN_REQUEST_TIMEOUT_IN_SECONDS` - CluedIn API request timeout (in seconds). If not set, then it defaults to `300` (5 minutes).

### Context

- `cluedin.Context.from_dict(cls, context_dict: dict) -> Context` – creates a new `Context` object from a `dict`.
- `cluedin.Context.from_json_file(file_path: str) -> Context` – creates a new `Context` object from a JSON-file.
- `cluedin.Context.from_jwt(jwt: str) -> Context` – creates a new `Context` object from a JWT (JSON Web Token, a.k.a. access token or API token).

### Account

- `cluedin.account.get_users(context: Context, org_id: str = None) -> list` – returns all users for Organization.
- `cluedin.account.is_organization_available_response(context: Context, org_name: str) -> dict` – checks if a given Organization name is available. This method returns a JSON-response serialized into a `dict`.
- `cluedin.account.is_organization_available(context: Context, org_name: str) -> bool` – checks if a given Organization name is available. Returns a Boolean.
- `cluedin.account.is_user_available_response(context: Context, user_email: str, org_name: str) -> dict` – checks, if a user with a given email can be created or this email is already reserved. This method returns a JSON-response serialized into a `dict`.
- `cluedin.account.is_user_available(context: Context, user_email: str, org_name: str) -> bool` – checks, if a user with a given email can be created or this email is already reserved. This method returns a JSON-response serialized into a `dict`. Returns a Boolean.
- `cluedin.account.get_invitation_code(context: Context, email: str) -> str` – returns an invitation code for a given email.
- `cluedin.account.create_organization(context: Context, user_email: str, password: str, org_name: str, org_sub_domain: str = None, email_domain: str = None, allow_email_domain_signup: bool = True, new_account_access_key: str = None) -> dict` - creates a new Organization. This method returns a JSON-response serialized into a `dict`.
- `cluedin.account.create_user(context: Context, user_email: str, user_password: str) -> requests.models.Response` – creates a new user. This method returns `requests.models.Response`.
- `cluedin.account.create_admin_user(context: Context, user_email: str, user_password: str) -> requests.models.Response` – creates a new admin user. This method returns `requests.models.Response`.
- `cluedin.account.get_user(context: Context, user_id: str = None) -> dict` – returns a user by ID. If `user_id` is nor provided, the current user is returned. This method returns a JSON-response serialized into a `dict`.

### Entity

- `cluedin.entity.get_entity_blob(context: Context, entity_id: str) -> str` – returns an entity blob by ID.
- `cluedin.entity.get_entity_as_clue(context: Context, entity_id: str) -> str` – returns an entity as a clue by ID.

### Ingestion

- `cluedin.ingestion.post(context: Context, url: str, collection: list[Any], batch_size: int = 10_000, delay_in_seconds: int = 0) -> Generator` – posts data to CluedIn ingestion endpoint. This method splits the collection into batches and sends them to CluedIn. If `delay_in_seconds` is set, then it waits for this time before sending the next batch. Returns a generator of responses.

### GraphQL

- `cluedin.gql.gql(context: Context, query: str, variables: dict = None) -> dict` – sends a GraphQL request and returns a response.
- `cluedin.gql.org_gql(context: Context, query: str, variables: dict = None) -> dict` – sends a GraphQL request to Organization endpoint and returns a response.
- `cluedin.gql.entries(context: Context, query: str, variables: dict = None, flat=False) -> Generator` – returns entries from a GraphQL search query. If cursor is requested in the GraphQL query (see the example above and tests), then it proceeds to next pages to return all results. If `flat` is `True`, then it flattens the `properties` dictionary of each returned entity.
- `search(context: Context, search_query: str, page_size: int = 10_000) -> Generator` – returns entities by a search query. This method is a wrapper around `cluedin.gql.entries`.

### JSON

- `cluedin.json.dump(file: str, obj: Any) -> None` – serialize obj as a JSON formatted stream to file.
- `cluedin.json.load(file: str) -> Any` – deserialize file to a Python object.

### JWT

- `cluedin.jwt.get_jwt_payload(jwt: str) -> dict` – parses a JWT (JSON Web Token, a.k.a. access token or API token), and returns its payload serialized into a `dict`.

### Public API

- `cluedin.public.post_clue(context: Context, clue: str, content_type: str = 'application/xml') -> str` – posts a clue in XML or JSON format. This method returns an operation result as a string.
- `cluedin.public.restore_user_entities(context: Context) -> list` – if you accidentally deleted `/Infrastructure/User` entities, this method gets all users and restores entities for those who miss them.

### Rules

- `cluedin.rules.RuleScope` - an enumeration of rule scopes: `DATA_PART`, `ENTITY`, `SURVIVORSHIP`.
- `cluedin.rules.get_rules(context: Context, scope=RuleScope.DATA_PART, page_number=1, search_name=None, is_active=None, sort_by=None, sort_direction=None) -> dict` – returns **one page** of rules for a given scope. This method returns a JSON-response serialized into a `dict`.
- `cluedin.rules.get_all_rules(context: Context, scope=RuleScope.DATA_PART, max_pages=1_000, **kwargs) -> Generator` – returns every rule in a scope, walking the pages. This function is a generator.
- `cluedin.rules.get_rule(context: Context, rule_id: str) -> dict` – returns a rule by ID. This method returns a JSON-response serialized into a `dict`.
- `cluedin.rules.get_all_rule_details(context: Context, scope=RuleScope.DATA_PART, **kwargs) -> Generator` – returns every rule in a scope in full, with its condition and actions. This function is a generator.
- `cluedin.rules.get_rules_page(response: dict) -> dict` – pulls the rules page out of a `get_rules` response, raising `ValueError` on a GraphQL error rather than a `KeyError` far from the cause.

The server decides the page size and currently returns 20 rules per page, so a scope holding more
than that needs several calls. `get_rules` returns a single page; `get_all_rules` walks them:

```python
rules = list(cluedin.rules.get_all_rules(context, RuleScope.ENTITY))

len(rules)  # every rule in the scope, not just the first 20
```

Rule summaries carry no condition or actions. To get rules ready to evaluate or apply, use
`get_all_rule_details`, which follows each summary with a `get_rule` call – one request per rule:

```python
rules = list(cluedin.rules.get_all_rule_details(context, RuleScope.ENTITY))

processors, skipped = cluedin.rules.RuleProcessor.prepare(rules)
```

Both generators are lazy, so `next()` or a `break` fetches only the pages it reaches. `max_pages`
caps the number of requests, so a server that ignores `pageNumber` cannot loop forever.

#### Running rules outside CluedIn

A CluedIn rule is a condition and a set of actions. This SDK can retrieve both and execute them in
Python, against a `dict` rather than a live entity, which makes it possible to preview what a rule
would do, test a rule against sample records before activating it, or apply the same logic to data
that has not been ingested yet.

The workflow is: retrieve the rules in full, turn them into processors, then apply them.

```python
import os

import cluedin
from cluedin.rules import RuleProcessor, RuleScope, get_all_rule_details

context = cluedin.Context.from_json_file(os.environ['CLUEDIN_CONTEXT'])
context.get_token()

# 1. Retrieve every rule in the scope, with its condition and actions.
rules = list(get_all_rule_details(context, RuleScope.ENTITY))

# 2. Turn them into executable rules. Anything this SDK cannot run is
#    reported instead of being half-applied.
processors, skipped = RuleProcessor.prepare(rules)

print(f'executable: {len(processors)}   skipped: {len(skipped)}')

for rule in skipped:
    print(f'SKIPPED {rule["name"]}: {rule["reason"]}')

# 3. Apply them to a record.
record = {
    'entityType': '/DPerson',
    'golden.person.firstName': 'Smith',
    'golden.person.lastName': 'Smith',
}

result = RuleProcessor.apply_all(record, processors)

print(result)
# {'entityType': '/DPerson', 'golden.person.firstName': 'New Name',
#  'golden.person.lastName': 'Smith'}
```

`apply_all` works on a copy, so `record` is left untouched. Each rule is applied atomically: if
one fails, its changes are discarded and the remaining rules still run. Pass `on_error` to see
which failed:

```python
errors = []

result = RuleProcessor.apply_all(
    record, processors, on_error=lambda processor, exc: errors.append((processor.name, exc)))
```

A single rule can be inspected on its own, which is usually what you want while working out why a
record did or did not change:

```python
for processor in processors:
    if processor.matches(record):
        print('matched:', processor.name)
```

##### The record shape

Rules address fields by vocabulary key. A record is a flat `dict` keyed by those vocabulary keys,
which is what `cluedin.gql.entries(..., flat=True)` and `cluedin.gql.search` already return, so
entities can be piped straight in:

```python
entities = cluedin.gql.search(context, 'entityType:/DPerson', page_size=1_000)

changed = []

for entity in entities:
    after = RuleProcessor.apply_all(entity, processors)
    if after != entity:
        changed.append((entity.get('name'), after))
```

Nothing is written back to CluedIn – applying a rule here only produces a new `dict`.

A record nested under a `Properties` mapping, the shape `get_rule` responses use, works too. For
anything else, pass `get_value` to map a vocabulary key onto your own field names:

```python
def get_value(field, obj):
    for part in field.split('.'):
        obj = obj.get(part) if isinstance(obj, dict) else None
        if obj is None:
            return None
    return obj

processors, skipped = RuleProcessor.prepare(
    rules, evaluator_kwargs={'get_value': get_value})
```

##### Finding the rules that use Power Fx

A rule expresses its condition either as field/operator/value triples or as a Power Fx formula,
and its actions either as typed actions or as a Formula Action. To see which rules use which:

```python
from cluedin.rules import get_powerfx_formula
from cluedin.rules.actions import EXPRESSION_ACTION, get_action_properties


def find_powerfx(rule):
    """Returns the Power Fx conditions and actions a rule uses."""
    model = rule['data']['management']['rule']
    formulas = []

    def walk(condition):
        formula = get_powerfx_formula(condition)
        if formula:
            formulas.append(formula)
        for child in condition.get('rules') or []:
            walk(child)

    walk(model.get('condition') or {})

    expressions = [
        get_action_properties(action).get('Expression')
        for processing_rule in model.get('rules') or []
        for action in processing_rule.get('actions') or []
        if action.get('type') == EXPRESSION_ACTION
    ]
    return formulas, expressions


for rule in rules:
    conditions, actions = find_powerfx(rule)
    if conditions or actions:
        print(rule['data']['management']['rule']['name'])
        for formula in conditions:
            print('  condition:', formula)
        for expression in actions:
            print('  action   :', expression)
```

##### What gets skipped, and why

`RuleProcessor.prepare` builds a processor only for a rule it can execute completely. A rule using
an unsupported action type, an unsupported operator, or a Formula Action verb that has no meaning
outside CluedIn is reported in `skipped` with the reason, and never partially applied:

```text
executable: 42   skipped: 4
SKIPPED Grant - recipient reference: ActionError: Unsupported rule action:
CluedIn.Rules.Actions.SomeAction, CluedIn.Rules
```

This is deliberate. A rule that half-runs would produce a record that neither matches CluedIn nor
is obviously wrong. See [Actions](#actions) for how to add support for an action type or a
statement function this SDK does not handle.

##### Cost

`get_all_rules` makes one request per page of 20 rules. `get_all_rule_details` additionally makes
one `get_rule` request per rule, because a rule summary carries no condition or actions – so a
scope of 46 rules costs 3 + 46 requests. Retrieve once and reuse the processors; building them
does no I/O.

#### Evaluator

- `cluedin.rules.evaluator.default_get_property_name(field: str) -> str` – returns a default property name for a given field. Used to map CluedIn Rules fields to your fields.
- `cluedin.rules.evaluator.default_get_value(field: str, obj: dict) -> Any` – returns a default value for a given field. Used to map CluedIn Rules fields to your fields.
- `cluedin.rules.Evaluator` – a class to evaluate CluedIn Rules.
- `cluedin.rules.Evaluator.evaluate(context: Context, rule: dict, obj: dict) -> bool` – evaluates a rule for an object. Returns a Boolean:

  - `cluedin.rules.get_matching_objects(self, objects) -> list` – returns a list of objects that match the rule.
  - `cluedin.rules.object_matches_rules(self, obj) -> bool` – returns `True` if an object matches the rule.
  - `cluedin.rules.explain(self) -> str` – returns an explanation of the rule (in pandas `DataFrame.query` terms).
  - `cluedin.rules.can_explain(self) -> bool` – returns `False` if the rule contains a Power Fx condition, which has no pandas equivalent, so `explain()` cannot produce a runnable query.

#### Operators

- `cluedin.rules.operators.default_get_operator(operator_id) -> Any` – returns a default operator for a given operator ID. Used to map CluedIn Rules operators to your operators.

You can add custom operations (see `test_operators.py` for examples), but the following CluedIn Rules operators are supported out of the box:

- `Is Not True`
- `Is True`
- `Begins With`
- `Between`
- `Contains`
- `Ends With`
- `Equals`
- `Exists`
- `Greater`
- `Greater or Equal`
- `In`
- `Is False`
- `Is Not Null`
- `Is Null`
- `Is True`
- `Less`
- `Less or Equal`
- `Matches pattern`
- `Not Begins With`
- `Not Between`
- `Not Contains`
- `Not Ends With`
- `Not Equal`
- `Does Not Exist`
- `Not In`
- `Does not match pattern`

#### Power Fx

CluedIn rules can express a condition as a Power Fx formula instead of a field/operator/value
triple, and can use a Formula Action to modify a record. Both run outside CluedIn, so a rule can
be evaluated and applied locally, against a `dict`, a batch, or a DataFrame row.

Formulas are parsed into an AST and interpreted. They are never passed to `eval` or `exec`, and
only the functions listed below are reachable, so rules authored by other people stay contained.

A Power Fx condition needs no special handling – `Evaluator` recognizes it by its `objectTypeId`
and evaluates it alongside the ordinary conditions in the same rule:

```python
rule = cluedin.rules.get_rule(context, rule_id)
evaluator = cluedin.rules.Evaluator(rule['data']['management']['rule']['condition'])

evaluator.object_matches_rules({
    'entityType': '/DPerson',
    'golden.person.firstName': 'Smith',
    'golden.person.lastName': 'Smith'
})
```

`Evaluator.explain()` cannot translate a formula into a pandas query, so it emits it as
`@powerfx(<formula>)`. A query containing that is not runnable – it is there so the explanation
does not silently drop a condition.

To also apply a rule's actions, use `RuleProcessor`:

```python
rules = [cluedin.rules.get_rule(context, rule_id) for rule_id in rule_ids]

processors, skipped = cluedin.rules.RuleProcessor.prepare(rules)

for rule in skipped:
    print(f'SKIPPED: {rule["name"]} -> {rule["reason"]}')

result = cluedin.rules.RuleProcessor.apply_all(obj, processors)
```

- `cluedin.rules.RuleProcessor(rule, get_action=default_get_action, evaluator_kwargs=None, **runtime_kwargs)` – an executable rule: a condition plus the actions to apply to the objects that satisfy it. Accepts a `get_rule` response or the rule model inside it.
  - `matches(obj) -> bool` – returns `True` if an object satisfies the rule's condition.
  - `apply(obj) -> obj` – applies the rule's actions to an object, in place, if it matches.
  - `actions -> list` – every action callable in the rule.
  - `RuleProcessor.prepare(rules, **kwargs) -> (processors, skipped)` – builds a processor per rule that can be executed here, and reports the rest as `{'id', 'name', 'reason'}`.
  - `RuleProcessor.apply_all(obj, processors, on_error=None) -> obj` – applies rules to a copy of an object. Each rule is atomic: if one raises, its changes are discarded and the rest still run.
- `cluedin.rules.processor.describe_unsupported(rule) -> list` – lists the action types in a rule that this SDK cannot execute.

##### Power Fx API

- `cluedin.rules.evaluate_powerfx(formula, entity, get_value=None, load_entity_by_code=None) -> Any` – evaluates a formula against an entity.
- `cluedin.rules.matches_powerfx(formula, entity, ...) -> bool` – evaluates a formula as a predicate.
- `cluedin.rules.compile_powerfx(formula) -> CompiledPowerFx` – parses a formula once for reuse across many entities. Results are cached.
- `cluedin.rules.PowerFxError` – raised when a formula cannot be parsed or evaluated.
- `cluedin.rules.get_powerfx_formula(rule_object) -> str` – returns a condition's formula, or `None` if it is not a Power Fx condition.

`get_value` is `(key, entity) -> value`, used by `GetVocabularyKeyValue`. By default a key is read
from the entity's `Properties` mapping, then from the entity itself, so both the CluedIn shape and
the flattened shape of `cluedin.gql.entries(flat=True)` work. `Evaluator` passes its own
`get_property_name`/`get_value` through, so a custom field mapping also applies inside formulas.

`load_entity_by_code` is `(code) -> entity`, used by `LoadEntityByEntityCode`. Without it, a
formula calling that function raises `PowerFxError` rather than silently returning blank.

Supported in a formula:

- literals: text, numbers, `true`, `false`, `Blank()`
- `Entity`, `Entity.Name`, nested members, and `'quoted names'`
- operators: `=`, `<>`, `<`, `<=`, `>`, `>=`, `+`, `-`, `*`, `/`, `&`, `in`, `exactin`, `And`/`&&`, `Or`/`||`, `Not`/`!`
- text: `Char`, `Concatenate`, `EncodeUrl`, `EndsWith`, `Find`, `Left`, `Len`, `Lower`, `Mid`, `Proper`, `Replace`, `Right`, `Split`, `StartsWith`, `Substitute`, `Text`, `Trim`, `Upper`
- numbers: `Abs`, `Average`, `Int`, `Max`, `Min`, `Mod`, `Power`, `Round`, `Sqrt`, `Sum`, `Trunc`, `Value`
- dates: `DateAdd`, `DateDiff`, `DateTimeValue`, `DateValue`, `Day`, `Hour`, `Minute`, `Month`, `Now`, `Second`, `Today`, `Weekday`, `Year`
- logic: `And`, `Blank`, `Boolean`, `Coalesce`, `If`, `IfError`, `IsBlank`, `IsBlankOrError`, `IsEmpty`, `IsError`, `IsMatch`, `Not`, `Or`, `Switch`
- CluedIn: `CountRows`, `GetVocabularyKeyValue`, `LoadEntityByEntityCode`

A vocabulary key holding several values compares with ANY semantics, except `<>`, which holds only
if every value differs. `If`, `Switch`, `And`, `Or`, `Coalesce`, `IfError` and `IsError` evaluate
their arguments lazily, as Power Fx does. Anything outside this subset raises `PowerFxError`.

Numbers follow Power Fx rather than Python: `Round` rounds half away from zero (`Round(2.5)` is 3,
not Python's 2), `Text` implements the .NET numeric formats (`N2`, `#,##0.00`, `D3`, `P1`, …) and
raises on one it cannot honour rather than emitting a wrong number, and `Value` reads group
separators, percentages and accounting negatives. Invariant culture only — a European-locale
`"1.000,50"` is not understood.

`Split` returns a Python list rather than a Power Fx table, which comparisons and `CountRows`
already understand. The table functions (`Filter`, `ForAll`, `Sort`, …) are not supported.

#### Actions

- `cluedin.rules.default_get_action(action_json, **runtime_kwargs) -> callable` – translates a rule action into `(obj) -> obj`. Raises `ActionError` for an action type that is not supported.
- `cluedin.rules.iter_actions(rule_model)` – yields every action in a rule. A rule's actions live on its child processing rules, not on the rule itself.
- `cluedin.rules.CompiledExpressionAction(expression)` – parses a Formula Action's `;`-separated Power Fx statements. `apply(obj, **runtime_kwargs) -> obj` runs them.
- `cluedin.rules.ActionError` – raised when an action cannot be translated or applied.

Supported action types:

- `CluedIn.Rules.Actions.SetValue` – sets a property to a constant.
- `CluedIn.Rules.Actions.AddTag` – appends to the object's `tags` list.
- `CluedIn.Rules.Actions.ExpressionAction` – runs a Formula Action, for example
  `SetVocabularyKeyValue(Entity,"golden.person.firstName","New Name")`. Their value arguments are
  ordinary Power Fx expressions, so an action can read the entity it is modifying.

##### Formula Action statement functions

| Function | Status |
| --- | --- |
| `SetVocabularyKeyValue(Entity, "key", value)` | Supported. Seen in a real CluedIn rule. |
| `SetEntityProperty(Entity, "name", value)` | Supported. Seen in a real CluedIn rule. |
| `RemoveVocabularyKey(Entity, "key")` | Supported, but **inferred** – not yet seen in a real rule, so the name is unconfirmed. |
| `AddTag(Entity, "tag")` | Supported, but **inferred** – `AddTag` is confirmed as an action *type*, not as a formula verb. |

##### Not supported: entity-level functions

Rules run here against a plain JSON object – a `dict` from `cluedin.gql.entries` or one you built
yourself – not against a live CluedIn entity. A formula that manipulates the entity itself rather
than its properties therefore has no meaningful target, and is **not supported**:

`SetEntityName`, `SetEntityType`, `RemoveTag`, `AddAlias`, `AddEntityCode`, `RemoveEntityCode`,
`AddEdge`, `RemoveEdge`, and any other function that reaches into CluedIn's entity model.

This is a deliberate limit, not an oversight. Those functions operate on parts of an entity –
its codes, aliases, edges, entity type – that a JSON object does not carry, and inventing a
representation for them would produce a result that does not match what CluedIn would do.

The statement name is checked when the formula is parsed, not when it runs, so `RuleProcessor`
reports the whole rule while rules are being prepared rather than failing partway through a batch:

```python
processors, skipped = cluedin.rules.RuleProcessor.prepare(rules)

for rule in skipped:
    print(f'SKIPPED: {rule["name"]} -> {rule["reason"]}')
```

```text
SKIPPED: Rename people -> ActionError: Unsupported expression action function:
SetEntityName. Supported are AddTag, RemoveVocabularyKey, SetEntityProperty,
SetVocabularyKeyValue. Functions that modify the entity itself, such as
SetEntityName or AddEntityCode, have no equivalent when a rule runs against a
plain object.
```

If your object does model one of these, add the verb yourself rather than waiting for the SDK.
Subclass `ExpressionActionRuntime`, extend `STATEMENTS`, handle the name in `call`, and pass the
subclass as `runtime_class`:

```python
class MyRuntime(cluedin.rules.actions.ExpressionActionRuntime):
    STATEMENTS = ExpressionActionRuntime.STATEMENTS + ('SetEntityName',)

    def call(self, name, args):
        if name.lower() == 'setentityname':
            args[0]['name'] = args[1]
            return args[1]
        return super().call(name, args)

processors, skipped = cluedin.rules.RuleProcessor.prepare(
    rules, runtime_class=MyRuntime)
```

The same applies to an unsupported action *type*: pass your own `get_action` and fall back to
`default_get_action`.

Writes go through `set_value` (`(key, value, obj) -> None`) and `add_tag` (`(tag, obj) -> None`),
both overridable via `runtime_kwargs`. By default a key is written to the object's `Properties`
mapping if it has one, and as a top-level key otherwise.

### Vocabulary

- `cluedin.vocab.get_vocab_keys(context: Context) -> list` – gets all vocabulary keys.
