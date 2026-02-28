# Epic A Narration Script — Report Location & Output Structure

Narration for the terminal demo at `docs/demo/epic-a-output-location.cast`.
Audio can be generated from these segments using `scripts/build-demo.py`.

---

<!-- SEGMENT: title -->
pytest-gremlins finds the mutants your tests miss — and now it tells you exactly where it wrote the report.

<!-- SEGMENT: first_run -->
Watch what happens when we run pytest-gremlins with no flags. It feeds after midnight, runs every mutation,
and writes an HTML report to the default location: coverage slash gremlins slash index dot html.

<!-- SEGMENT: show_default -->
There it is. The full report in the standard coverage directory, right where your CI system expects it.

<!-- SEGMENT: custom_run -->
Now let's use the gremlins html dir flag to send the report somewhere else — say, a reports slash mutations directory.

<!-- SEGMENT: show_custom -->
Same report, different path. One flag and the output goes exactly where you need it.

<!-- SEGMENT: closing -->
pytest-gremlins. Mutation testing fast enough to run on every commit.
