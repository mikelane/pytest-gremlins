# Operators

Operators define what types of mutations pytest-gremlins can create. Each operator targets specific code patterns and generates gremlin variants.

## Built-in Operators

### comparison

Mutates comparison operators.

| Original | Mutations |
|----------|-----------|
| `<` | `<=`, `>` |
| `<=` | `<`, `>` |
| `>` | `>=`, `<` |
| `>=` | `>`, `<` |
| `==` | `!=` |
| `!=` | `==` |

**Example:**
```python
# Original
if age >= 18:

# Gremlins
if age > 18:   # gremlin_001
if age < 18:   # gremlin_002
```

### boundary

Shifts boundary values in comparisons.

| Original | Mutations |
|----------|-----------|
| `x >= 18` | `x >= 19`, `x >= 17` |
| `x > 0` | `x > 1`, `x > -1` |

**Example:**
```python
# Original
if score > 100:

# Gremlins
if score > 101:  # gremlin_003
if score > 99:   # gremlin_004
```

### boolean

Mutates boolean operators and values.

| Original | Mutations |
|----------|-----------|
| `and` | `or` |
| `or` | `and` |
| `not x` | `x` |
| `True` | `False` |
| `False` | `True` |

**Example:**
```python
# Original
if is_valid and is_active:

# Gremlins
if is_valid or is_active:  # gremlin_005
```

### arithmetic

Mutates arithmetic operators.

| Original | Mutations |
|----------|-----------|
| `+` | `-` |
| `-` | `+` |
| `*` | `/` |
| `/` | `*` |
| `//` | `/` |
| `%` | `//` |
| `**` | `*` |

**Example:**
```python
# Original
total = price * quantity

# Gremlins
total = price / quantity  # gremlin_006
```

### return

Mutates return statements.

| Original | Mutations |
|----------|-----------|
| `return x` | `return None` |
| `return True` | `return False` |
| `return False` | `return True` |
| `return []` | `return [None]` |
| `return x` | `return -x` (numbers) |

**Example:**
```python
# Original
def is_valid():
    return True

# Gremlins
def is_valid():
    return False  # gremlin_007
```

## Enabling/Disabling Operators

### Via Configuration

```toml
[tool.pytest-gremlins]
# Only use these operators
operators = ["comparison", "boolean"]

# Or exclude specific operators
exclude_operators = ["arithmetic"]
```

### Via Command Line

```bash
pytest --gremlins --gremlin-operators=comparison,boolean
```

## Custom Operators

You can create custom operators for domain-specific mutations. See the [API Reference](../api/index.md) for details.

## Operator Priority

Operators run in priority order (highest value first):

1. **comparison** - Most likely to catch real bugs
2. **boundary** - Boundary conditions are critical
3. **boolean** - Logic errors are common
4. **return** - Return values must be tested
5. **arithmetic** - Wrong math = wrong results

Higher-priority gremlins are tested first for faster feedback.
