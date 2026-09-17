# Rule execution outside CluedIn — known gaps

What is missing, unverified, or wrong in the rule support added to
`cluedin/rules/` (`powerfx.py`, `actions.py`, `processor.py`, and the
pagination helpers in `rules.py`).

The goal of that work is to retrieve CluedIn rules and run them outside
CluedIn. Everything below is a way in which a rule that CluedIn executes may
not execute here, or may execute differently. Each item says how it was
established: **verified** means reproduced against this code, **unverified**
means it depends on CluedIn behaviour we have not confirmed.

Status: conditions and actions run for the rule shapes we have seen. The single
real rule available while building this was
`tests/fixtures/rules/powerfx.json`.

---

## 1. Correctness bugs

These produce wrong output rather than an error, so they fail silently.

- [ ] **Number parsing and formatting are invariant-culture only.** `Value` now
  reads group separators, percentages and accounting negatives, and `Text`
  implements the .NET numeric formats — but both assume `,` groups and `.` is
  the decimal separator. A European-locale value such as `"1.000,50"` reads as
  1.0, not 1000.5. Power Fx is locale-aware. Establish which locale CluedIn
  evaluates rules under before adding one.

- [ ] **`Text()` rejects the currency format `C`.** It raises `PowerFxError`
  rather than guessing a currency symbol, which would depend on a locale we do
  not know. Add it once the locale question above is settled.

- [ ] **Text comparison case sensitivity is inconsistent within one rule.**
  Verified: Power Fx `=` here is case-sensitive (`"ABC" = "abc"` is `False`),
  matching real Power Fx, but the SDK's `Equals` operator
  (`0bafc522-…`) is case-**in**sensitive. The same rule can therefore treat case
  two different ways depending on which kind of condition is used. Confirm which
  CluedIn applies to a Power Fx condition and align.

## 2. Unverified assumptions

Things built on inference that need checking against CluedIn before being
trusted.

- [ ] **`AddTag` and `RemoveVocabularyKey` as Formula Action statements are
  guesses.** Only `SetVocabularyKeyValue` (from the real rule) and
  `SetEntityProperty` (from the notebook) are confirmed. The other two are
  plausible pairings. If CluedIn names them differently they are two lines each
  in `ExpressionActionRuntime.call`. Get the real list of statement functions.

- [ ] **`isActive` is ignored, on both the rule and its child processing rules.**
  Verified: the real fixture's child processing rule has `"isActive": false`,
  and its action is applied anyway. `RuleProcessor.is_active` is recorded and
  never read. Establish what CluedIn does with an inactive child rule — this
  currently applies actions CluedIn may not.

- [ ] **Rule `order` is ignored, and cannot currently be honoured.** Verified:
  the `getRule` query in `rules.py` does not request `order`, so a rule fetched
  in full has no `order` field and `RuleProcessor.order` is always 0 — sorting
  by it today would be a no-op. The `getRules` list query does request it.
  Fixing this means adding `order` to the `getRule` selection set, which was not
  attempted because a field the schema does not have fails the whole query and
  there was no schema to check against. Since actions mutate the record, order
  changes the result. **Check the schema, add the field, then sort in
  `prepare`.**

- [ ] **Only the `Entity` scope is exercised.** The one real rule is
  `scope: "Entity"`. `DataPart` and `Survivorship` rules may present a different
  record shape (a data part is not a golden record) and different available
  functions. Untested.

- [ ] **Power Fx conditions are detected solely by
  `objectTypeId == 96102979-e952-43d8-afe6-987676c0698b`.** This is from one
  rule. If CluedIn uses other ids for other formula condition kinds, they will
  fall through to `Rule(...)` and raise on the empty-GUID operator. See
  `POWERFX_OBJECT_TYPE_ID` in `evaluator.py`.

- [ ] **The rule `type` field is not applied to Power Fx conditions.** Ordinary
  conditions typecast through `Rule.typecast_value`; a Power Fx condition has
  `type: null` and its values are used as they arrive. Whether CluedIn coerces
  vocabulary key types before a formula sees them is unknown.

## 3. Missing Power Fx functions

The scalar functions are now implemented. What remains needs either a value
model this engine does not have, or a decision.

- [ ] **Table functions:** `Filter`, `Sort`, `ForAll`, `Search`, `First`,
  `Last`, `Index`, `Distinct`, `Table`, `Shuffle`, `Concat` (the table form,
  distinct from the supported `Concatenate`). These need a table/record value
  model and a scope for `ThisRecord`, which is a real piece of work rather than
  a function each. `Split` is the one exception: it returns a plain Python list,
  which comparisons and `CountRows` already understand.
- [ ] **`Time`.** Needs a time-of-day value type; the engine has dates and
  datetimes only.
- [ ] **`JSON`.** Needs a decision on what a serialized CluedIn entity should
  look like.
- [ ] **`Rand`, `RandBetween`, `GUID`.** Deliberately absent: a non-deterministic
  rule cannot be reproduced or tested. Add only if a real rule needs one.

The supported set is declared in `PowerFxRuntime.FUNCTIONS`, and a test now
asserts that every declared name is actually dispatched, so the list and the
implementation cannot drift apart.

## 4. Missing Power Fx language features

- [ ] **Bracket indexing.** Verified: `Entity.Properties["a.b"]` fails at the
  lexer (`[` is not a token). Lower priority than it first looks — there are two
  working ways to reach a dotted vocabulary key:
  `GetVocabularyKeyValue(Entity,"a.b")` and the quoted name
  `Entity.Properties.'a.b'` (both verified). Only add brackets if real rules use
  that syntax.
- [ ] **`ThisRecord`, `ThisItem`, `Self`.** Verified: rejected. Only names rooted
  at `Entity` resolve.
- [ ] **No error *value* model.** `IfError`, `IsError` and `IsBlankOrError` now
  catch errors, which covers the practical uses. But an error is still a raised
  `PowerFxError`, not a value that flows through an expression, so `1/0 = 1`
  raises instead of producing an error. Only matters if a rule relies on an
  error propagating through arithmetic.
- [ ] **No named formulas, `Set`, `UpdateContext`, or variables.** Expression-only
  by design; noted so the limit is explicit.

## 5. CluedIn integration gaps

- [ ] **`LoadEntityByEntityCode` has no built-in implementation.** It requires a
  caller-supplied callback and otherwise raises. Since the SDK already has a
  `Context` and GraphQL access, it could resolve entity codes against CluedIn
  itself. This is probably the highest-value item here: it makes cross-entity
  formulas work without the caller writing lookup plumbing.
- [ ] **Entity metadata beyond properties is untested.** A formula may reference
  `Entity.Codes`, `Entity.Tags`, `Entity.CreatedDate`, `Entity.Aliases`, or edges
  (`OutgoingEdges`/`IncomingEdges`). Member access will return whatever the dict
  happens to hold, or blank. No helpers, no fixtures, no tests.
- [ ] **Unsupported action types are not enumerated.** Three are supported:
  `SetValue`, `AddTag`, `ExpressionAction`. CluedIn has more, and we have no
  list. Anything else raises `ActionError` and the rule is reported as skipped —
  correct behaviour, but the coverage is unknown. Get the full action type list.
- [ ] **No integration test against a live tenant.** All Power Fx tests are unit
  tests over fixtures. The existing `@pytest.mark.integration` tests would be the
  place for a real round-trip.

## 6. Rule retrieval

- [ ] **Page size cannot be controlled.** Verified: the GraphQL query in
  `rules.py` declares `$searchName`, `$isActive`, `$pageNumber`, `$sortBy`,
  `$sortDirection` and `$scope` — but no `$pageSize`. The server serves 20 rules
  per page. `get_all_rules` works around this by walking pages, which costs one
  request per 20 rules. If the `management.rules` schema accepts a page size,
  adding `$pageSize: Int` to the query would collapse most scopes to a single
  request. Not attempted: the postman collection does not contain this query, so
  there was no way to confirm the argument exists, and guessing would break the
  query outright. **Check the schema.**

- [ ] **`get_all_rule_details` makes one request per rule.** Unavoidable with
  the current API — rule summaries carry no condition or actions, so each needs
  its own `get_rule`. If a bulk endpoint exists, use it.

- [ ] **No integration test for pagination.** The tests fake the GraphQL layer,
  so they prove the paging logic but not that the server behaves as assumed
  (20 per page, `total` accurate, `pageNumber` honoured). A tenant with more
  than 20 rules in a scope would confirm it.

## 7. Ergonomics and performance

- [ ] **`RuleProcessor.apply_all` deep-copies twice per rule per object.** Once
  for the result and once per rule for atomicity. Fine for a notebook, wasteful
  for a large batch. A copy-on-write or a rollback journal would avoid it.
- [ ] **No vectorised path.** Rules are applied per object. There is no DataFrame
  equivalent for Power Fx conditions, which is what `explain()` exists for with
  ordinary conditions.

## 8. Repository

- [ ] **Version drift.** This repo (`CluedIn-io/CluedIn.SDK.Py`) is at **3.0.1**,
  while the `cluedin` package on PyPI is at **4.0.1**, published from
  `romaklimenko/cluedin`. This work sits on the older base. Resolve before
  publishing, or the 4.0.x changes get clobbered.

---

## Not gaps — deliberate decisions

Recorded so they are not "fixed" by mistake.

- **The zip's `QueryBuilderEvaluator` was dropped.** It re-implemented AND/OR
  traversal against string operator names (`equal`, `contains`) while this SDK
  dispatches on CluedIn operator GUIDs. Keeping both would mean two evaluators
  disagreeing about the same rule.
- **Formulas are interpreted, never `eval`/`exec`'d.** Only whitelisted functions
  are reachable. This is why adding a function is an explicit edit to `call()`
  rather than a lookup into Python's namespace.
- **`Evaluator`'s public API is unchanged.** Power Fx conditions are routed
  inside it, so existing callers keep working.

## Fixed in the source library

Bugs found in `powerfx_querybuilder.zip` and corrected while merging it, listed
in case that library is used elsewhere.

- `-` was in the identifier lexer pattern, so `Len("a")-1` lexed as one name.
- `Not(x)`, `And(...)`, `Or(...)` raised "Unsupported function" despite the
  README claiming support.
- `If` evaluated both branches, so `If(IsBlank(x), "", 1/x)` threw on the
  untaken branch.
- Ordering comparisons against blanks raised a raw Python `TypeError`.
- `Text(d, "dd MMM yyyy")` corrupted month names — sequential replacement turned
  `MMM` into `%mM`.
- `in` was case-sensitive; real Power Fx `in` is not, and `exactin` is the
  case-sensitive form.
- `StartsWith`/`EndsWith` were case-sensitive; `Len` failed on non-text;
  `DateValue` returned a datetime rather than a date.
