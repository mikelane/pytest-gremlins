# Operators Module

The operators module provides the mutation operator system for pytest-gremlins. Operators identify
AST patterns and generate mutated variants (gremlins).

## Overview

Mutation operators are the core of mutation testing. Each operator:

1. **Identifies** specific AST node patterns it can mutate
2. **Generates** one or more mutated variants of matching nodes
3. **Provides** human-readable descriptions for reports

## Module Exports

```python
from pytest_gremlins.operators import (
    GremlinOperator,      # Protocol for all operators
    OperatorRegistry,     # Central operator registration
    ArithmeticOperator,   # +, -, *, /, //, %, **
    BooleanOperator,      # and/or, True/False, not
    BoundaryOperator,     # Off-by-one (value +/- 1)
    ComparisonOperator,   # <, <=, >, >=, ==, !=
    ReturnOperator,       # return value mutations
)
```

---

## Protocol

### GremlinOperator

All mutation operators must implement this protocol.

::: pytest_gremlins.operators.protocol.GremlinOperator
    options:
      show_root_heading: true
      show_source: true

### Protocol Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `name` | `str` | Unique identifier (e.g., 'comparison') |
| `description` | `str` | Human-readable description |
| `can_mutate(node)` | `bool` | Whether operator can mutate this node |
| `mutate(node)` | `list[AST]` | List of mutated AST variants |

### Implementing a Custom Operator

```python
import ast
import copy

class CustomOperator:
    """Example custom mutation operator."""

    @property
    def name(self) -> str:
        return 'custom'

    @property
    def description(self) -> str:
        return 'Custom mutations for demonstration'

    def can_mutate(self, node: ast.AST) -> bool:
        # Return True for nodes this operator handles
        return isinstance(node, ast.Constant) and node.value == 42

    def mutate(self, node: ast.AST) -> list[ast.AST]:
        # Return list of mutated variants
        if not isinstance(node, ast.Constant):
            return []
        mutated = copy.deepcopy(node)
        mutated.value = 0
        return [mutated]
```

---

## Registry

### OperatorRegistry

Central registry for managing mutation operators.

::: pytest_gremlins.operators.registry.OperatorRegistry
    options:
      show_root_heading: true
      show_source: true
      members:
        - "__init__"
        - register
        - register_decorator
        - get
        - get_all
        - available

### Registry Methods

| Method | Description |
|--------|-------------|
| `register(cls, name=None)` | Register an operator class |
| `register_decorator(name=None)` | Decorator for registration |
| `get(name)` | Get single operator by name |
| `get_all(enabled=None)` | Get list of operator instances |
| `available()` | List registered operator names |

### Usage Examples

```python
from pytest_gremlins.operators import OperatorRegistry, ComparisonOperator

# Create a registry
registry = OperatorRegistry()

# Register operators
registry.register(ComparisonOperator)
registry.register(CustomOperator, name='custom')

# List available operators
print(registry.available())  # ['comparison', 'custom']

# Get specific operator
op = registry.get('comparison')

# Get all operators
all_ops = registry.get_all()

# Get subset of operators
subset = registry.get_all(enabled=['comparison', 'arithmetic'])
```

### Using the Decorator

```python
registry = OperatorRegistry()

@registry.register_decorator('my_operator')
class MyOperator:
    @property
    def name(self) -> str:
        return 'my_operator'
    # ...
```

---

## Built-in Operators

pytest-gremlins includes five built-in operators covering common mutation patterns.

### ComparisonOperator

Mutates comparison operators to catch boundary and off-by-one bugs.

::: pytest_gremlins.operators.comparison.ComparisonOperator
    options:
      show_root_heading: true
      show_source: true

#### Mutations

| Original | Mutations |
|----------|-----------|
| `<` | `<=`, `>` |
| `<=` | `<`, `>` |
| `>` | `>=`, `<` |
| `>=` | `>`, `<` |
| `==` | `!=` |
| `!=` | `==` |

#### Example

```python
# Original code
if age >= 18:
    return "adult"

# Mutations generated:
# 1. if age > 18:   (>= to >)
# 2. if age < 18:   (>= to <)
```

---

### ArithmeticOperator

Mutates arithmetic operators to catch calculation errors.

::: pytest_gremlins.operators.arithmetic.ArithmeticOperator
    options:
      show_root_heading: true
      show_source: true

#### Mutations

| Original | Mutations |
|----------|-----------|
| `+` | `-` |
| `-` | `+` |
| `*` | `/` |
| `/` | `*` |
| `//` | `/` |
| `%` | `//` |
| `**` | `*` |

#### Example

```python
# Original code
total = price * quantity

# Mutation generated:
# total = price / quantity  (* to /)
```

---

### BooleanOperator

Mutates boolean logic to catch logic errors.

::: pytest_gremlins.operators.boolean.BooleanOperator
    options:
      show_root_heading: true
      show_source: true

#### Mutations

| Original | Mutations |
|----------|-----------|
| `and` | `or` |
| `or` | `and` |
| `not x` | `x` |
| `True` | `False` |
| `False` | `True` |

#### Example

```python
# Original code
if is_admin and is_active:
    grant_access()

# Mutation generated:
# if is_admin or is_active:  (and to or)
```

---

### BoundaryOperator

Mutates integer constants in comparisons by +/- 1 to catch off-by-one errors.

::: pytest_gremlins.operators.boundary.BoundaryOperator
    options:
      show_root_heading: true
      show_source: true

#### Mutations

For each integer constant in a comparison:

| Original | Mutations |
|----------|-----------|
| `n` | `n - 1`, `n + 1` |

#### Example

```python
# Original code
if age >= 18:
    return "adult"

# Mutations generated:
# 1. if age >= 17:   (18 to 17)
# 2. if age >= 19:   (18 to 19)
```

!!! note
    BoundaryOperator only targets integer constants within comparison expressions.
    Boolean values (`True`/`False`) are excluded.

---

### ReturnOperator

Mutates return statements to verify tests check return values.

::: pytest_gremlins.operators.return_value.ReturnOperator
    options:
      show_root_heading: true
      show_source: true

#### Mutations

| Original | Mutations |
|----------|-----------|
| `return x` | `return None` |
| `return True` | `return False` |
| `return False` | `return True` |

#### Example

```python
# Original code
def is_valid(data):
    return True

# Mutations generated:
# 1. return None    (value to None)
# 2. return False   (True to False)
```

---

## Operator Selection

### Via CLI

```bash
# Use all operators (default)
pytest --gremlins

# Use specific operators
pytest --gremlins --gremlin-operators=comparison,boundary

# Use single operator
pytest --gremlins --gremlin-operators=arithmetic
```

### Via pyproject.toml

```toml
[tool.pytest-gremlins]
operators = ["comparison", "arithmetic", "boolean"]
```

### Programmatically

```python
from pytest_gremlins.instrumentation.transformer import get_default_registry

# Get the default registry with all 5 operators
registry = get_default_registry()

# Get specific operators
ops = registry.get_all(enabled=['comparison', 'boundary'])
```

---

## Operator Statistics

The default operators generate mutations as follows:

| Operator | AST Nodes | Mutations per Node |
|----------|-----------|-------------------|
| comparison | `Compare` | 1-2 per operator |
| arithmetic | `BinOp` | 1 |
| boolean | `BoolOp`, `UnaryOp`, `Constant` | 1 |
| boundary | `Compare` with int constants | 2 per constant |
| return | `Return` | 1-2 |

A typical function with 10 lines might generate 5-15 gremlins depending on the code patterns present.
