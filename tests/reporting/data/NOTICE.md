# Third-party notice

`mutation-testing-report-schema.json` is vendored from the Stryker project's
[mutation-testing-elements](https://github.com/stryker-mutator/mutation-testing-elements)
repository (`packages/report-schema`).

Copyright the Stryker contributors. Licensed under the
[Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0).

The file is used only by the test suite: `tests/reporting/test_stryker_schema.py` validates the
Stryker export against it, and `tests/reporting/test_stryker_docs_example.py` validates the example
in `docs/guide/reports.md`. It is not part of the installed wheel.
