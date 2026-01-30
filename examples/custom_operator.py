"""Example custom mutation operator for pytest-gremlins.

This module demonstrates how to create a custom mutation operator that
can be used with pytest-gremlins. It includes a complete implementation,
registration examples, and test cases.

Usage:
    1. Copy this file to your project
    2. Modify the operator to match your domain patterns
    3. Register it via conftest.py or entry points
    4. Enable it in your configuration

Example registration in conftest.py:
    from pytest_gremlins.operators import OperatorRegistry
    from examples.custom_operator import StringEmptyOperator

    def pytest_configure(config):
        registry = OperatorRegistry()
        registry.register(StringEmptyOperator)
"""

from __future__ import annotations

import ast
import copy
from typing import TYPE_CHECKING, ClassVar


if TYPE_CHECKING:
    pass


# =============================================================================
# Example 1: Simple String Mutation Operator
# =============================================================================


class StringEmptyOperator:
    """Mutate non-empty string literals to empty strings.

    This operator targets string literals and replaces them with empty
    strings to verify that string values are actually being tested.
    Useful for catching display logic and error message testing gaps.

    Mutations:
        - "hello" -> ""
        - 'error message' -> ''
        - f"template" -> f""

    Why this matters:
        If your tests don't verify the actual content of strings (error
        messages, display text, API responses), this mutation will survive,
        indicating a test gap.

    Example:
        >>> import ast
        >>> operator = StringEmptyOperator()
        >>> node = ast.parse('"hello"', mode='eval').body
        >>> operator.can_mutate(node)
        True
        >>> mutations = operator.mutate(node)
        >>> len(mutations)
        1
        >>> mutations[0].value
        ''
    """

    @property
    def name(self) -> str:
        """Return unique identifier for this operator.

        Returns:
            The string 'string-empty' which is used in configuration
            and reports to identify this operator.
        """
        return 'string-empty'

    @property
    def description(self) -> str:
        """Return human-readable description for reports.

        Returns:
            A description shown in mutation reports and help output.
        """
        return 'Replace non-empty string literals with empty strings'

    def can_mutate(self, node: ast.AST) -> bool:
        """Return True if this is a non-empty string constant.

        This method is called for every AST node during analysis,
        so it must be fast. We check the node type first (cheap)
        before checking the value (slightly more expensive).

        Args:
            node: The AST node to check.

        Returns:
            True if this is a Constant node with a non-empty string value.
        """
        # Fast type check first
        if not isinstance(node, ast.Constant):
            return False

        # Only mutate non-empty strings
        return isinstance(node.value, str) and len(node.value) > 0

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        """Return a mutation that replaces the string with an empty string.

        Creates a deep copy of the node to avoid modifying the original
        AST, then replaces the string value with an empty string.

        Args:
            node: The AST node to mutate.

        Returns:
            List containing one mutated AST node with an empty string.
            Returns empty list if the node cannot be mutated.
        """
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            return []

        # IMPORTANT: Always deep copy to avoid modifying the original AST
        mutated = copy.deepcopy(node)
        mutated.value = ''
        return [mutated]


# =============================================================================
# Example 2: Method Swap Operator (Domain-Specific)
# =============================================================================


class HttpMethodOperator:
    """Mutate HTTP method strings in API client code.

    This operator targets common HTTP method strings and swaps them
    to verify that your tests actually check the HTTP method used.

    Mutations:
        - 'GET' -> 'POST'
        - 'POST' -> 'GET'
        - 'PUT' -> 'PATCH'
        - 'PATCH' -> 'PUT'
        - 'DELETE' -> 'GET'

    Why this matters:
        API clients often construct requests with method strings. If tests
        don't verify the correct method is used, bugs where GET is used
        instead of POST would go undetected.

    Example:
        >>> import ast
        >>> operator = HttpMethodOperator()
        >>> node = ast.parse('"POST"', mode='eval').body
        >>> operator.can_mutate(node)
        True
        >>> mutations = operator.mutate(node)
        >>> mutations[0].value
        'GET'
    """

    # Define the method swaps - each method maps to its replacement
    METHOD_SWAPS: ClassVar[dict[str, str]] = {
        'GET': 'POST',
        'POST': 'GET',
        'PUT': 'PATCH',
        'PATCH': 'PUT',
        'DELETE': 'GET',
        'HEAD': 'GET',
        'OPTIONS': 'GET',
    }

    @property
    def name(self) -> str:
        """Return unique identifier for this operator."""
        return 'http-method'

    @property
    def description(self) -> str:
        """Return human-readable description for reports."""
        return 'Swap HTTP method strings (GET/POST, PUT/PATCH, etc.)'

    def can_mutate(self, node: ast.AST) -> bool:
        """Return True if this is an HTTP method string.

        Args:
            node: The AST node to check.

        Returns:
            True if this is a Constant node with an HTTP method string.
        """
        if not isinstance(node, ast.Constant):
            return False

        if not isinstance(node.value, str):
            return False

        # Check if it's an HTTP method (case-insensitive matching,
        # but we store and check uppercase)
        return node.value.upper() in self.METHOD_SWAPS

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        """Return mutation that swaps the HTTP method.

        Preserves the case of the original method string.

        Args:
            node: The AST node to mutate.

        Returns:
            List containing one mutated AST node with swapped method.
        """
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            return []

        original = node.value
        upper_original = original.upper()

        if upper_original not in self.METHOD_SWAPS:
            return []

        replacement = self.METHOD_SWAPS[upper_original]

        # Preserve original case
        if original.islower():
            replacement = replacement.lower()
        elif original[0].isupper() and original[1:].islower():
            replacement = replacement.capitalize()
        # Otherwise keep uppercase (the default)

        mutated = copy.deepcopy(node)
        mutated.value = replacement
        return [mutated]


# =============================================================================
# Example 3: Function Call Operator
# =============================================================================


class ListMethodOperator:
    """Mutate list method calls.

    This operator swaps related list methods to verify that tests
    check the specific list operation being performed.

    Mutations:
        - .append(x) -> .extend([x])
        - .pop() -> .pop(0)
        - .sort() -> .sort(reverse=True)

    Example:
        >>> import ast
        >>> operator = ListMethodOperator()
        >>> code = 'my_list.append(item)'
        >>> tree = ast.parse(code, mode='eval')
        >>> for node in ast.walk(tree):
        ...     if operator.can_mutate(node):
        ...         print('Found target!')
        Found target!
    """

    TARGET_METHODS: ClassVar[set[str]] = {'append', 'pop', 'sort', 'reverse'}

    @property
    def name(self) -> str:
        """Return unique identifier for this operator."""
        return 'list-method'

    @property
    def description(self) -> str:
        """Return human-readable description for reports."""
        return 'Mutate list method calls (append, pop, sort, reverse)'

    def can_mutate(self, node: ast.AST) -> bool:
        """Return True if this is a target list method call.

        Args:
            node: The AST node to check.

        Returns:
            True if this is a Call node with a target list method.
        """
        if not isinstance(node, ast.Call):
            return False

        if not isinstance(node.func, ast.Attribute):
            return False

        return node.func.attr in self.TARGET_METHODS

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        """Return mutations for the list method call.

        Args:
            node: The AST node to mutate.

        Returns:
            List of mutated AST nodes.
        """
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            return []

        method = node.func.attr
        mutations: list[ast.AST] = []

        if method == 'append':
            # append(x) -> insert(0, x) - adds at beginning instead of end
            mutated = copy.deepcopy(node)
            mutated.func.attr = 'insert'
            # Prepend 0 as the first argument
            zero_node = ast.Constant(value=0)
            mutated.args = [zero_node, *mutated.args]
            mutations.append(mutated)

        elif method == 'pop':
            if not node.args:
                # pop() -> pop(0) - removes first instead of last
                mutated = copy.deepcopy(node)
                mutated.args = [ast.Constant(value=0)]
                mutations.append(mutated)

        elif method == 'sort':
            # sort() -> sort(reverse=True)
            mutated = copy.deepcopy(node)
            # Check if reverse is already specified
            has_reverse = any(kw.arg == 'reverse' for kw in node.keywords)
            if not has_reverse:
                mutated.keywords.append(
                    ast.keyword(arg='reverse', value=ast.Constant(value=True))
                )
                mutations.append(mutated)

        elif method == 'reverse':
            # reverse() -> (remove the call entirely by returning empty)
            # This is a no-op mutation - we'd need statement-level mutation
            pass

        return mutations


# =============================================================================
# Registration Examples
# =============================================================================


def register_all_examples() -> None:
    """Register all example operators.

    Call this function from your conftest.py or entry point to register
    all the example operators:

        # conftest.py
        from examples.custom_operator import register_all_examples

        def pytest_configure(config):
            register_all_examples()
    """
    # Import here to avoid circular imports
    from pytest_gremlins.operators import OperatorRegistry

    registry = OperatorRegistry()
    registry.register(StringEmptyOperator)
    registry.register(HttpMethodOperator)
    registry.register(ListMethodOperator)


# =============================================================================
# Test Cases
# =============================================================================
# These would typically go in a separate test file, but are included here
# for completeness as documentation.


def _run_example_tests() -> None:
    """Run basic tests to verify the operators work.

    This is for documentation/example purposes. In a real project,
    use pytest with proper test files.
    """
    import ast

    # Test StringEmptyOperator
    print('Testing StringEmptyOperator...')
    op = StringEmptyOperator()
    assert op.name == 'string-empty'

    node = ast.parse('"hello"', mode='eval').body
    assert op.can_mutate(node) is True
    mutations = op.mutate(node)
    assert len(mutations) == 1
    assert mutations[0].value == ''
    assert node.value == 'hello'  # Original unchanged
    print('  PASSED')

    # Test HttpMethodOperator
    print('Testing HttpMethodOperator...')
    op2 = HttpMethodOperator()
    assert op2.name == 'http-method'

    node = ast.parse('"POST"', mode='eval').body
    assert op2.can_mutate(node) is True
    mutations = op2.mutate(node)
    assert mutations[0].value == 'GET'
    print('  PASSED')

    # Test case preservation
    node = ast.parse('"post"', mode='eval').body
    mutations = op2.mutate(node)
    assert mutations[0].value == 'get'
    print('  Case preservation PASSED')

    # Test ListMethodOperator
    print('Testing ListMethodOperator...')
    op3 = ListMethodOperator()
    assert op3.name == 'list-method'

    tree = ast.parse('items.append(x)', mode='eval')
    for node in ast.walk(tree):
        if op3.can_mutate(node):
            mutations = op3.mutate(node)
            assert len(mutations) == 1
            # Verify mutation changed append to insert
            assert mutations[0].func.attr == 'insert'
            print('  PASSED')
            break

    print('\nAll example tests passed!')


if __name__ == '__main__':
    # Run example tests when executed directly
    _run_example_tests()
