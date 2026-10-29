"""The batch options' help text says batching groups gremlins into worker tasks and does not cut subprocesses (#733)."""

from __future__ import annotations

import pytest

from pytest_gremlins import plugin


class _RecordingGroup:
    def __init__(self) -> None:
        self.help_by_option: dict[str, str] = {}

    def addoption(self, *names: str, **kwargs: object) -> None:
        for name in names:
            self.help_by_option[name] = str(kwargs.get('help', ''))


class _RecordingParser:
    def __init__(self) -> None:
        self.group = _RecordingGroup()

    def getgroup(self, *_args: object, **_kwargs: object) -> _RecordingGroup:
        return self.group

    def addini(self, *_args: object, **_kwargs: object) -> None:
        pass


def _help_texts() -> dict[str, str]:
    parser = _RecordingParser()
    plugin.pytest_addoption(parser)  # type: ignore[arg-type]
    return parser.group.help_by_option


@pytest.mark.small
class DescribeBatchOptionHelpText:
    def it_does_not_claim_batching_reduces_subprocess_overhead(self) -> None:
        assert 'subprocess overhead' not in _help_texts()['--gremlin-batch']

    def it_says_batching_groups_gremlins_into_worker_tasks(self) -> None:
        assert 'worker tasks' in _help_texts()['--gremlin-batch']

    def it_says_batching_does_not_reduce_subprocesses(self) -> None:
        assert 'not reduce subprocesses' in _help_texts()['--gremlin-batch']

    def it_describes_batch_size_as_gremlins_per_worker_task(self) -> None:
        assert 'worker task' in _help_texts()['--gremlin-batch-size']

    def it_names_no_option_inside_the_help_text_where_argparse_could_wrap_it(self) -> None:
        assert '--gremlin' not in _help_texts()['--gremlin-batch']
