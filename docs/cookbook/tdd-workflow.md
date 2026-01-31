# TDD with Mutation Testing

Integrate mutation testing into your Test-Driven Development workflow for stronger tests.

## Goal

Extend the classic Red-Green-Refactor cycle with mutation testing to ensure tests are not just
passing, but actually catching bugs.

## Prerequisites

- Understanding of TDD fundamentals
- pytest-gremlins installed
- A project with tests

## The Extended TDD Cycle

Traditional TDD:

```text
RED → GREEN → REFACTOR
```

TDD with Mutation Testing:

```text
RED → GREEN → REFACTOR → MUTATE
```

The **MUTATE** phase uses pytest-gremlins to verify your tests would catch bugs in the code you just wrote.

## Steps

1. Understand the extended cycle
2. Configure for fast feedback
3. Practice the workflow
4. Integrate into your routine

## Configuration

### Fast Feedback Configuration

Create `pyproject.toml` optimized for TDD:

```toml
[project]
name = "myproject"
version = "1.0.0"

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-gremlins>=1.0.0",
    "pytest-watch>=4.2.0",  # For continuous testing
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers -x --tb=short"
# -x: stop on first failure (fast feedback)
# --tb=short: concise tracebacks

[tool.pytest-gremlins]
paths = ["src"]

# TDD-friendly operator selection
operators = [
    "comparison",    # Boundary conditions
    "arithmetic",    # Math operations
    "boolean",       # Logic conditions
    "return",        # Return values
]
```

### Shell Aliases

Add to your `.bashrc` or `.zshrc`:

```bash
# TDD workflow aliases
alias t='pytest -x --tb=short'                    # Quick test run
alias tw='pytest-watch -- -x --tb=short'          # Watch mode
alias tm='pytest --gremlins --gremlin-cache -x'   # Mutate
alias tdd='pytest -x && pytest --gremlins --gremlin-cache -x'  # Full cycle
```

## The Workflow

### Phase 1: RED - Write a Failing Test

Write a test for the behavior you want:

```python
# tests/test_calculator.py
"""Tests for calculator module."""


class TestCalculatorAdd:
    """Tests for add function."""

    def test_add_positive_numbers(self):
        """Adding positive numbers returns their sum."""
        from myproject.calculator import add

        result = add(2, 3)

        assert result == 5
```

Run the test - it should fail:

```bash
t  # or: pytest -x --tb=short
```

```text
FAILED tests/test_calculator.py::TestCalculatorAdd::test_add_positive_numbers
E   ModuleNotFoundError: No module named 'myproject.calculator'
```

### Phase 2: GREEN - Make It Pass

Write the minimum code to pass:

```python
# src/myproject/calculator.py
"""Calculator module."""


def add(a, b):
    """Add two numbers."""
    return a + b
```

Run the test - it should pass:

```bash
t  # or: pytest -x --tb=short
```

```text
PASSED tests/test_calculator.py::TestCalculatorAdd::test_add_positive_numbers
```

### Phase 3: REFACTOR - Improve the Code

If needed, refactor while keeping tests green:

```python
# src/myproject/calculator.py
"""Calculator module."""


def add(a: int | float, b: int | float) -> int | float:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        Sum of a and b.
    """
    return a + b
```

Verify tests still pass:

```bash
t
```

### Phase 4: MUTATE - Verify Test Strength

Now run mutation testing to see if your test would catch bugs:

```bash
tm  # or: pytest --gremlins --gremlin-cache -x
```

If gremlins survive, your test has gaps:

```text
================== pytest-gremlins mutation report ==================

Zapped: 0 gremlins (0%)
Survived: 2 gremlins (100%)

Surviving gremlins:
  src/myproject/calculator.py:12    + → -   (arithmetic not verified)
  src/myproject/calculator.py:12    + → *   (arithmetic not verified)
```

This tells us: if someone changed `+` to `-` or `*`, our test wouldn't catch it!

### Back to RED - Strengthen Tests

Add tests that would catch these mutations:

```python
# tests/test_calculator.py
"""Tests for calculator module."""


class TestCalculatorAdd:
    """Tests for add function."""

    def test_add_positive_numbers(self):
        """Adding positive numbers returns their sum."""
        from myproject.calculator import add

        result = add(2, 3)

        assert result == 5

    def test_add_is_not_subtraction(self):
        """Addition is different from subtraction."""
        from myproject.calculator import add

        # If add(5, 3) returned 2, we'd know it's subtracting
        result = add(5, 3)

        assert result == 8  # Not 2 (5-3) or 15 (5*3)

    def test_add_zero_returns_other(self):
        """Adding zero returns the other number."""
        from myproject.calculator import add

        assert add(5, 0) == 5
        assert add(0, 5) == 5
```

Run mutation testing again:

```bash
tm
```

```text
================== pytest-gremlins mutation report ==================

Zapped: 2 gremlins (100%)
Survived: 0 gremlins (0%)
```

All gremlins zapped. Your tests are strong.

## Complete Example: Boundary Conditions

Let's work through a more complex example with boundary conditions.

### RED - Write the Test

```python
# tests/test_validator.py
"""Tests for age validator."""


class TestIsAdult:
    """Tests for is_adult function."""

    def test_eighteen_is_adult(self):
        """Age 18 is considered adult."""
        from myproject.validator import is_adult

        assert is_adult(18) is True
```

### GREEN - Make It Pass

```python
# src/myproject/validator.py
"""Age validation module."""


def is_adult(age: int) -> bool:
    """Check if age qualifies as adult.

    Args:
        age: Age in years.

    Returns:
        True if 18 or older, False otherwise.
    """
    return age >= 18
```

### MUTATE - Find Gaps

```bash
tm
```

```text
Surviving gremlins:
  src/myproject/validator.py:14    >= → >   (boundary not tested)
```

The `>=` to `>` mutation survives. If someone changed `age >= 18` to `age > 18`, our test would
still pass because we only test with age 18.

### RED Again - Test the Boundary

```python
# tests/test_validator.py
"""Tests for age validator."""


class TestIsAdult:
    """Tests for is_adult function."""

    def test_eighteen_is_adult(self):
        """Age 18 is considered adult."""
        from myproject.validator import is_adult

        assert is_adult(18) is True

    def test_seventeen_is_not_adult(self):
        """Age 17 is not adult."""
        from myproject.validator import is_adult

        assert is_adult(17) is False

    def test_nineteen_is_adult(self):
        """Age 19 is adult."""
        from myproject.validator import is_adult

        assert is_adult(19) is True
```

### MUTATE - Verify

```bash
tm
```

```text
Zapped: 2 gremlins (100%)
```

The boundary is now properly tested.

## Quick Feedback Loop

### Using pytest-watch

Install pytest-watch for continuous testing:

```bash
pip install pytest-watch
```

Run in watch mode:

```bash
pytest-watch -- -x --tb=short
```

Now every time you save a file, tests run automatically.

### Periodic Mutation Checks

While pytest-watch handles the RED-GREEN-REFACTOR cycle, periodically run mutation testing:

```bash
# In another terminal, or after completing a feature
tm
```

Or use a keyboard shortcut in your IDE to run the full TDD cycle:

```bash
tdd  # alias for: pytest -x && pytest --gremlins --gremlin-cache -x
```

## IDE Integration

### VS Code

Create `.vscode/tasks.json`:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "TDD: Run Tests",
      "type": "shell",
      "command": "pytest -x --tb=short",
      "group": "test",
      "problemMatcher": []
    },
    {
      "label": "TDD: Mutate",
      "type": "shell",
      "command": "pytest --gremlins --gremlin-cache -x",
      "group": "test",
      "problemMatcher": []
    },
    {
      "label": "TDD: Full Cycle",
      "type": "shell",
      "command": "pytest -x && pytest --gremlins --gremlin-cache -x",
      "group": "test",
      "problemMatcher": []
    }
  ]
}
```

Use `Cmd+Shift+B` (Mac) or `Ctrl+Shift+B` (Windows/Linux) to run tasks.

### PyCharm

Create run configurations:

1. **TDD: Tests** - `pytest -x --tb=short`
2. **TDD: Mutate** - `pytest --gremlins --gremlin-cache -x`
3. **TDD: Full** - Compound configuration running both

## Verification

1. Practice the cycle on a new feature:
   - Write failing test
   - Make it pass
   - Refactor
   - Run mutation testing
   - Strengthen tests if needed

2. Check that mutation scores stay high:

   ```bash
   pytest --gremlins --gremlin-report=console
   ```

3. Over time, mutation scores should improve or stay stable

## Troubleshooting

### Mutation testing is too slow for TDD

Use caching and operator subsets:

```bash
# Fast check during development
pytest --gremlins --gremlin-cache --gremlin-operators=comparison -x

# Full check before committing
pytest --gremlins
```

### Too many surviving gremlins to address

Focus on one at a time:

```bash
# See detailed report
pytest --gremlins --gremlin-report=html

# Address the most critical (e.g., boundary conditions) first
```

Prioritize:

1. Boundary condition mutations (`>=` to `>`)
2. Return value mutations (returning wrong value)
3. Boolean mutations (logic errors)
4. Arithmetic mutations (calculation errors)

### Some gremlins are false positives

Not all surviving gremlins indicate test gaps. Some mutations are equivalent (produce the same
behavior). Use pragmatic judgment:

```python
# This gremlin might survive: x = x + 0  →  x = x - 0
# Both produce the same result - not a real test gap
```

Mark intentional exclusions:

```python
def calculate_discount(price):
    # pragma: no gremlin
    return price * 0  # Always free! (not a real example)
```

## Best Practices

1. **Run mutation testing after each feature, not each commit**
   - TDD cycle: seconds
   - Mutation check: tens of seconds to minutes

2. **Start with high-value mutations**
   - Comparison operators catch boundary bugs
   - Boolean operators catch logic errors

3. **Don't chase 100% mutation score**
   - 85-95% is excellent
   - Some equivalent mutations are unavoidable

4. **Use mutation testing to learn**
   - Surviving gremlins teach you about edge cases
   - Over time, you'll write stronger tests naturally

5. **Integrate with code review**
   - Share mutation reports in PRs
   - Discuss surviving gremlins with teammates
