# Instrumentation Module

The instrumentation module implements **mutation switching**, the key speed optimization in
pytest-gremlins. Instead of modifying source files for each mutation, code is instrumented once
with all mutations embedded, and toggled via an environment variable.

## Overview

Traditional mutation testing rewrites files for each mutant:

```text
For each mutation:
    1. Modify source file
    2. Run tests
    3. Restore original file

# With 100 mutations = 100 file rewrites
```

Mutation switching instruments once:

```text
1. Transform source with ALL mutations embedded
2. For each mutation:
    - Set ACTIVE_GREMLIN=gXXX
    - Run tests (mutation auto-activates)

# With 100 mutations = 1 transformation, 100 test runs
```

## Module Exports

```python
from pytest_gremlins.instrumentation import (
    Gremlin,                  # Mutation dataclass
    transform_source,        # Main transformation function
    ACTIVE_GREMLIN_ENV_VAR,  # Environment variable name
    get_active_gremlin,      # Get current active gremlin ID
)
```

---

## Gremlin

A `Gremlin` represents a single mutation injected into source code.

::: pytest_gremlins.instrumentation.gremlin.Gremlin
    options:
      show_root_heading: true
      show_source: true

### Gremlin Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `gremlin_id` | `str` | Unique identifier (e.g., 'g001', 'g002') |
| `file_path` | `str` | Path to source file containing the mutation |
| `line_number` | `int` | Line number where mutation occurs |
| `original_node` | `ast.AST` | Original AST node before mutation |
| `mutated_node` | `ast.AST` | Mutated AST node |
| `operator_name` | `str` | Name of operator that created this mutation |
| `description` | `str` | Human-readable description (e.g., '>= to >') |

### Example

```python
from pytest_gremlins.instrumentation import transform_source

source = '''
def is_adult(age):
    return age >= 18
'''

gremlins, tree = transform_source(source, 'example.py')

for g in gremlins:
    print(f'{g.gremlin_id}: {g.description} at line {g.line_number}')

# Output:
# g001: >= to > at line 3
# g002: >= to < at line 3
# g003: boundary shift +/-1 at line 3
# g004: boundary shift +/-1 at line 3
# g005: return value to None at line 3
```

---

## Transformer

### transform_source

The main entry point for instrumenting Python source code.

::: pytest_gremlins.instrumentation.transformer.transform_source
    options:
      show_root_heading: true
      show_source: true

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `str` | Required | Python source code to transform |
| `file_path` | `str` | Required | Path for gremlin metadata |
| `operators` | `list[GremlinOperator] \| None` | `None` | Operators to use (None = all 5) |

### Returns

| Element | Type | Description |
|---------|------|-------------|
| `[0]` | `list[Gremlin]` | List of generated gremlins |
| `[1]` | `ast.Module` | Transformed AST with embedded switches |

### Example

```python
from pytest_gremlins.instrumentation import transform_source
from pytest_gremlins.operators import ComparisonOperator

source = 'result = x > 0'

# Use all default operators
gremlins, tree = transform_source(source, 'test.py')

# Use specific operators only
gremlins, tree = transform_source(
    source,
    'test.py',
    operators=[ComparisonOperator()]
)
```

---

### MutationSwitchingTransformer

Internal AST transformer that replaces mutation points with switching expressions.

::: pytest_gremlins.instrumentation.transformer.MutationSwitchingTransformer
    options:
      show_root_heading: true
      show_source: true
      members:
        - "__init__"
        - visit_Compare
        - visit_BinOp
        - visit_BoolOp
        - visit_UnaryOp
        - visit_Constant
        - visit_Return

### How Switching Works

The transformer replaces mutation points with conditional expressions:

**Original code:**

```python
if age >= 18:
    return "adult"
```

**Transformed code (conceptual):**

```python
if (
    'g002' if __gremlin_active__ == 'g001' else
    'g003' if __gremlin_active__ == 'g002' else
    age >= 18
):
    return (
        None if __gremlin_active__ == 'g003' else
        "adult"
    )
```

When `__gremlin_active__` is:

- `None` - Original code executes
- `'g001'` - First mutation activates (>= to >)
- `'g002'` - Second mutation activates (>= to <)
- etc.

---

### build_switching_expression

Builds a nested ternary expression for mutation switching.

::: pytest_gremlins.instrumentation.transformer.build_switching_expression
    options:
      show_root_heading: true
      show_source: true

### build_switching_statement

Builds a nested if statement for statement-level mutations (like return).

::: pytest_gremlins.instrumentation.transformer.build_switching_statement
    options:
      show_root_heading: true
      show_source: true

---

### get_default_registry

Returns the default operator registry with all 5 built-in operators.

::: pytest_gremlins.instrumentation.transformer.get_default_registry
    options:
      show_root_heading: true
      show_source: true

### Registered Operators

| Name | Class | Description |
|------|-------|-------------|
| `comparison` | `ComparisonOperator` | <, <=, >, >=, ==, != |
| `arithmetic` | `ArithmeticOperator` | +, -, *, /, //, %, ** |
| `boolean` | `BooleanOperator` | and/or, True/False, not |
| `boundary` | `BoundaryOperator` | Integer constants +/- 1 |
| `return` | `ReturnOperator` | Return value mutations |

---

## Switcher

### ACTIVE_GREMLIN_ENV_VAR

The environment variable that controls which gremlin is active.

```python
from pytest_gremlins.instrumentation import ACTIVE_GREMLIN_ENV_VAR

print(ACTIVE_GREMLIN_ENV_VAR)  # 'ACTIVE_GREMLIN'
```

### get_active_gremlin

Returns the currently active gremlin ID from the environment.

::: pytest_gremlins.instrumentation.switcher.get_active_gremlin
    options:
      show_root_heading: true
      show_source: true

### Example

```python
import os
from pytest_gremlins.instrumentation import get_active_gremlin

# No gremlin active
print(get_active_gremlin())  # None

# Activate a gremlin
os.environ['ACTIVE_GREMLIN'] = 'g001'
print(get_active_gremlin())  # 'g001'
```

---

## Import Hooks

The import hooks module intercepts Python imports to inject instrumented code.

### GremlinFinder

MetaPathFinder that intercepts imports for instrumented modules.

::: pytest_gremlins.instrumentation.import_hooks.GremlinFinder
    options:
      show_root_heading: true
      show_source: true
      members:
        - "__init__"
        - find_spec

### GremlinLoader

Loader that executes instrumented AST code.

::: pytest_gremlins.instrumentation.import_hooks.GremlinLoader
    options:
      show_root_heading: true
      show_source: true
      members:
        - "__init__"
        - create_module
        - exec_module

### register_import_hooks

Registers import hooks for instrumented modules.

::: pytest_gremlins.instrumentation.import_hooks.register_import_hooks
    options:
      show_root_heading: true
      show_source: true

### unregister_import_hooks

Removes import hooks from sys.meta_path.

::: pytest_gremlins.instrumentation.import_hooks.unregister_import_hooks
    options:
      show_root_heading: true
      show_source: true

### Import Hook Flow

```text
1. register_import_hooks({'mymodule': instrumented_ast})
2. import mymodule  # Python calls GremlinFinder.find_spec()
3. GremlinFinder returns ModuleSpec with GremlinLoader
4. Python calls GremlinLoader.exec_module()
5. Loader injects __gremlin_active__ and executes instrumented AST
```

---

## Finder

### MutationPointVisitor

AST visitor that collects nodes that can be mutated.

::: pytest_gremlins.instrumentation.finder.MutationPointVisitor
    options:
      show_root_heading: true
      show_source: true

### find_mutation_points

Finds all mutation points in an AST.

::: pytest_gremlins.instrumentation.finder.find_mutation_points
    options:
      show_root_heading: true
      show_source: true

### Example

```python
import ast
from pytest_gremlins.instrumentation.finder import find_mutation_points

source = '''
def check(x, y):
    if x > y:
        return x - y
    return y - x
'''

tree = ast.parse(source)
points = find_mutation_points(tree)
print(f'Found {len(points)} mutation points')
```

---

## Helper Functions

### create_gremlins_for_node

Creates gremlins for any AST node using a specific operator.

::: pytest_gremlins.instrumentation.transformer.create_gremlins_for_node
    options:
      show_root_heading: true
      show_source: true

### create_gremlins_for_compare

Creates gremlins specifically for comparison nodes.

::: pytest_gremlins.instrumentation.transformer.create_gremlins_for_compare
    options:
      show_root_heading: true
      show_source: true

### collect_gremlins

Collects gremlins from source without instrumenting it.

::: pytest_gremlins.instrumentation.transformer.collect_gremlins
    options:
      show_root_heading: true
      show_source: true

---

## Performance Considerations

### Why Mutation Switching is Fast

| Approach | File I/O per Mutation | Module Reloads |
|----------|----------------------|----------------|
| Traditional | Read + Write + Restore | Yes |
| Switching | None (env var only) | No |

### Memory Trade-off

The transformed AST is larger because it contains all mutations embedded. For a file with N
mutation points generating M mutations total:

- Original AST: ~1x size
- Transformed AST: ~1x + (M * switch_overhead)

This trade-off is worthwhile because:

1. Transformation happens once per file
2. Test execution happens M times per file
3. Memory is cheap; I/O is expensive
