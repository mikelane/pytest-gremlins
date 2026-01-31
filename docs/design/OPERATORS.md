# Gremlin Operators Design Document

> "Each gremlin is a small act of mischief in your code."

## Overview

Gremlin operators define **what mutations** pytest-gremlins can inject into code. Each operator
identifies specific AST patterns and generates mutated variants.

The architecture prioritizes:

1. **Extensibility** - Trivial to add new operators later
2. **Configurability** - Users enable/disable operators via config
3. **Third-party support** - External packages can register operators

---

## Architecture

### The Operator Protocol

```python
from abc import abstractmethod
from ast import AST
from typing import Protocol

class GremlinOperator(Protocol):
    """Interface for all mutation operators."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this operator (e.g., 'comparison', 'arithmetic')."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description for reports."""
        return self.name

    @abstractmethod
    def can_mutate(self, node: AST) -> bool:
        """Return True if this operator can mutate the given AST node."""
        ...

    @abstractmethod
    def mutate(self, node: AST) -> list[AST]:
        """Return all mutated variants of this node.

        Each returned AST node represents one gremlin.
        """
        ...
```

### The Registry

```python
from typing import Callable

class OperatorRegistry:
    """Central registry for gremlin operators."""

    _operators: dict[str, type[GremlinOperator]] = {}

    @classmethod
    def register(cls, name: str | None = None) -> Callable:
        """Decorator to register an operator class.

        Usage:
            @OperatorRegistry.register("comparison")
            class ComparisonOperator(GremlinOperator):
                ...

            # Or use the class's name property
            @OperatorRegistry.register()
            class ArithmeticOperator(GremlinOperator):
                name = "arithmetic"
                ...
        """
        def decorator(op_class: type[GremlinOperator]) -> type[GremlinOperator]:
            key = name or op_class.name
            cls._operators[key] = op_class
            return op_class
        return decorator

    @classmethod
    def get(cls, name: str) -> GremlinOperator:
        """Get a single operator by name."""
        return cls._operators[name]()

    @classmethod
    def get_all(cls, enabled: list[str] | None = None) -> list[GremlinOperator]:
        """Get operator instances.

        Args:
            enabled: If provided, only return these operators (in order).
                     If None, return all registered operators.
        """
        if enabled is None:
            return [op() for op in cls._operators.values()]
        return [
            cls._operators[name]()
            for name in enabled
            if name in cls._operators
        ]

    @classmethod
    def available(cls) -> list[str]:
        """List all registered operator names."""
        return list(cls._operators.keys())
```

### Entry Points for Third-Party Operators

External packages can register operators via Python entry points:

```toml
# In third-party package's pyproject.toml
[project.entry-points."pytest_gremlins.operators"]
django = "pytest_gremlins_django:register_operators"
```

```python
# In pytest_gremlins_django/__init__.py
from pytest_gremlins import OperatorRegistry

def register_operators():
    """Called by pytest-gremlins to register our operators."""
    from .operators import DjangoQuerySetOperator, DjangoModelOperator
    OperatorRegistry.register("django-queryset")(DjangoQuerySetOperator)
    OperatorRegistry.register("django-model")(DjangoModelOperator)
```

Auto-discovery at startup:

```python
from importlib.metadata import entry_points

def discover_operators():
    """Load operators from entry points."""
    for ep in entry_points(group="pytest_gremlins.operators"):
        register_fn = ep.load()
        register_fn()
```

---

## Configuration

Users configure operators in `pyproject.toml`:

```toml
[tool.pytest-gremlins]
# Explicit list of operators to use (in priority order)
operators = [
    "comparison",
    "boundary",
    "arithmetic",
    "boolean",
]

# Or exclude specific operators from the default set
exclude_operators = ["string"]

# Operator-specific configuration
[tool.pytest-gremlins.operators.comparison]
# Don't mutate == to != (too many false positives in your codebase)
skip_mutations = ["eq_to_noteq"]

[tool.pytest-gremlins.operators.arithmetic]
# Only mutate + and -
only_ops = ["add", "sub"]
```

---

## V1 Operators

### Tier 1: High-Value (Ship First)

These catch real bugs with low noise:

#### 1. Comparison Operator (`comparison`)

```python
@OperatorRegistry.register("comparison")
class ComparisonOperator(GremlinOperator):
    """Mutate comparison operators."""

    name = "comparison"
    description = "Swap comparison operators (<, <=, >, >=, ==, !=)"

    MUTATIONS = {
        ast.Lt:    [ast.LtE, ast.Gt],      # < → <=, >
        ast.LtE:   [ast.Lt, ast.Gt],       # <= → <, >
        ast.Gt:    [ast.GtE, ast.Lt],      # > → >=, <
        ast.GtE:   [ast.Gt, ast.Lt],       # >= → >, <
        ast.Eq:    [ast.NotEq],            # == → !=
        ast.NotEq: [ast.Eq],               # != → ==
    }
```

**Why high-value:** Boundary bugs are common and dangerous. Off-by-one errors kill.

#### 2. Boundary Operator (`boundary`)

```python
@OperatorRegistry.register("boundary")
class BoundaryOperator(GremlinOperator):
    """Mutate boundary conditions in comparisons."""

    name = "boundary"
    description = "Shift boundary values by ±1"
```

Targets patterns like:

```python
if x >= 18:      # → if x >= 19:, if x >= 17:
if len(s) > 0:   # → if len(s) > 1:, if len(s) > -1:
```

**Why high-value:** Catches the classic "should this be >= or >?" bugs.

#### 3. Boolean Operator (`boolean`)

```python
@OperatorRegistry.register("boolean")
class BooleanOperator(GremlinOperator):
    """Mutate boolean operators and values."""

    name = "boolean"
    description = "Swap and/or, negate conditions, flip True/False"

    # and ↔ or
    # not x → x
    # True ↔ False
    # if cond: → if not cond:
```

**Why high-value:** Logic bugs from wrong boolean operators are common.

#### 4. Arithmetic Operator (`arithmetic`)

```python
@OperatorRegistry.register("arithmetic")
class ArithmeticOperator(GremlinOperator):
    """Mutate arithmetic operators."""

    name = "arithmetic"
    description = "Swap arithmetic operators (+, -, *, /, //, %, **)"

    MUTATIONS = {
        ast.Add:      [ast.Sub],           # + → -
        ast.Sub:      [ast.Add],           # - → +
        ast.Mult:     [ast.Div],           # * → /
        ast.Div:      [ast.Mult],          # / → *
        ast.FloorDiv: [ast.Div],           # // → /
        ast.Mod:      [ast.FloorDiv],      # % → //
        ast.Pow:      [ast.Mult],          # ** → *
    }
```

**Why high-value:** Wrong arithmetic operator = wrong results.

#### 5. Return Value Operator (`return`)

```python
@OperatorRegistry.register("return")
class ReturnOperator(GremlinOperator):
    """Mutate return statements."""

    name = "return"
    description = "Replace return values with None, empty, or negated"

    # return x → return None
    # return True → return False
    # return [] → return [None]
    # return x → return -x (for numbers)
```

**Why high-value:** Tests should verify return values, not just that code runs.

### Tier 2: Medium-Value (Ship Second)

#### 6. Assignment Operator (`assignment`)

```python
@OperatorRegistry.register("assignment")
class AssignmentOperator(GremlinOperator):
    """Mutate augmented assignment operators."""

    name = "assignment"
    description = "Swap augmented assignments (+=, -=, *=, etc.)"

    # += ↔ -=
    # *= ↔ /=
```

#### 7. Unary Operator (`unary`)

```python
@OperatorRegistry.register("unary")
class UnaryOperator(GremlinOperator):
    """Mutate unary operators."""

    name = "unary"
    description = "Remove or swap unary operators (+x, -x, ~x, not x)"

    # -x → x, +x
    # +x → x, -x
    # ~x → x
```

#### 8. Exception Operator (`exception`)

```python
@OperatorRegistry.register("exception")
class ExceptionOperator(GremlinOperator):
    """Mutate exception handling."""

    name = "exception"
    description = "Modify exception types and handling"

    # except ValueError: → except TypeError:
    # except (A, B): → except A:
    # raise X → raise Y
```

### Tier 3: Lower-Value / Higher-Noise (Optional)

#### 9. Statement Deletion (`statement`)

```python
@OperatorRegistry.register("statement")
class StatementDeletionOperator(GremlinOperator):
    """Delete entire statements."""

    name = "statement"
    description = "Remove statements to test coverage"

    # logging.info(...) → (deleted)
    # x = calculate() → (deleted)
```

**Trade-off:** High noise on logging/debug code, but catches dead code.

#### 10. String Operator (`string`)

```python
@OperatorRegistry.register("string")
class StringOperator(GremlinOperator):
    """Mutate string literals."""

    name = "string"
    description = "Modify string literals"

    # "hello" → ""
    # "hello" → "gremlin"
    # f"Hello {name}" → f"Hello {name}!"
```

**Trade-off:** Often produces equivalent mutants (strings used for display only).

#### 11. Container Operator (`container`)

```python
@OperatorRegistry.register("container")
class ContainerOperator(GremlinOperator):
    """Mutate container literals."""

    name = "container"
    description = "Modify list, dict, set literals"

    # [] → [None]
    # {} → {"gremlin": None}
    # [1, 2, 3] → [1, 2]
```

### Future / Python-Specific (Post-V1)

These require more design work:

- **Match Statement Operator** - Mutate `match`/`case` patterns
- **Comprehension Operator** - Mutate filters and expressions in comprehensions
- **Decorator Operator** - Remove or modify decorators
- **Async Operator** - `await` → remove, `async for` → `for`
- **Type Hint Operator** - For runtime-checked types (Pydantic, etc.)

---

## Operator Priority and Ordering

When running gremlins, order matters for fast feedback:

### Default Priority (Highest First)

1. **comparison** - Most likely to catch real bugs
2. **boundary** - Boundary conditions are critical
3. **boolean** - Logic errors are common
4. **return** - Return values must be tested
5. **arithmetic** - Wrong math = wrong results
6. **assignment** - Less common bugs
7. **unary** - Edge cases
8. **exception** - Error handling paths
9. **statement** - Coverage gaps (noisy)
10. **string** - Often equivalent (noisy)
11. **container** - Often equivalent (noisy)

### Smart Ordering Strategies

Beyond static priority, we can order dynamically:

```python
class OrderingStrategy(Protocol):
    def order(self, gremlins: list[Gremlin]) -> list[Gremlin]: ...

class PriorityOrdering(OrderingStrategy):
    """Order by operator priority (default)."""
    ...

class CoverageOrdering(OrderingStrategy):
    """Least-covered code first (more likely to survive)."""
    ...

class HistoryOrdering(OrderingStrategy):
    """Previously-surviving gremlins first (regression check)."""
    ...

class RandomOrdering(OrderingStrategy):
    """Random shuffle (for sampling)."""
    ...
```

---

## Equivalent Mutant Detection

Some mutations produce equivalent behavior. We can detect and skip some:

### Compile-Time Detection

```python
class EquivalentMutantFilter:
    """Filter out obviously equivalent mutants."""

    def is_equivalent(self, original: AST, mutated: AST) -> bool:
        # Compile both, compare bytecode
        original_code = compile(original, "<gremlin>", "exec")
        mutated_code = compile(mutated, "<gremlin>", "exec")
        return original_code.co_code == mutated_code.co_code
```

### Pattern-Based Suppression

Known equivalent patterns:

```python
EQUIVALENT_PATTERNS = [
    # x + 0 → x - 0 (equivalent)
    # x * 1 → x / 1 (equivalent)
    # not not x → x (equivalent)
]
```

### User Suppression

```toml
[tool.pytest-gremlins]
# Skip mutations in these patterns
suppress_patterns = [
    "logging.*",           # Don't mutate logging calls
    "*.migrations.*",      # Don't mutate Django migrations
]
```

---

## Summary

### V1 Scope

Ship these 5 operators first:

1. `comparison` - Comparison operators
2. `boundary` - Boundary value shifts
3. `boolean` - Boolean logic
4. `arithmetic` - Arithmetic operators
5. `return` - Return values

### Architecture Guarantees

1. **Adding operators is trivial** - Implement protocol, use `@register` decorator
2. **Users control what runs** - Config enables/disables operators
3. **Third parties can extend** - Entry points for external packages
4. **Ordering is configurable** - Priority, coverage-based, or custom

### Open Questions

1. **Boundary operator scope** - Only numeric literals, or also `len()`, `range()`, etc.?
2. **Statement deletion heuristics** - How to avoid noise on logging/debug?
3. **f-string mutation** - How deep do we go? Just the template, or expressions too?
