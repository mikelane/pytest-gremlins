# Operators

Operators define what types of mutations pytest-gremlins can inject into your code. Each operator
targets specific code patterns and generates gremlin variants that your tests should catch.

## Overview

pytest-gremlins ships with five built-in operators, each designed to catch different categories
of bugs:

| Operator | Target | Bug Category |
|----------|--------|--------------|
| `comparison` | `<`, `<=`, `>`, `>=`, `==`, `!=` | Off-by-one errors, boundary bugs |
| `boundary` | Integer constants in comparisons | Boundary condition bugs |
| `boolean` | `and`, `or`, `not`, `True`, `False` | Logic errors |
| `arithmetic` | `+`, `-`, `*`, `/`, `//`, `%`, `**` | Calculation errors |
| `return` | Return statements | Return value verification |

## Built-in Operators

### comparison

The comparison operator mutates comparison operators to catch off-by-one and boundary condition bugs.

**What it mutates:**

| Original | Mutations  |
| -------- | ---------- |
| `<`      | `<=`, `>`  |
| `<=`     | `<`, `>`   |
| `>`      | `>=`, `<`  |
| `>=`     | `>`, `<`   |
| `==`     | `!=`       |
| `!=`     | `==`       |

**Example mutations:**

```python
# Original code
def is_adult(age: int) -> bool:
    return age >= 18

# Gremlin 1: >= becomes >
def is_adult(age: int) -> bool:
    return age > 18  # Fails for age=18

# Gremlin 2: >= becomes <
def is_adult(age: int) -> bool:
    return age < 18  # Completely inverted
```

**When it catches bugs:**

- Tests do not check boundary values (e.g., exactly 18)
- Tests do not verify both sides of a condition
- Tests use only extreme values (0, 100) but not edge cases

**When to use:**

- Always enabled (high-value, low-noise)
- Essential for any code with conditional logic

**When to disable:**

- Rarely necessary
- Consider disabling if you have many equality checks on strings/enums that produce false positives

**Configuration:**

```toml
[tool.pytest-gremlins.operators.comparison]
skip_mutations = ["eq_to_noteq"]  # Skip == -> != mutation
```

---

### boundary

The boundary operator shifts integer constants in comparisons by +/- 1 to catch off-by-one errors.

**What it mutates:**

| Original  | Mutations            |
| --------- | -------------------- |
| `x >= 18` | `x >= 17`, `x >= 19` |
| `x > 0`   | `x > -1`, `x > 1`    |
| `x < 100` | `x < 99`, `x < 101`  |
| `x == 5`  | `x == 4`, `x == 6`   |

**Example mutations:**

```python
# Original code
def validate_password(password: str) -> bool:
    return len(password) >= 8

# Gremlin 1: 8 becomes 7
def validate_password(password: str) -> bool:
    return len(password) >= 7  # Accepts 7-char passwords

# Gremlin 2: 8 becomes 9
def validate_password(password: str) -> bool:
    return len(password) >= 9  # Rejects 8-char passwords
```

**When it catches bugs:**

- Tests do not use boundary values
- Tests skip "fence post" scenarios
- Tests use round numbers but not exact boundaries

**When to use:**

- Code with numeric thresholds
- Validation logic
- Loop boundaries

**When to disable:**

- Code with many magic numbers that are not boundaries
- Performance-sensitive mutation testing (generates many gremlins)

**Configuration:**

```toml
[tool.pytest-gremlins]
operators = ["comparison"]  # Exclude boundary for faster runs
```

---

### boolean

The boolean operator mutates boolean operators and values to catch logic errors.

**What it mutates:**

| Original | Mutations |
| -------- | --------- |
| `and`    | `or`      |
| `or`     | `and`     |
| `not x`  | `x`       |
| `True`   | `False`   |
| `False`  | `True`    |

**Example mutations:**

```python
# Original code
def can_access(user):
    return user.is_admin and user.is_active

# Gremlin 1: and becomes or
def can_access(user):
    return user.is_admin or user.is_active  # Security bug!

# Original code
def is_valid():
    return True

# Gremlin 2: True becomes False
def is_valid():
    return False  # Always fails validation
```

**When it catches bugs:**

- Tests do not verify all condition combinations
- Tests assume boolean functions return the correct value
- Tests do not check negation logic

**When to use:**

- Authentication and authorization code
- Feature flags
- Complex conditional logic

**When to disable:**

- Rarely necessary
- Consider disabling for code with many boolean constants used for configuration

---

### arithmetic

The arithmetic operator mutates arithmetic operators to catch calculation errors.

**What it mutates:**

| Original | Mutations |
| -------- | --------- |
| `+`      | `-`       |
| `-`      | `+`       |
| `*`      | `/`       |
| `/`      | `*`       |
| `//`     | `/`       |
| `%`      | `//`      |
| `**`     | `*`       |

**Example mutations:**

```python
# Original code
def calculate_total(price: float, quantity: int) -> float:
    return price * quantity

# Gremlin: * becomes /
def calculate_total(price: float, quantity: int) -> float:
    return price / quantity  # Completely wrong calculation

# Original code
def next_even(n: int) -> int:
    return n + n % 2

# Gremlin: % becomes //
def next_even(n: int) -> int:
    return n + n // 2  # Wrong result
```

**When it catches bugs:**

- Tests do not verify actual calculation results
- Tests only check return type, not value
- Tests use example values that happen to work with multiple operators

**When to use:**

- Financial calculations
- Scientific computing
- Any code where math correctness matters

**When to disable:**

- Code with trivial arithmetic (incrementing counters)
- Tests that naturally verify calculations through integration

---

### return

The return operator mutates return statements to verify that tests actually check return values.

**What it mutates:**

| Original       | Mutations             |
| -------------- | --------------------- |
| `return x`     | `return None`         |
| `return True`  | `return False`        |
| `return False` | `return True`         |

**Example mutations:**

```python
# Original code
def get_user(user_id: int) -> User:
    return database.find(user_id)

# Gremlin: return x becomes return None
def get_user(user_id: int) -> User:
    return None  # Caller may not handle None

# Original code
def is_authenticated() -> bool:
    return True

# Gremlin: return True becomes return False
def is_authenticated() -> bool:
    return False  # Always denies access
```

**When it catches bugs:**

- Tests call functions but do not assert on return values
- Tests assume functions work without verifying
- Tests check side effects but not return values

**When to use:**

- Functions that return important values
- Validation functions
- Data retrieval functions

**When to disable:**

- Procedures (functions that return nothing meaningful)
- Builder pattern methods (return `self`)

## Operator Selection Strategies

### Strategy 1: All Operators (Default)

Use all operators for comprehensive mutation testing:

```bash
pytest --gremlins
```

Best for:

- Thorough testing
- CI/CD pipelines with time budget
- Critical codebases

### Strategy 2: High-Value Only

Focus on operators that catch the most real bugs:

```toml
[tool.pytest-gremlins]
operators = ["comparison", "boolean"]
```

Or via command line:

```bash
pytest --gremlins --gremlin-operators=comparison,boolean
```

Best for:

- Quick feedback during development
- Large codebases with time constraints
- First-time mutation testing

### Strategy 3: Domain-Specific

Choose operators based on your code's domain:

**Financial/E-commerce:**

```toml
operators = ["arithmetic", "comparison", "boundary"]
```

**Authentication/Authorization:**

```toml
operators = ["boolean", "comparison", "return"]
```

**Data Processing:**

```toml
operators = ["arithmetic", "return"]
```

### Strategy 4: Incremental Adoption

Start small and expand:

1. **Week 1**: `comparison` only
2. **Week 2**: Add `boolean`
3. **Week 3**: Add `boundary`
4. **Week 4**: Add `arithmetic` and `return`

```bash
# Week 1
pytest --gremlins --gremlin-operators=comparison

# Week 2
pytest --gremlins --gremlin-operators=comparison,boolean

# And so on...
```

## Operator Priority

When pytest-gremlins runs, operators execute in priority order. Higher-priority gremlins are tested
first for faster feedback.

Default priority (highest first):

1. **comparison** - Most likely to catch real bugs
2. **boundary** - Boundary conditions are critical
3. **boolean** - Logic errors are common
4. **return** - Return values must be verified
5. **arithmetic** - Calculation errors

This means if you have a time budget and need to stop early, the most valuable gremlins are
tested first.

## Understanding Gremlin Output

When a gremlin survives, the output shows:

```text
Top surviving gremlins:
  src/auth.py:42    >= -> >     (comparison)
  src/utils.py:17   + -> -      (arithmetic)
  src/api.py:88     True -> False (return)
```

Breaking down each line:

| Part | Meaning |
|------|---------|
| `src/auth.py:42` | File and line number |
| `>= -> >` | Original code and mutation |
| `(comparison)` | Operator that created this gremlin |

## Equivalent Mutants

Some mutations produce identical behavior to the original code. These are called "equivalent
mutants" and cannot be caught by any test.

**Example:**

```python
# Original
x = a + 0

# Mutation: + becomes -
x = a - 0  # Same result!
```

pytest-gremlins attempts to detect and skip some equivalent mutants, but not all can be detected
automatically. A mutation score below 100% is normal and expected.

## Writing Tests That Catch Gremlins

### For comparison operator:

Test boundary values explicitly:

```python
# Bad: Only tests happy path
def test_is_adult():
    assert is_adult(25) is True

# Good: Tests boundary
def test_is_adult_boundary():
    assert is_adult(17) is False
    assert is_adult(18) is True
    assert is_adult(19) is True
```

### For boolean operator:

Test all condition combinations:

```python
# Bad: Only tests one combination
def test_can_access():
    admin_user = User(is_admin=True, is_active=True)
    assert can_access(admin_user) is True

# Good: Tests all combinations
def test_can_access_combinations():
    assert can_access(User(is_admin=True, is_active=True)) is True
    assert can_access(User(is_admin=True, is_active=False)) is False
    assert can_access(User(is_admin=False, is_active=True)) is False
    assert can_access(User(is_admin=False, is_active=False)) is False
```

### For arithmetic operator:

Use values that expose wrong operators:

```python
# Bad: 1 * 2 == 2 and 2 + 2 == 4 (different)
def test_multiply():
    assert multiply(2, 2) == 4  # Also passes for add!

# Good: Use values that differ for each operator
def test_multiply_distinct():
    assert multiply(3, 4) == 12  # 3 + 4 = 7, 3 * 4 = 12
```

### For return operator:

Always assert on return values:

```python
# Bad: Calls function without checking return
def test_get_user():
    get_user(123)  # No assertion!

# Good: Assert on the return value
def test_get_user():
    user = get_user(123)
    assert user is not None
    assert user.id == 123
```

## Custom Operators

pytest-gremlins supports custom operators for domain-specific mutations.
See the [API Reference](../api/index.md) for details on implementing custom operators.

Example third-party operator:

```python
from pytest_gremlins import OperatorRegistry

@OperatorRegistry.register("django-queryset")
class DjangoQuerySetOperator:
    """Mutate Django QuerySet methods."""

    @property
    def name(self) -> str:
        return "django-queryset"

    def can_mutate(self, node) -> bool:
        # Check for .filter(), .exclude(), etc.
        ...

    def mutate(self, node) -> list:
        # Generate mutations
        ...
```

## Summary

| Operator | Use When | Catches |
|----------|----------|---------|
| `comparison` | Always | Boundary bugs, off-by-one |
| `boundary` | Numeric thresholds | Fence post errors |
| `boolean` | Conditional logic | Logic errors |
| `arithmetic` | Calculations | Math errors |
| `return` | Functions with return values | Missing assertions |

For most projects, start with all operators enabled and use incremental caching (`--gremlin-cache`)
to manage performance.
