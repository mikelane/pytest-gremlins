# Extensibility Guide

This guide explains how to extend pytest-gremlins with custom mutation operators for domain-specific testing needs.

## Why Create Custom Operators?

The built-in operators cover common mutation patterns, but your domain may have specific patterns worth testing:

- **Django ORM**: Mutate `filter()` to `exclude()`, swap `select_related()` with `prefetch_related()`
- **Financial calculations**: Flip rounding modes, swap floor/ceil operations
- **API clients**: Swap HTTP methods, alter timeout values
- **Data validation**: Remove required field checks, alter regex patterns

Custom operators let you catch bugs specific to your codebase that generic operators miss.

## Prerequisites

This guide assumes familiarity with:

- Python's `ast` module (Abstract Syntax Trees)
- Basic understanding of how pytest-gremlins works (see [Getting Started](getting-started.md))

If you're new to Python's AST, the [official ast module documentation](https://docs.python.org/3/library/ast.html)
and the [Green Tree Snakes tutorial](https://greentreesnakes.readthedocs.io/) are excellent resources.

## The GremlinOperator Protocol

All operators must implement the `GremlinOperator` protocol:

```python
from typing import Protocol
import ast

class GremlinOperator(Protocol):
    """Protocol for all mutation operators."""

    @property
    def name(self) -> str:
        """Unique identifier for this operator (e.g., 'comparison')."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description for reports."""
        ...

    def can_mutate(self, node: ast.AST) -> bool:
        """Return True if this operator can mutate the given AST node."""
        ...

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        """Return all mutated variants of this node."""
        ...
```

### Method Details

| Method         | Purpose                                                                         |
| -------------- | ------------------------------------------------------------------------------- |
| `name`         | Unique string identifier used in configuration and reports                      |
| `description`  | Shown in reports and `--help` output                                            |
| `can_mutate()` | Fast check - called for every AST node, return `True` only for nodes you handle |
| `mutate()`     | Generate mutation variants - called only when `can_mutate()` returns `True`     |

## Creating Your First Operator

Let's create a simple operator that flips string literals to empty strings - useful for catching untested display logic.

### Step 1: Create the Operator Class

```python
"""String empty mutation operator."""

from __future__ import annotations

import ast
import copy


class StringEmptyOperator:
    """Mutate non-empty string literals to empty strings.

    This operator targets string literals and replaces them with empty
    strings to verify that string values are actually being tested.

    Mutations:
        - "hello" -> ""
        - 'world' -> ''
    """

    @property
    def name(self) -> str:
        """Return unique identifier for this operator."""
        return 'string-empty'

    @property
    def description(self) -> str:
        """Return human-readable description for reports."""
        return 'Replace non-empty string literals with empty strings'

    def can_mutate(self, node: ast.AST) -> bool:
        """Return True if this is a non-empty string constant.

        Args:
            node: The AST node to check.

        Returns:
            True if this is a Constant node with a non-empty string value.
        """
        if not isinstance(node, ast.Constant):
            return False

        # Only mutate non-empty strings
        return isinstance(node.value, str) and len(node.value) > 0

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        """Return a mutation that replaces the string with an empty string.

        Args:
            node: The AST node to mutate.

        Returns:
            List containing one mutated AST node with an empty string.
        """
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            return []

        # Create a deep copy and replace the value
        mutated = copy.deepcopy(node)
        mutated.value = ''
        return [mutated]
```

### Step 2: Understand the AST

To write effective operators, you need to understand how Python code maps to AST nodes. Use `ast.dump()` to explore:

```python
import ast

code = '"hello world"'
tree = ast.parse(code, mode='eval')
print(ast.dump(tree, indent=2))
```

Output:

```text
Expression(
  body=Constant(value='hello world'))
```

This shows that string literals are `ast.Constant` nodes with a `value` attribute.

### Step 3: Test Your Operator

Always write tests for your operators:

```python
"""Tests for StringEmptyOperator."""

import ast

import pytest

from my_operators import StringEmptyOperator


class TestStringEmptyOperatorCanMutate:
    """Test the can_mutate method."""

    def test_returns_true_for_non_empty_string(self):
        operator = StringEmptyOperator()
        node = ast.parse('"hello"', mode='eval').body

        assert operator.can_mutate(node) is True

    def test_returns_false_for_empty_string(self):
        operator = StringEmptyOperator()
        node = ast.parse('""', mode='eval').body

        assert operator.can_mutate(node) is False

    def test_returns_false_for_integer(self):
        operator = StringEmptyOperator()
        node = ast.parse('42', mode='eval').body

        assert operator.can_mutate(node) is False


class TestStringEmptyOperatorMutate:
    """Test the mutate method."""

    def test_mutates_string_to_empty(self):
        operator = StringEmptyOperator()
        node = ast.parse('"hello"', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 1
        assert mutations[0].value == ''

    def test_original_node_is_not_modified(self):
        operator = StringEmptyOperator()
        node = ast.parse('"hello"', mode='eval').body

        operator.mutate(node)

        assert node.value == 'hello'
```

## Registration

Once your operator is implemented and tested, register it so pytest-gremlins can discover it.

### Method 1: Entry Points (Recommended for Packages)

If you're distributing your operator as a package, use Python entry points:

```toml
# pyproject.toml
[project.entry-points."pytest_gremlins.operators"]
my_operators = "my_package.operators:register_operators"
```

```python
# my_package/operators/__init__.py
from pytest_gremlins.operators import OperatorRegistry

from .string_empty import StringEmptyOperator


def register_operators() -> None:
    """Register custom operators with pytest-gremlins."""
    registry = OperatorRegistry()
    registry.register(StringEmptyOperator)
```

pytest-gremlins automatically discovers and calls `register_operators()` at startup.

### Method 2: Direct Registration (For Local Use)

For operators used only in your project, register them in `conftest.py`:

```python
# conftest.py
from pytest_gremlins.operators import OperatorRegistry

from my_operators import StringEmptyOperator


def pytest_configure(config):
    """Register custom operators."""
    registry = OperatorRegistry()
    registry.register(StringEmptyOperator)
```

### Method 3: Decorator Registration

The registry also supports a decorator pattern:

```python
from pytest_gremlins.operators import OperatorRegistry

registry = OperatorRegistry()


@registry.register_decorator('my-operator')
class MyOperator:
    """Custom operator registered via decorator."""

    @property
    def name(self) -> str:
        return 'my-operator'

    # ... rest of implementation
```

## AST Manipulation Patterns

### Pattern 1: Simple Value Replacement

Replace a value with a different value (like our string example):

```python
def mutate(self, node: ast.AST) -> list[ast.AST]:
    mutated = copy.deepcopy(node)
    mutated.value = new_value
    return [mutated]
```

### Pattern 2: Operator Swapping

Replace one operator with another (like comparison operators):

```python
MUTATIONS = {
    ast.Lt: [ast.LtE, ast.Gt],
    ast.LtE: [ast.Lt, ast.Gt],
}

def mutate(self, node: ast.AST) -> list[ast.AST]:
    mutations = []
    for replacement_type in self.MUTATIONS[type(node.op)]:
        mutated = copy.deepcopy(node)
        mutated.op = replacement_type()
        mutations.append(mutated)
    return mutations
```

### Pattern 3: Function Call Modification

Swap method names or arguments:

```python
def can_mutate(self, node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute):
        return False
    return node.func.attr == 'filter'

def mutate(self, node: ast.AST) -> list[ast.AST]:
    mutated = copy.deepcopy(node)
    mutated.func.attr = 'exclude'  # Django: filter() -> exclude()
    return [mutated]
```

### Pattern 4: Argument Removal

Remove optional arguments:

```python
def mutate(self, node: ast.AST) -> list[ast.AST]:
    if len(node.args) <= 1:
        return []

    mutated = copy.deepcopy(node)
    mutated.args = mutated.args[:-1]  # Remove last argument
    return [mutated]
```

### Pattern 5: Statement Modification

Modify entire statements:

```python
def can_mutate(self, node: ast.AST) -> bool:
    return isinstance(node, ast.Return)

def mutate(self, node: ast.AST) -> list[ast.AST]:
    mutated = copy.deepcopy(node)
    mutated.value = ast.Constant(value=None)  # return x -> return None
    return [mutated]
```

## Best Practices

### Naming Conventions

- Use lowercase with hyphens: `my-operator`, not `MyOperator` or `my_operator`
- Be descriptive: `django-queryset` not just `django`
- Prefix domain-specific operators: `fastapi-response`, `sqlalchemy-query`

### Keep can_mutate() Fast

`can_mutate()` is called for every AST node in the codebase. Keep it simple:

```python
# Good: Fast type check first
def can_mutate(self, node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    # More expensive checks after type check passes
    return self._is_target_function(node)

# Bad: Expensive operation for every node
def can_mutate(self, node: ast.AST) -> bool:
    return self._expensive_analysis(node)  # Called millions of times!
```

### Always Deep Copy

Never modify the original AST node:

```python
# Good
mutated = copy.deepcopy(node)
mutated.value = new_value
return [mutated]

# Bad - modifies the original!
node.value = new_value
return [node]
```

### Generate Meaningful Mutations

Avoid mutations that are obviously equivalent or trivially detected:

```python
# Good: Changes program behavior
"error message" -> ""  # Will be caught if error handling tested

# Less useful: Unlikely to be caught
"error message" -> "error_message"  # Same length, similar content
```

### Consider Scope

Decide whether your operator should target:

- **All occurrences**: Mutate every matching pattern
- **Specific contexts**: Only mutate in certain scopes (function bodies, class methods)

```python
def can_mutate(self, node: ast.AST) -> bool:
    # Only mutate strings inside function definitions
    # Requires tracking parent nodes during traversal
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and self._is_inside_function(node)
    )
```

### Document Your Mutations

Include clear documentation of what mutations your operator generates:

```python
class MyOperator:
    """Mutate XYZ patterns.

    Mutations:
        - pattern_a -> pattern_b
        - pattern_c -> pattern_d

    Why this matters:
        These mutations catch common bugs where developers assume X
        but the code actually does Y.
    """
```

## Complete Example: Django QuerySet Operator

Here's a complete, production-ready example for Django ORM mutations:

```python
"""Django QuerySet mutation operator.

Mutates Django ORM QuerySet method calls to catch untested query logic.
"""

from __future__ import annotations

import ast
import copy
from typing import ClassVar


class DjangoQuerySetOperator:
    """Mutate Django QuerySet method calls.

    This operator targets common Django ORM patterns and generates
    mutations that test whether your query logic is actually verified.

    Mutations:
        - filter() -> exclude()
        - exclude() -> filter()
        - first() -> last()
        - last() -> first()
        - exists() -> (removed, returns queryset)
        - order_by('x') -> order_by('-x')
    """

    METHOD_SWAPS: ClassVar[dict[str, str]] = {
        'filter': 'exclude',
        'exclude': 'filter',
        'first': 'last',
        'last': 'first',
        'select_related': 'prefetch_related',
        'prefetch_related': 'select_related',
    }

    @property
    def name(self) -> str:
        """Return unique identifier for this operator."""
        return 'django-queryset'

    @property
    def description(self) -> str:
        """Return human-readable description for reports."""
        return 'Swap Django QuerySet methods (filter/exclude, first/last, etc.)'

    def can_mutate(self, node: ast.AST) -> bool:
        """Return True if this is a swappable QuerySet method call.

        Args:
            node: The AST node to check.

        Returns:
            True if this is a Call node with a swappable method name.
        """
        if not isinstance(node, ast.Call):
            return False

        if not isinstance(node.func, ast.Attribute):
            return False

        return node.func.attr in self.METHOD_SWAPS

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        """Return mutation that swaps the method name.

        Args:
            node: The AST node to mutate.

        Returns:
            List containing one mutated AST node with swapped method.
        """
        if not isinstance(node, ast.Call):
            return []

        if not isinstance(node.func, ast.Attribute):
            return []

        method_name = node.func.attr
        if method_name not in self.METHOD_SWAPS:
            return []

        mutated = copy.deepcopy(node)
        mutated.func.attr = self.METHOD_SWAPS[method_name]
        return [mutated]
```

### Registration for the Django Example

```toml
# pyproject.toml for pytest-gremlins-django package
[project.entry-points."pytest_gremlins.operators"]
django = "pytest_gremlins_django:register_operators"
```

```python
# pytest_gremlins_django/__init__.py
from pytest_gremlins.operators import OperatorRegistry

from .queryset import DjangoQuerySetOperator


def register_operators() -> None:
    """Register Django-specific operators."""
    registry = OperatorRegistry()
    registry.register(DjangoQuerySetOperator)
```

### Using the Django Operator

Once registered, enable via configuration:

```toml
# pyproject.toml
[tool.pytest-gremlins]
operators = [
    "comparison",
    "boolean",
    "django-queryset",  # Your custom operator
]
```

Or via command line:

```bash
pytest --gremlins --gremlin-operators=django-queryset
```

## Testing Your Operators

### Unit Tests

Test each method independently:

```python
class TestMyOperatorCanMutate:
    """Test can_mutate returns correct values."""

    @pytest.mark.parametrize('code', ['target_pattern', 'another_target'])
    def test_returns_true_for_target_patterns(self, code):
        operator = MyOperator()
        node = ast.parse(code, mode='eval').body
        assert operator.can_mutate(node) is True

    @pytest.mark.parametrize('code', ['non_target', 'other_code'])
    def test_returns_false_for_non_targets(self, code):
        operator = MyOperator()
        node = ast.parse(code, mode='eval').body
        assert operator.can_mutate(node) is False


class TestMyOperatorMutate:
    """Test mutate generates correct mutations."""

    def test_generates_expected_mutation(self):
        operator = MyOperator()
        node = ast.parse('original_code', mode='eval').body

        mutations = operator.mutate(node)

        assert len(mutations) == 1
        # Verify the mutation is correct
        assert mutations[0].some_attribute == expected_value

    def test_does_not_modify_original(self):
        operator = MyOperator()
        node = ast.parse('original_code', mode='eval').body
        original_value = node.some_attribute

        operator.mutate(node)

        assert node.some_attribute == original_value
```

### Integration Tests

Test that mutations actually affect program behavior:

```python
def test_mutation_changes_behavior():
    """Verify the mutation produces different runtime behavior."""
    original_code = '''
def get_users():
    return User.objects.filter(active=True)
'''
    # Parse and apply mutation
    tree = ast.parse(original_code)
    operator = DjangoQuerySetOperator()

    # Find and mutate the call node
    for node in ast.walk(tree):
        if operator.can_mutate(node):
            mutations = operator.mutate(node)
            # Verify mutation changed filter to exclude
            assert 'exclude' in ast.unparse(mutations[0])
            break
```

## Troubleshooting

### My Operator Isn't Being Discovered

1. Check entry point group name: must be `pytest_gremlins.operators`
2. Verify your registration function is called
3. Run `pytest --gremlins --help` to see registered operators

### Mutations Aren't Being Generated

1. Add logging to `can_mutate()` to verify it's being called
2. Check that your AST pattern matching is correct with `ast.dump()`
3. Ensure `mutate()` returns a non-empty list

### Original Code Is Being Modified

Always use `copy.deepcopy()` before modifying nodes. AST nodes are mutable and shared.

### Performance Is Slow

1. Optimize `can_mutate()` - it's called for every node
2. Use `isinstance()` checks before more expensive operations
3. Consider caching expensive computations

## Summary

Creating custom operators involves:

1. **Implement the protocol**: `name`, `description`, `can_mutate()`, `mutate()`
2. **Understand your AST targets**: Use `ast.dump()` to explore patterns
3. **Always deep copy**: Never modify the original AST
4. **Write thorough tests**: Unit test each method
5. **Register properly**: Use entry points for packages, `conftest.py` for local use

Custom operators let you extend pytest-gremlins to catch domain-specific bugs that generic operators
miss. Start simple, test thoroughly, and iterate based on what bugs you find in your codebase.

## Further Reading

- [Python ast module documentation](https://docs.python.org/3/library/ast.html)
- [Green Tree Snakes AST tutorial](https://greentreesnakes.readthedocs.io/)
- [Operators Design Document](../design/OPERATORS.md) - Internal architecture details
- [Built-in Operators](operators.md) - Reference for existing operators
