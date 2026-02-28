# Epic F Capstone Narration Script

<!-- markdownlint-disable MD013 -->

<!-- SEGMENT: intro -->
Five epics, one report. Pie Test Gremlins now generates a full H T M L mutation report — location, theming, charts, code diffs, and run history. Here is what the finished thing looks like.

<!-- SEGMENT: run -->
One flag: double-dash gremlin-report equals H T M L. The plugin runs mutation analysis and prints the report path when it finishes. Eight zapped, four survived, in just over three seconds. Open that path in a browser and you are done.

<!-- SEGMENT: dark_mode -->
Dark mode by default. The score, the charts, the diff table — all rendered on first load. Chart dot J S draws the canvases asynchronously, so give it a few seconds before you start clicking around.

<!-- SEGMENT: light_toggle -->
One click on Toggle Theme. The whole report re-renders in light mode using C S S custom properties — no JavaScript redraws the charts, no round-trip to a server. Click again to go back.

<!-- SEGMENT: score_gauge -->
The score gauge shows fifty-one percent. Red means more than half your gremlins survived. The percentage and colour both come from the mutation data in this run.

<!-- SEGMENT: outcome_pie -->
Twenty zapped, nineteen survived, zero timeouts, zero errors. The pie gives you the overall split. If you see a large survived slice, that is where your tests are not catching mutations.

<!-- SEGMENT: file_bar -->
The per-file bar chart breaks the score down by source file. Calculator dot py sits at forty-seven percent, validator dot py at fifty-six. Calculator is the weaker one — that is where the surviving gremlins are concentrated.

<!-- SEGMENT: operator_chart -->
The operator chart shows which mutation types produced survivors. Comparison operators and boolean operators account for most of the surviving gremlins here. If one operator type keeps escaping, your test suite is probably missing boundary checks for it.

<!-- SEGMENT: diff_expand -->
Click a row to expand the diff. Left panel is the Mogwai — the original. Right panel is the Gremlin — the mutated version. The unified diff is underneath. This one flipped greater-than to greater-than-or-equal and the tests did not catch it.

<!-- SEGMENT: history -->
The history section plots mutation score across runs. Sixty-three, seventy-one, seventy-eight, then sixty-six. Run four dropped twelve points. The chart is right there in the same report, same file.

<!-- SEGMENT: outro -->
That is the full report. Single H T M L file, no server, no dependencies at runtime. Location, theming, charts, diffs, history — all five epics in one artifact. That is Pie Test Gremlins at version one point three.
