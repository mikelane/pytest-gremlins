# Demo Narration: Epic C — Data Visualizations

<!-- markdownlint-disable MD013 -->

## Metadata

- Issue: 166
- Recording date: 2026-02-27

---

## Segments

<!-- SEGMENT: intro -->
pytest-gremlins renders four Chart dot j s visualizations directly in the HTML report. No external dependencies, no internet required — the charts are bundled right in.

<!-- SEGMENT: score_gauge -->
The score gauge is the first thing you see. It's a dial that fills from red on the left through yellow in the middle to green on the right. The percentage shown is your mutation score — how many gremlins your tests actually zapped. Below seventy percent is red. Seventy to ninety is yellow. Ninety and above turns green.

<!-- SEGMENT: outcome_pie -->
Below the gauge is the outcome pie chart. It breaks every gremlin into one of three buckets: zapped, survived, or not covered. Zapped is good — your tests caught the mutation. Survived means the mutation slipped through. Not covered means no test even ran against that code path.

<!-- SEGMENT: file_bar -->
The per-file bar chart ranks every file by its individual mutation score. Files with the most survivors show up short and red on the left. This tells you exactly where to write more tests — no guessing, no digging through logs.

<!-- SEGMENT: operator_chart -->
The operator chart shows which kinds of mutations caused the most trouble. Each bar represents a mutation operator — things like flipping comparisons or removing boolean logic. Tall bars on the right mean those operator types produced the most survivors. That tells you which coding patterns your tests are weakest against.

<!-- SEGMENT: perfect_score -->
Now let's look at the perfect-score report. The gauge swings all the way to the right and turns solid green. One hundred percent. Every single gremlin zapped. That's what a fully tested module looks like.

<!-- SEGMENT: outro -->
Four charts, one report, immediate actionable insight. You know your score, you know which files need work, and you know which mutation types are slipping through — all without leaving the browser.
