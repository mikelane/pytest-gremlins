"""Changing package source forces a decision about the cache markers (#867).

``RECORDED_DIGESTS`` holds one sha256 per ``*.py`` file under ``src/pytest_gremlins/``, except the paths named
in ``EXCLUDED_FROM_GUARD``, one entry per line so git merges edits to different files cleanly.
A new file is guarded the moment it exists; nothing has to be added to a list. When a
digest no longer matches, the author decides whether the change can alter a verdict, or which gremlins exist,
for the same source and tests:

- ``CACHE_VERSION`` owns what gets mutated: ``operators/``, ``instrumentation/`` and anything else that changes
  which gremlins exist.
- ``RUNNER_FIDELITY_VERSION`` owns test execution and the mapping from test outcome to verdict: ``parallel/``,
  ``control_run.py`` and the code that shapes the gremlin subprocess command line.
- A change that cannot alter any verdict leaves both markers alone; re-record the digest.
- A file that can never influence a verdict goes into ``EXCLUDED_FROM_GUARD`` with a one-line reason, which review
  checks. When unsure, leave the file guarded.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from pytest_gremlins.cache.incremental import RUNNER_FIDELITY_VERSION
from pytest_gremlins.cache.versions import CACHE_VERSION

ALLOWLIST_PRAGMA = '# pragma: allowlist secret'
NOQA_E501 = '# noqa: E501'
ENTRY_SEPARATOR = '    # --'
MAX_LINE_LENGTH = 120
GIT = shutil.which('git') or 'git'
PACKAGE_ROOT = Path(__file__).resolve().parents[2] / 'src' / 'pytest_gremlins'

# Keys are package-relative POSIX paths: a file, or a directory prefix ending in "/".
# Only renderers that run after every verdict is decided belong here. Nothing on the verdict path imports them:
# the parallel executors and plugin.py import only reporting/results.py (GremlinResultStatus), and
# reporting/score.py, reporting/types.py and reporting/__init__.py stay guarded.
EXCLUDED_FROM_GUARD: dict[str, str] = {
    '__init__.py': 'Holds only __version__, which cz bump rewrites each release; decides no verdict.',
    'reporting/console.py': 'Formats finished results for the terminal; decides no verdict.',
    'reporting/diff.py': 'Renders the original-versus-mutated diff shown in reports; decides no verdict.',
    'reporting/history.py': 'Persists per-run scores for trend charts after the run; decides no verdict.',
    'reporting/html.py': 'Renders finished results as an HTML report; decides no verdict.',
    'reporting/json_reporter.py': 'Serialises finished results as a JSON report; decides no verdict.',
    'reporting/sonarqube_export.py': 'Exports finished results in SonarQube format; decides no verdict.',
    'reporting/stryker_export.py': 'Exports finished results in Stryker format; decides no verdict.',
}

RECORDED_CACHE_VERSION = 1
RECORDED_RUNNER_FIDELITY_VERSION = 'rf21'
# One entry per guarded file, sorted, one per line, with a separator comment between entries: every entry sits
# between unchanged lines, so git merges re-records of different files, even neighbours, without a conflict.
RECORDED_DIGESTS: dict[str, str] = {
    'cache/__init__.py': '62df21d4f76d4423b6066843acd9402dc17a026cadba50937fa4efe3841ae428',  # pragma: allowlist secret
    # --
    'cache/hasher.py': 'c9dc2acff727bf1c552ddbecf312ea6b55091c1c442f8cdf0096a91e227ac2b7',  # pragma: allowlist secret
    # --
    'cache/incremental.py': '19a75ff2f148ede6e0eb9a75f2827473f0d6121ab3ea6197c82407c9e5afda4c',  # pragma: allowlist secret  # noqa: E501
    # --
    'cache/store.py': '967c632516b6ae126921f43f1c72b753de59c0cac9679557793c2082e0003cc1',  # pragma: allowlist secret
    # --
    'cache/types.py': 'e8f2a82731cb4bfaec2a4803fe312826f3a85511224868322aa7eb127339085a',  # pragma: allowlist secret
    # --
    'cache/versions.py': '6e728070b7df009e39337fee2ad65eac5d94d722ba865a0fdf7fd8ea7eebb0e7',  # pragma: allowlist secret
    # --
    'config.py': 'c505aee0edbe35832d21e600138b9ce95832d4c99094185f908f9ca9f534338a',  # pragma: allowlist secret
    # --
    'control_run.py': '95174e647a5cea01a3bfb54a0498df39c92f7c57168bf2dbaea3ddcbc0584270',  # pragma: allowlist secret
    # --
    'coverage/__init__.py': 'aafaa74217e1e3936ede3a3506ba602f27eb43416b0b4b2ebbcadd1817d35854',  # pragma: allowlist secret  # noqa: E501
    # --
    'coverage/collector.py': '75f0086e3b1721ccb25793192722a28c340eff07ccdbd0b3a1e10345edcdda8d',  # pragma: allowlist secret  # noqa: E501
    # --
    'coverage/context_plugin.py': 'c90a4a707246f294bf45b6c82ace9605d1db8daceef5b94999fbd3a5b3022905',  # pragma: allowlist secret  # noqa: E501
    # --
    'coverage/mapper.py': '57aa2eab82fe4b361033d9812754c0aa99f5214ceaba112810bc5f0ce0f63dc4',  # pragma: allowlist secret  # noqa: E501
    # --
    'coverage/nodeid_markers.py': '5e7ce08b10b29d8cf56667342381d30b113ddf76d316ea3c346f0141d0a7e78f',  # pragma: allowlist secret  # noqa: E501
    # --
    'coverage/prescan_main.py': '7ffea6a07f3b2216aa493ebc36b5bae3d5c90a52413a2c6be72dc7cf6161c28b',  # pragma: allowlist secret  # noqa: E501
    # --
    'coverage/prioritized_selector.py': '60c4b6fd3e094aa0627428c75fb5693a9d7de28f1f1943baf12abe7b4bc5cdc2',  # pragma: allowlist secret  # noqa: E501
    # --
    'coverage/selector.py': 'b35af2f065bb47abe40ba63c83d0dc95cacc12de744e261f65aba879f149707b',  # pragma: allowlist secret  # noqa: E501
    # --
    'coverage/subprocess_bootstrap.py': 'c0eeeb6ae0d1ee099c901d2a76432502d05309897111be48b9eb616ab37c1463',  # pragma: allowlist secret  # noqa: E501
    # --
    'coverage/types.py': '6300b3a3c2f3a3ccd433e43fb172f367243f4f3eb10cd588306790ae415453ae',  # pragma: allowlist secret
    # --
    'gremlins_options.py': 'a222a60f665711808dac20c94eb44b072fe4483cfd9de134a15bb3c8172075a0',  # pragma: allowlist secret  # noqa: E501
    # --
    'instrumentation/__init__.py': '22aab29f2f7b08257f748738722eff5fede51bc1c5d90010a588fc38c92d42aa',  # pragma: allowlist secret  # noqa: E501
    # --
    'instrumentation/finder.py': '66c4a9f9e100fbf0fed6bdbed6fbb38758c91c2b5d42bd0eb793ef2ced7ed2f8',  # pragma: allowlist secret  # noqa: E501
    # --
    'instrumentation/gremlin.py': 'e395cdccebf405d826b8e699db383c1b876ade684afcd03c86cf202ccd99ad89',  # pragma: allowlist secret  # noqa: E501
    # --
    'instrumentation/origin_finder.py': 'bf015833cefb378c87181a5c3e8da40fdbae176cc152beff3a48183bec2b5b00',  # pragma: allowlist secret  # noqa: E501
    # --
    'instrumentation/pragma.py': 'c62fc42dce8d590bd58fa84e35183957ac428019b1c7227ea15ef2c4fbcf5597',  # pragma: allowlist secret  # noqa: E501
    # --
    'instrumentation/spawn_hook.py': '160a3d6b0bd717a1739e2d7a300067a8a2aaba6f3dcbdd343bed67d65ce57922',  # pragma: allowlist secret  # noqa: E501
    # --
    'instrumentation/switcher.py': '602bef0ec33b9e4f0edbb24db1497f2d9fbf57952662a5f11ec51dee262cff0e',  # pragma: allowlist secret  # noqa: E501
    # --
    'instrumentation/transformer.py': '1fd0ecc046dbae7b2d2771beac1b170427d365508e1ee855f52355b79096a3f5',  # pragma: allowlist secret  # noqa: E501
    # --
    'node_id_args.py': 'd8a6f83045811ffe0c9513e74a15278966c62071db6f3722b1ebc5359c073bb9',  # pragma: allowlist secret
    # --
    'node_id_file.py': '0dc413771fb6c5cff0719deec2e44a7d61581867e567fa7a7dad1f8d6b8cafc6',  # pragma: allowlist secret
    # --
    'operators/__init__.py': '95127c7b9b0e9bf0a142c29b7715bce2ea44da38864a26961e6e37855b6f7598',  # pragma: allowlist secret  # noqa: E501
    # --
    'operators/arithmetic.py': '222d4c8b864303e7d883407e0996bac191d03054a197c046fb8ac1d80669cd5a',  # pragma: allowlist secret  # noqa: E501
    # --
    'operators/boolean.py': 'a7db9c8a221f21021450c126890125b384bba56b6351ddb26f419009fdcab7be',  # pragma: allowlist secret  # noqa: E501
    # --
    'operators/boundary.py': '15d660650c565532be8e39a1a4d09cc58cf50dc53a3890bad69656419d565c49',  # pragma: allowlist secret  # noqa: E501
    # --
    'operators/comparison.py': 'c17be7152001c60806e524c37cffd6f6994af35cd658e598a24cc77570805a73',  # pragma: allowlist secret  # noqa: E501
    # --
    'operators/entry_points.py': 'a573e99cb07764a845d95341d53b67748e5113d0679b26c86821943347e4c4ed',  # pragma: allowlist secret  # noqa: E501
    # --
    'operators/protocol.py': '999044b8fd477412888e1febfbc756cc8928e8f1afd0fc4ec11cca4c28437be2',  # pragma: allowlist secret  # noqa: E501
    # --
    'operators/registry.py': 'd080086690b1d631cbf8d7c8b0c3a98f0c9e48309778c98bf148df9d0b897625',  # pragma: allowlist secret  # noqa: E501
    # --
    'operators/return_value.py': 'c38d8601fa6a360995fa0fde826316f89084a518bd1829ab57c3e7f65bf97070',  # pragma: allowlist secret  # noqa: E501
    # --
    'parallel/__init__.py': 'e8924a340f82b43586372f919c082e74931c371cc38298db53113ae38093a69b',  # pragma: allowlist secret  # noqa: E501
    # --
    'parallel/aggregator.py': '1edf168a66e9a95fed83e875eeee1a5a04682312b53b17284311f4148f0796ed',  # pragma: allowlist secret  # noqa: E501
    # --
    'parallel/batch_executor.py': '1d9ddd85f39485f58f7b122daf67cb7d6bd3da0096e9ce6216cb614dbffdc5c1',  # pragma: allowlist secret  # noqa: E501
    # --
    'parallel/distribution.py': '547985ecbe111d9640a41ccbc477e1a275053b864ccf988a9402f47fc57498be',  # pragma: allowlist secret  # noqa: E501
    # --
    'parallel/exit_codes.py': '4b0c1b2aa2d80c2483e7b2294960f2dc59e13438a1837b48056888ad6527da14',  # pragma: allowlist secret  # noqa: E501
    # --
    'parallel/fork_executor.py': 'a8553843606b1f21c192849e79207d71a61e8f4fc089a0ef9891337eccd9dcc3',  # pragma: allowlist secret  # noqa: E501
    # --
    'parallel/inprocess_executor.py': '250373b1553a8d52b9e437f2d65eea6d5fc2e977440f3e82f94a77020090bc67',  # pragma: allowlist secret  # noqa: E501
    # --
    'parallel/lightweight.py': '72dd62804a24be6334d38305fdd058fe70c537e445a73329d1e11c81f22482db',  # pragma: allowlist secret  # noqa: E501
    # --
    'parallel/persistent_pool.py': 'ff1309b9440529053e646d0af40990a4cb7068cb6c66e637d3cafe1fa0be220b',  # pragma: allowlist secret  # noqa: E501
    # --
    'parallel/pool.py': 'dd1e32efef562fe73506be11431bcc516d87b064bbd0edc5f1ff73711989344a',  # pragma: allowlist secret
    # --
    'parallel/pool_config.py': '7af64e5f01674965d50a40aea73547967316c01c10258aa6e800f7eaa90cae20',  # pragma: allowlist secret  # noqa: E501
    # --
    'parallel/runner_eligibility.py': 'fc7e0151bb1be877e4234efcd32ec1e1a1322f2a3666f72f3d75caf4e1771423',  # pragma: allowlist secret  # noqa: E501
    # --
    'plugin.py': 'af401b7492c2137688f108fc489ca479f39626e577f82b38bb12bfa23cfac248',  # pragma: allowlist secret
    # --
    'reporting/__init__.py': '89554da09af979ba49dee1f14ae15bfc210a64f59b7de9f99e7fd1ab31480401',  # pragma: allowlist secret  # noqa: E501
    # --
    'reporting/results.py': '82505d9a8978c5193f13e2f53876a963d10ed1a314a22117dd8a286b21530fd6',  # pragma: allowlist secret  # noqa: E501
    # --
    'reporting/score.py': 'e13c00b47d0451a30d4354240d10b2d2224ffdcd3ca87b658f648a3e6cfc61d3',  # pragma: allowlist secret  # noqa: E501
    # --
    'reporting/types.py': 'f732c4d57c6173836ac0244f4176fded3e86da043c768d9b55386f42a57d0492',  # pragma: allowlist secret  # noqa: E501
    # --
    'rerun_options.py': '988743f054ce69cdeec2be71ffc4e906cb5b0fb9f362046fcbbfdb78513ec415',  # pragma: allowlist secret
    # --
    'xdist_options.py': 'cf57d1eb13c67982575c1b48f20cc462bc1dec5043f5c457f541067007101c41',  # pragma: allowlist secret
}


def _is_excluded(relative_path: str) -> bool:
    return any(
        relative_path == excluded or (excluded.endswith('/') and relative_path.startswith(excluded))
        for excluded in EXCLUDED_FROM_GUARD
    )


def guarded_sources() -> list[Path]:
    """Return the package sources whose content the cache-version guard hashes, in digest order.

    That is every ``*.py`` file under the package except the paths in ``EXCLUDED_FROM_GUARD``, sorted by
    package-relative POSIX path. The release-time check (#877) and the CI verdict-diff job (#876) must call
    this function rather than keep their own list, so a file can never be guarded in one place and missed in
    another.
    """
    candidates = (
        (source, source.relative_to(PACKAGE_ROOT).as_posix())
        for source in PACKAGE_ROOT.rglob('*.py')
        if '__pycache__' not in source.parts
    )
    return [source for source, relative in sorted(candidates, key=lambda pair: pair[1]) if not _is_excluded(relative)]


def _normalized_sha256(source: Path) -> str:
    return hashlib.sha256(source.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def _guarded_digests() -> dict[str, str]:
    return {source.relative_to(PACKAGE_ROOT).as_posix(): _normalized_sha256(source) for source in guarded_sources()}


@dataclass(frozen=True)
class DigestDiff:
    """Guarded paths that differ between the recorded and the current digests, each tuple sorted."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def _compare_digests(recorded: Mapping[str, str], current: Mapping[str, str]) -> DigestDiff:
    return DigestDiff(
        added=tuple(sorted(current.keys() - recorded.keys())),
        removed=tuple(sorted(recorded.keys() - current.keys())),
        changed=tuple(sorted(path for path in current.keys() & recorded.keys() if current[path] != recorded[path])),
    )


def _format_entry(path: str, digest: str) -> str:
    line = f"    '{path}': '{digest}',  {ALLOWLIST_PRAGMA}"
    return f'{line}  {NOQA_E501}' if len(line) > MAX_LINE_LENGTH else line


def _format_entries(digests: Mapping[str, str]) -> str:
    entries = [_format_entry(path, digest) for path, digest in sorted(digests.items())]
    return ''.join(f'{line}\n' for line in _join_with_separator(entries, ENTRY_SEPARATOR))


def _join_with_separator(lines: list[str], separator: str) -> list[str]:
    separated = [line for entry in lines for line in (separator, entry)]
    return separated[1:]


def _mismatch_message(diff: DigestDiff) -> str:
    return '\n'.join(
        f'{label}: {", ".join(paths)}'
        for label, paths in (('added', diff.added), ('removed', diff.removed), ('changed', diff.changed))
        if paths
    )


def _copy_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    package_copy = tmp_path / 'pytest_gremlins'
    shutil.copytree(PACKAGE_ROOT, package_copy, ignore=shutil.ignore_patterns('__pycache__'))
    monkeypatch.setitem(globals(), 'PACKAGE_ROOT', package_copy)
    return package_copy


@pytest.mark.small
class DescribeDigestComparison:
    """Per-file digests let independent edits to different files merge into a passing guard."""

    def it_reports_nothing_when_recorded_and_current_match(self) -> None:
        assert _compare_digests({'a.py': 'h1'}, {'a.py': 'h1'}).is_empty is True

    @pytest.mark.parametrize(
        'diff',
        [
            DigestDiff(added=('a.py',), removed=(), changed=()),
            DigestDiff(added=(), removed=('a.py',), changed=()),
            DigestDiff(added=(), removed=(), changed=('a.py',)),
        ],
        ids=['added', 'removed', 'changed'],
    )
    def it_reports_a_difference_when_any_category_names_a_path(self, diff: DigestDiff) -> None:
        assert diff.is_empty is False

    def it_names_an_added_file(self) -> None:
        diff = _compare_digests({'a.py': 'h1'}, {'a.py': 'h1', 'b.py': 'h2'})

        assert (diff.added, diff.removed, diff.changed) == (('b.py',), (), ())

    def it_names_a_removed_file(self) -> None:
        diff = _compare_digests({'a.py': 'h1', 'b.py': 'h2'}, {'a.py': 'h1'})

        assert (diff.added, diff.removed, diff.changed) == ((), ('b.py',), ())

    def it_names_a_changed_file(self) -> None:
        diff = _compare_digests({'a.py': 'h1', 'b.py': 'h2'}, {'a.py': 'h1', 'b.py': 'h3'})

        assert (diff.added, diff.removed, diff.changed) == ((), (), ('b.py',))

    def it_fails_a_stale_record_naming_every_differing_path_in_the_message(self) -> None:
        message = _mismatch_message(_compare_digests({'a.py': 'h1', 'b.py': 'h2'}, {'a.py': 'h9', 'c.py': 'h3'}))

        assert message == 'added: c.py\nremoved: b.py\nchanged: a.py'

    def it_prints_replacement_entries_sorted_with_a_separator_line_between_them(self) -> None:
        printed = _format_entries({'b.py': 'h2', 'a.py': 'h1'})

        assert printed == (
            f"    'a.py': 'h1',  {ALLOWLIST_PRAGMA}\n{ENTRY_SEPARATOR}\n    'b.py': 'h2',  {ALLOWLIST_PRAGMA}\n"
        )

    def it_marks_every_printed_digest_line_with_the_allowlist_pragma(self) -> None:
        printed = _format_entries({'a.py': 'h1', 'b.py': 'h2', 'c.py': 'h3'})

        assert printed.count(ALLOWLIST_PRAGMA) == 3

    @pytest.mark.parametrize(
        ('line_length', 'expected'),
        [(MAX_LINE_LENGTH, False), (MAX_LINE_LENGTH + 1, True)],
        ids=['at-limit', 'over-limit'],
    )
    def it_adds_noqa_e501_only_when_the_entry_passes_the_line_limit(self, line_length: int, expected: bool) -> None:
        digest = 'a' * 64
        overhead = len(f"    '': '{digest}',  {ALLOWLIST_PRAGMA}")
        printed = _format_entries({'p' * (line_length - overhead): digest})

        assert printed.rstrip('\n').endswith(NOQA_E501) == expected


@pytest.mark.medium
class DescribeRecordMerge:
    """Two branches that re-record neighbouring files merge without a git conflict."""

    def it_merges_re_records_of_adjacent_entries_without_a_conflict(self, tmp_path: Path) -> None:
        base = {'cache/hasher.py': 'a' * 64, 'cache/incremental.py': 'b' * 64, 'cache/store.py': 'c' * 64}
        (tmp_path / 'base.py').write_text(_format_entries(base))
        (tmp_path / 'ours.py').write_text(_format_entries({**base, 'cache/hasher.py': 'd' * 64}))
        (tmp_path / 'theirs.py').write_text(_format_entries({**base, 'cache/incremental.py': 'e' * 64}))

        result = subprocess.run(
            [GIT, 'merge-file', '-p', 'ours.py', 'base.py', 'theirs.py'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        merged = {**base, 'cache/hasher.py': 'd' * 64, 'cache/incremental.py': 'e' * 64}
        assert (result.returncode, result.stdout) == (0, _format_entries(merged))


@pytest.mark.medium
class DescribeCacheVersionGuard:
    """The recorded digests and the cache markers move together with the verdict-affecting source."""

    def it_matches_the_recorded_digests_of_guarded_source(self) -> None:
        current = _guarded_digests()
        diff = _compare_digests(RECORDED_DIGESTS, current)

        assert diff.is_empty, (
            'Guarded package source changed. Decide whether the change can alter a verdict, or which gremlins '
            'exist, for the same source and tests. If it changes what gets mutated, raise CACHE_VERSION in '
            'src/pytest_gremlins/cache/versions.py. If it changes test execution or the outcome-to-verdict '
            'mapping, raise RUNNER_FIDELITY_VERSION in src/pytest_gremlins/cache/incremental.py. If neither, '
            'only re-record. Then replace RECORDED_DIGESTS in this file with the entries below (and update '
            'RECORDED_CACHE_VERSION or RECORDED_RUNNER_FIDELITY_VERSION for the marker you raised). If the file '
            'can never influence a verdict, add it to EXCLUDED_FROM_GUARD with a reason instead.\n'
            f'{_mismatch_message(diff)}\n'
            f'RECORDED_DIGESTS: dict[str, str] = {{\n{_format_entries(current)}}}'
        )

    def it_records_the_block_in_exactly_the_layout_it_prints(self) -> None:
        source = Path(__file__).read_text(encoding='utf-8')

        assert f'RECORDED_DIGESTS: dict[str, str] = {{\n{_format_entries(RECORDED_DIGESTS)}}}\n' in source

    def it_records_the_current_cache_version(self) -> None:
        assert RECORDED_CACHE_VERSION == CACHE_VERSION, (
            f'CACHE_VERSION is {CACHE_VERSION} but the guard recorded {RECORDED_CACHE_VERSION}. '
            'Update RECORDED_CACHE_VERSION and RECORDED_DIGESTS together.'
        )

    def it_records_the_current_runner_fidelity_version(self) -> None:
        assert RECORDED_RUNNER_FIDELITY_VERSION == RUNNER_FIDELITY_VERSION, (
            f'RUNNER_FIDELITY_VERSION is {RUNNER_FIDELITY_VERSION!r} but the guard recorded '
            f'{RECORDED_RUNNER_FIDELITY_VERSION!r}. '
            'Update RECORDED_RUNNER_FIDELITY_VERSION and RECORDED_DIGESTS together.'
        )

    @pytest.mark.parametrize(
        'guarded_file', ['node_id_args.py', 'rerun_options.py', 'config.py', 'gremlins_options.py']
    )
    def it_changes_the_digest_when_a_guarded_file_changes(
        self, guarded_file: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_copy = _copy_package(tmp_path, monkeypatch)
        before = _guarded_digests()

        target = package_copy / guarded_file
        target.write_text(target.read_text() + '\n_CHANGED = True\n')

        assert _guarded_digests() != before

    @pytest.mark.parametrize('new_file', ['brand_new_module.py', 'newpackage/deep/module.py'])
    def it_guards_a_new_source_file_without_any_list_edit(
        self, new_file: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_copy = _copy_package(tmp_path, monkeypatch)
        before = _guarded_digests()

        (package_copy / new_file).parent.mkdir(parents=True, exist_ok=True)
        (package_copy / new_file).write_text('VALUE = 1\n')

        assert _guarded_digests() != before

    @pytest.mark.parametrize('excluded_file', sorted(EXCLUDED_FROM_GUARD))
    def it_ignores_edits_to_an_excluded_file(
        self, excluded_file: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_copy = _copy_package(tmp_path, monkeypatch)
        before = _guarded_digests()

        target = package_copy / excluded_file
        target.write_text(target.read_text() + '\n_CHANGED = True\n')

        assert _guarded_digests() == before

    def it_keeps_the_digest_when_a_release_bump_rewrites_only_the_package_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_copy = _copy_package(tmp_path, monkeypatch)
        before = _guarded_digests()

        init_file = package_copy / '__init__.py'
        init_file.write_text(re.sub(r"__version__ = '[^']*'", "__version__ = '999.0.0'", init_file.read_text()))

        assert _guarded_digests() == before

    @pytest.mark.parametrize('excluded_path', sorted(EXCLUDED_FROM_GUARD))
    def it_names_only_existing_paths_in_the_exclusion_list(self, excluded_path: str) -> None:
        assert (PACKAGE_ROOT / excluded_path).exists(), (
            f'EXCLUDED_FROM_GUARD names {excluded_path!r}, which does not exist. Remove the stale exclusion.'
        )

    @pytest.mark.parametrize('excluded_path', sorted(EXCLUDED_FROM_GUARD))
    def it_gives_every_exclusion_a_reason(self, excluded_path: str) -> None:
        assert EXCLUDED_FROM_GUARD[excluded_path].strip(), f'{excluded_path!r} is excluded without a reason.'

    def it_excludes_nothing_that_the_verdict_path_imports(self) -> None:
        guarded = {source.relative_to(PACKAGE_ROOT).as_posix() for source in guarded_sources()}

        assert {'config.py', 'gremlins_options.py', 'plugin.py', 'reporting/results.py'} <= guarded
