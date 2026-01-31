# pytest-gremlins

> Let the gremlins loose. See which ones survive.

**pytest-gremlins** is a fast-first mutation testing plugin for pytest. It helps you evaluate the
quality of your test suite by injecting small changes (gremlins) into your code and checking if
your tests catch them.

## Why Mutation Testing?

Code coverage tells you what code your tests *execute*, but not whether your tests would catch bugs.
Mutation testing answers a harder question: **if I introduce a bug, will my tests fail?**

pytest-gremlins creates "gremlins" (small code mutations like changing `>=` to `>`) and runs your
tests against each one. If your tests pass despite the gremlin, you've found a weakness in your
test suite.

## Quick Start

Install pytest-gremlins:

```bash
pip install pytest-gremlins
```

Run mutation testing:

```bash
pytest --gremlins
```

## Features

- **Fast** - Mutation switching, coverage-guided selection, incremental analysis, parallel execution
- **Native pytest integration** - Works with your existing test suite
- **Configurable** - Enable/disable operators, set thresholds, exclude paths
- **Great reports** - Console, HTML, and JSON output formats

## The Gremlins Theme

We use Gremlins movie references as our domain language:

| Traditional Term       | Gremlin Term            | Meaning                              |
| ---------------------- | ----------------------- | ------------------------------------ |
| Original code          | **Mogwai**              | Your clean, untouched source code    |
| Start mutation testing | **Feed after midnight** | Begin the mutation process           |
| Mutant                 | **Gremlin**             | A mutation injected into your code   |
| Kill mutant            | **Zap**                 | Your test caught the mutation        |
| Surviving mutant       | **Survivor**            | Mutation your tests missed           |

## Next Steps

- [Getting Started](guide/getting-started.md) - Installation and first run
- [Configuration](guide/configuration.md) - Customize pytest-gremlins
- [Operators](guide/operators.md) - Available mutation operators
