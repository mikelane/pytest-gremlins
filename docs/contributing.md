# Contributing

See the [CONTRIBUTING.md](https://github.com/mikelane/pytest-gremlins/blob/main/CONTRIBUTING.md) file in
the repository for detailed contribution guidelines.

## Quick Summary

1. Fork the repository
2. Create a feature branch in a git worktree
3. Follow TDD (write tests first!)
4. Use conventional commits
5. Submit a pull request

## Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/pytest-gremlins.git
cd pytest-gremlins
uv sync --dev
uv run pre-commit install
```

## Running Tests

```bash
uv run pytest tests/small  # Fast unit tests
uv run pytest              # All tests
```

## Code of Conduct

Please read and follow our [Code of Conduct](https://github.com/mikelane/pytest-gremlins/blob/main/CODE_OF_CONDUCT.md).
