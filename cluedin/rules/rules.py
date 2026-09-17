from enum import Enum
from typing import Any, Generator, Optional

from ..context import Context
from ..gql import org_gql


class RuleScope(Enum):
    """
    Enum representing the scope of a rule (DataPart, Entity (Golden Record), Survivorship).
    """

    DATA_PART = 'DataPart'
    ENTITY = 'Entity'
    SURVIVORSHIP = 'Survivorship'


def get_rules(
    context: Context,
    scope=RuleScope.DATA_PART,
    page_number=1,
    search_name: Optional[str] = None,
    is_active: Optional[bool] = None,
    sort_by: Optional[str] = None,
    sort_direction: Optional[str] = None,
) -> dict:
    """
    Retrieves one page of rules.

    The server decides the page size, and currently returns 20 rules per page,
    so a scope with more rules than that needs several calls. Use
    `get_all_rules` to iterate over every page.

    Args:
            context (Context): The context object.
            scope (RuleScope, optional): The scope of the rules. Defaults to RuleScope.DATA_PART.
            page_number (int, optional): The page number to retrieve. Defaults to 1.
            search_name (str, optional): Only return rules whose name matches.
            is_active (bool, optional): Only return active or inactive rules.
            sort_by (str, optional): The field to sort by.
            sort_direction (str, optional): The sort direction.

    Returns:
            dict: The rules' data.

    """
    query = """
        query getRules($searchName: String, $isActive: Boolean, $pageNumber: Int, $sortBy: String, $sortDirection: String, $scope: String) {
            management {
                id
                rules(
                    searchName: $searchName
                    isActive: $isActive
                    pageNumber: $pageNumber
                    sortBy: $sortBy
                    sortDirection: $sortDirection
                    scope: $scope
                ) {
                    total
                    data {
                        id
                        name
                        order
                        description
                        isActive
                        createdBy
                        modifiedBy
                        ownedBy
                        createdAt
                        modifiedAt
                        author {
                            id
                            username
                            __typename
                        }
                        scope
                        isReprocessing
                        __typename
                    }
                    __typename
                }
                __typename
            }
        }
        """

    variables = {
        "scope": scope.value,
        "pageNumber": page_number
    }

    # The query declares these, but the server applies its own defaults when a
    # variable is absent, so only send the ones the caller asked for.
    optional = {
        "searchName": search_name,
        "isActive": is_active,
        "sortBy": sort_by,
        "sortDirection": sort_direction,
    }
    variables.update(
        {name: value for name, value in optional.items() if value is not None})

    return org_gql(context, query, variables)


def get_rules_page(response: dict) -> dict:
    """
    Pulls the rules page out of a `get_rules` response.

    Args:
            response (dict): A `get_rules` response.

    Returns:
            dict: The page, with its `total` and its `data`.

    Raises:
            ValueError: If the response carries GraphQL errors or has no page,
                    which otherwise surfaces as a KeyError far from the cause.
    """
    if not isinstance(response, dict):
        raise ValueError(f'Expected a GraphQL response, got {type(response).__name__}.')

    if response.get('errors'):
        raise ValueError(f'GraphQL query failed: {response["errors"]}')

    page = (response.get('data') or {}).get('management') or {}
    page = page.get('rules')

    if page is None:
        raise ValueError(
            'GraphQL response contains no rules. '
            'The token may lack the permission to read them.')

    return page


def get_all_rules(
    context: Context,
    scope=RuleScope.DATA_PART,
    max_pages: int = 1_000,
    **kwargs,
) -> Generator[Any, Any, Any]:
    """
    Retrieves every rule in a scope, one page after another. This function is
    a generator.

    `get_rules` returns a single page, so a scope holding more rules than the
    server's page size needs several calls. This walks them:

    ```python
    rules = list(cluedin.rules.get_all_rules(context, RuleScope.ENTITY))
    ```

    Args:
            context (Context): The context object.
            scope (RuleScope, optional): The scope of the rules. Defaults to RuleScope.DATA_PART.
            max_pages (int, optional): A ceiling on the number of requests, so a
                    server that ignores `pageNumber` cannot loop forever.
                    Defaults to 1000.
            **kwargs: Passed to `get_rules`, for example `search_name` or `is_active`.

    Yields:
            dict: Each rule.

    Raises:
            ValueError: If a page cannot be read.
    """
    seen_ids = set()
    total = None
    page_number = 1

    while page_number <= max_pages:
        page = get_rules_page(
            get_rules(context, scope=scope, page_number=page_number, **kwargs))

        if total is None:
            total = page.get('total')

        rules = page.get('data') or []

        if not rules:
            return

        new_rules = 0
        for rule in rules:
            # Guard against a server that ignores pageNumber and keeps
            # returning the same page: without this the total check below
            # would be reached only after yielding duplicates.
            rule_id = rule.get('id')
            if rule_id is not None:
                if rule_id in seen_ids:
                    continue
                seen_ids.add(rule_id)
            new_rules += 1
            yield rule

        if new_rules == 0:
            return

        if total is not None and len(seen_ids) >= total:
            return

        page_number += 1


def get_rule(context: Context, rule_id: str) -> dict:
    """
    Retrieves the properties of a rule based on the provided rule ID.

    Args:
            context (Context): The context object.
            rule_id (str): The ID of the rule to retrieve properties for.

    Returns:
            dict: A dictionary containing the properties of the rule.
    """
    query = """
        query getRule($id: ID!) {
            management {
                id
                rule(id: $id) {
                    id
                    name
                    description
                    isActive
                    createdBy
                    modifiedBy
                    ownedBy
                    createdAt
                    modifiedAt
                    condition
                    actions
                    rules
                    sourceDetail {
                        id
                        name
                        type
                        __typename
                    }
                    author {
                        id
                        username
                        __typename
                    }
                    scope
                    isReprocessing
                    requiresAttention
                    __typename
                }
                __typename
            }
        }
        """
    variables = {
        "id": rule_id
    }

    return org_gql(context, query, variables)


def get_all_rule_details(
    context: Context,
    scope=RuleScope.DATA_PART,
    **kwargs,
) -> Generator[Any, Any, Any]:
    """
    Retrieves every rule in a scope in full, with its condition and actions.
    This function is a generator.

    `get_all_rules` returns rule summaries, which carry no condition or
    actions. This follows each one with a `get_rule` call, so it makes one
    request per rule:

    ```python
    rules = list(cluedin.rules.get_all_rule_details(context, RuleScope.ENTITY))
    processors, skipped = cluedin.rules.RuleProcessor.prepare(rules)
    ```

    Args:
            context (Context): The context object.
            scope (RuleScope, optional): The scope of the rules. Defaults to RuleScope.DATA_PART.
            **kwargs: Passed to `get_all_rules`.

    Yields:
            dict: Each rule's full `get_rule` response.
    """
    for rule in get_all_rules(context, scope=scope, **kwargs):
        rule_id = rule.get('id')
        if rule_id is None:
            continue
        yield get_rule(context, rule_id)
