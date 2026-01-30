# pytest Plugin Compatibility

Configure pytest-gremlins to work alongside other popular pytest plugins.

## Goal

Integrate pytest-gremlins with pytest-cov, pytest-xdist, and other plugins without conflicts.

## Prerequisites

- pytest-gremlins installed
- One or more additional pytest plugins
- Understanding of each plugin's purpose

## pytest-cov Integration

### Goal

Run coverage collection and mutation testing together, or separately, without conflicts.

### Configuration

Create `pyproject.toml`:

```toml
[project]
name = "myproject"
version = "1.0.0"

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.1.0",
    "pytest-gremlins>=1.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"

# Coverage configuration
[tool.coverage.run]
source = ["src"]
branch = true
parallel = true

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
fail_under = 80

# Gremlins configuration
[tool.pytest-gremlins]
paths = ["src"]
min_score = 80
incremental = true
```

### Running Both Tools

**Option 1: Run separately (recommended)**

```bash
# Run coverage first
pytest tests/ --cov=src --cov-report=html --cov-report=term

# Run mutation testing second
pytest --gremlins --gremlin-report=html
```

**Option 2: Run together**

```bash
# Gremlins uses coverage data for test selection
pytest --gremlins --cov=src --cov-report=term
```

### CI Workflow

Create `.github/workflows/quality.yml`:

```yaml
name: Code Quality

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  coverage:
    name: Coverage
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run tests with coverage
        run: pytest tests/ --cov=src --cov-report=xml --cov-report=term

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          files: coverage.xml

  mutation:
    name: Mutation Testing
    runs-on: ubuntu-latest
    needs: coverage  # Run after coverage passes
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run mutation testing
        run: pytest --gremlins --gremlin-report=html

      - name: Upload mutation report
        uses: actions/upload-artifact@v4
        with:
          name: mutation-report
          path: gremlin-report.html
```

### Verification

1. Run coverage and verify report:
   ```bash
   pytest tests/ --cov=src --cov-report=html
   open htmlcov/index.html
   ```

2. Run mutation testing:
   ```bash
   pytest --gremlins --gremlin-report=html
   open gremlin-report.html
   ```

3. Both should complete without errors

### Troubleshooting

**Issue: Coverage reports are empty when running with gremlins**

pytest-gremlins may interfere with coverage collection. Run separately:

```bash
# Coverage only
pytest tests/ --cov=src

# Gremlins only
pytest --gremlins
```

**Issue: "CoverageWarning: No data was collected"**

Ensure source paths match:

```toml
[tool.coverage.run]
source = ["src"]  # Must match your package location

[tool.pytest-gremlins]
paths = ["src"]   # Same path
```

---

## pytest-xdist Integration

### Goal

Use pytest-xdist for parallel test execution alongside pytest-gremlins.

### Important Note

pytest-gremlins has its own parallel execution via `--gremlin-workers`. You typically don't need pytest-xdist for mutation testing, but they can coexist for regular test runs.

### Configuration

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-xdist>=3.5.0",
    "pytest-gremlins>=1.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"

[tool.pytest-gremlins]
paths = ["src"]
# Use gremlins' built-in parallelism, not xdist
workers = 4
```

### Running Tests

**Regular tests with xdist:**

```bash
pytest tests/ -n auto  # Uses all CPU cores
```

**Mutation testing (don't use -n):**

```bash
pytest --gremlins --gremlin-workers=4
```

**Combined in CI:**

```yaml
jobs:
  test:
    steps:
      # Fast parallel tests
      - name: Run tests
        run: pytest tests/ -n auto

  mutation:
    needs: test
    steps:
      # Mutation testing with its own parallelism
      - name: Run mutation testing
        run: pytest --gremlins --gremlin-workers=4
```

### Verification

1. Regular tests run in parallel:
   ```bash
   pytest tests/ -n 4 -v
   ```

2. Mutation testing uses its own workers:
   ```bash
   pytest --gremlins --gremlin-workers=4
   ```

### Troubleshooting

**Issue: Tests hang when using -n with --gremlins**

Don't combine them. pytest-gremlins manages its own parallelism:

```bash
# Wrong
pytest --gremlins -n 4

# Correct
pytest --gremlins --gremlin-workers=4
```

**Issue: Worker processes crash**

Reduce worker count or check for resource conflicts:

```bash
pytest --gremlins --gremlin-workers=2
```

---

## pytest-bdd Integration

### Goal

Run mutation testing alongside BDD-style tests written with pytest-bdd.

### Configuration

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-bdd>=7.0.0",
    "pytest-gremlins>=1.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
bdd_features_base_dir = "tests/features"

[tool.pytest-gremlins]
paths = ["src"]
min_score = 80

# Exclude step definitions from mutation (they're test code)
exclude = [
    "**/steps/*",
    "**/conftest.py",
]
```

### Project Structure

```
myproject/
├── src/
│   └── myapp/
│       └── calculator.py
├── tests/
│   ├── features/
│   │   └── calculator.feature
│   ├── steps/
│   │   └── test_calculator_steps.py
│   └── conftest.py
└── pyproject.toml
```

### Example Feature

Create `tests/features/calculator.feature`:

```gherkin
Feature: Calculator
    As a user
    I want to perform calculations
    So that I get accurate results

    Scenario: Add two numbers
        Given I have a calculator
        When I add 2 and 3
        Then the result is 5

    Scenario: Subtract two numbers
        Given I have a calculator
        When I subtract 3 from 10
        Then the result is 7

    Scenario: Divide by zero
        Given I have a calculator
        When I divide 10 by 0
        Then I get a division error
```

### Example Steps

Create `tests/steps/test_calculator_steps.py`:

```python
"""Step definitions for calculator feature."""

import pytest
from pytest_bdd import scenarios, given, when, then, parsers

from myapp.calculator import Calculator


scenarios('../features/calculator.feature')


@pytest.fixture
def calculator():
    """Create a calculator instance."""
    return Calculator()


@pytest.fixture
def result():
    """Container for calculation result."""
    return {'value': None, 'error': None}


@given('I have a calculator')
def have_calculator(calculator):
    """Calculator is available."""
    assert calculator is not None


@when(parsers.parse('I add {a:d} and {b:d}'))
def add_numbers(calculator, result, a, b):
    """Add two numbers."""
    result['value'] = calculator.add(a, b)


@when(parsers.parse('I subtract {b:d} from {a:d}'))
def subtract_numbers(calculator, result, a, b):
    """Subtract b from a."""
    result['value'] = calculator.subtract(a, b)


@when(parsers.parse('I divide {a:d} by {b:d}'))
def divide_numbers(calculator, result, a, b):
    """Divide a by b."""
    try:
        result['value'] = calculator.divide(a, b)
    except ZeroDivisionError as e:
        result['error'] = e


@then(parsers.parse('the result is {expected:d}'))
def check_result(result, expected):
    """Verify the calculation result."""
    assert result['value'] == expected


@then('I get a division error')
def check_division_error(result):
    """Verify division error occurred."""
    assert result['error'] is not None
    assert isinstance(result['error'], ZeroDivisionError)
```

### Verification

1. Run BDD tests:
   ```bash
   pytest tests/ -v
   ```

2. Run mutation testing:
   ```bash
   pytest --gremlins
   ```

### Troubleshooting

**Issue: Step definitions are being mutated**

Exclude the steps directory:

```toml
[tool.pytest-gremlins]
exclude = [
    "**/steps/*",
    "**/step_defs/*",
]
```

**Issue: Feature file changes not detected**

Feature files are not Python code, so they don't trigger mutation testing. Only the source code (`src/`) is mutated.

---

## pytest-mock Integration

### Goal

Use pytest-mock alongside pytest-gremlins for mocking external dependencies.

### Configuration

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-mock>=3.12.0",
    "pytest-gremlins>=1.0.0",
]

[tool.pytest-gremlins]
paths = ["src"]
min_score = 80
```

### Example Tests with Mocking

```python
"""Tests using pytest-mock alongside mutation testing."""

import pytest


class TestEmailService:
    """Tests for email service with mocked SMTP."""

    def test_send_email_calls_smtp(self, mocker):
        """Email service calls SMTP client."""
        mock_smtp = mocker.patch('myapp.email.SMTPClient')

        from myapp.email import EmailService
        service = EmailService()

        service.send('test@example.com', 'Subject', 'Body')

        mock_smtp.return_value.send.assert_called_once()

    def test_send_email_includes_recipient(self, mocker):
        """SMTP receives correct recipient."""
        mock_smtp = mocker.patch('myapp.email.SMTPClient')

        from myapp.email import EmailService
        service = EmailService()

        service.send('user@example.com', 'Hello', 'World')

        call_args = mock_smtp.return_value.send.call_args
        assert 'user@example.com' in str(call_args)

    def test_send_email_handles_smtp_error(self, mocker):
        """SMTP errors are handled gracefully."""
        mock_smtp = mocker.patch('myapp.email.SMTPClient')
        mock_smtp.return_value.send.side_effect = ConnectionError('SMTP down')

        from myapp.email import EmailService
        service = EmailService()

        result = service.send('test@example.com', 'Subject', 'Body')

        assert result is False
```

### Verification

1. Tests with mocks pass:
   ```bash
   pytest tests/ -v
   ```

2. Mutation testing runs correctly:
   ```bash
   pytest --gremlins
   ```

### Troubleshooting

**Issue: Mocked code is being mutated**

Only source code is mutated. Mocked behavior in tests isn't affected.

**Issue: Mutations in mock setup code**

If you have mock factories in `src/`, exclude them:

```toml
[tool.pytest-gremlins]
exclude = [
    "**/testing/*",
    "**/mocks/*",
]
```

---

## pytest-asyncio Integration

### Goal

Run mutation testing on async code with pytest-asyncio.

### Configuration

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-gremlins>=1.0.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.pytest-gremlins]
paths = ["src"]
min_score = 80
```

### Example Async Tests

```python
"""Tests for async code with mutation testing."""

import pytest


class TestAsyncService:
    """Tests for async service."""

    async def test_fetch_data_returns_result(self):
        """Async fetch returns data."""
        from myapp.async_service import fetch_data

        result = await fetch_data('resource-id')

        assert result is not None
        assert 'data' in result

    async def test_fetch_data_with_invalid_id_raises(self):
        """Invalid ID raises ValueError."""
        from myapp.async_service import fetch_data

        with pytest.raises(ValueError, match='Invalid resource ID'):
            await fetch_data('')

    async def test_batch_fetch_returns_all_results(self):
        """Batch fetch returns result for each ID."""
        from myapp.async_service import batch_fetch

        results = await batch_fetch(['a', 'b', 'c'])

        assert len(results) == 3
```

### Verification

1. Async tests pass:
   ```bash
   pytest tests/ -v
   ```

2. Mutation testing works with async code:
   ```bash
   pytest --gremlins
   ```

### Troubleshooting

**Issue: "RuntimeError: Event loop is closed"**

Use `asyncio_mode = "auto"` in pytest config:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

**Issue: Async fixtures not working**

Ensure fixtures are marked as async:

```python
@pytest.fixture
async def async_client():
    async with AsyncClient() as client:
        yield client
```

---

## Multiple Plugins Together

### Complete Configuration

```toml
[project]
name = "myproject"
version = "1.0.0"

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.1.0",
    "pytest-xdist>=3.5.0",
    "pytest-asyncio>=0.23.0",
    "pytest-mock>=3.12.0",
    "pytest-gremlins>=1.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-ra --strict-markers"

[tool.coverage.run]
source = ["src"]
branch = true

[tool.coverage.report]
fail_under = 80

[tool.pytest-gremlins]
paths = ["src"]
min_score = 80
incremental = true
workers = 4

exclude = [
    "**/test_*",
    "**/conftest.py",
    "**/__pycache__/*",
]
```

### CI Workflow with All Plugins

```yaml
name: Full Quality Pipeline

jobs:
  test:
    name: Tests with Coverage
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - run: pip install -e ".[dev]"

      # Parallel tests with coverage
      - run: pytest tests/ -n auto --cov=src --cov-report=xml

      - uses: codecov/codecov-action@v4
        with:
          files: coverage.xml

  mutation:
    name: Mutation Testing
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - run: pip install -e ".[dev]"

      # Mutation testing (no xdist, uses own parallelism)
      - run: pytest --gremlins --gremlin-workers=4 --gremlin-report=html

      - uses: actions/upload-artifact@v4
        with:
          name: mutation-report
          path: gremlin-report.html
```
