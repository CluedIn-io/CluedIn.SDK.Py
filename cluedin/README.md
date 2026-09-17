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
  `SetVocabularyKeyValue(Entity,"golden.person.firstName","New Name")`. Statement functions:
  `SetVocabularyKeyValue`, `SetEntityProperty`, `RemoveVocabularyKey`, `AddTag`. Their value
  arguments are ordinary Power Fx expressions, so an action can read the entity it is modifying.

Writes go through `set_value` (`(key, value, obj) -> None`) and `add_tag` (`(tag, obj) -> None`),
both overridable via `runtime_kwargs`. By default a key is written to the object's `Properties`
mapping if it has one, and as a top-level key otherwise. To support an action type this SDK does
not, pass your own `get_action` to `RuleProcessor` and fall back to `default_get_action`.

### Vocabulary

- `cluedin.vocab.get_vocab_keys(context: Context) -> list` – gets all vocabulary keys.
