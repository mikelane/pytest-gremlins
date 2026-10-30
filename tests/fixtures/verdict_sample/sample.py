"""Code mutated by the CI verdict-diff job; each function drives one verdict path (#876).

Keep this file stable: a change here changes the verdicts the job compares.

- ``LEVELS`` feeds a parametrize id, so its gremlin stops the suite from collecting: a collection kill.
- ``count_down`` loops forever when its ``-`` becomes ``+``: a timeout.
- ``is_smaller`` is only run, not checked, by its test: survivors.
- ``is_retry_safe`` is covered only by a test that fails its first attempt, so its gremlins survive only when the
  gremlin runs honour ``--reruns``: the rerun path.
- The rest are zapped.
"""

LEVELS = (1 + 1,)


def is_adult(age):
    return age >= 18


def both(first, second):
    return first and second


def total(price, quantity):
    return price * quantity


def is_smaller(first, second):
    return first < second


def count_down(steps):
    while steps > 0:
        steps = steps - 1
    return steps


def double(level):
    return level * 2


def is_retry_safe(attempts):
    return attempts <= 3
