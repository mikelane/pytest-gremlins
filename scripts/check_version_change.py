#!/usr/bin/env python3
"""Pull request guard on version changes: only a release pull request may change ``[project].version``.

It runs on every pull request. The version is compared with the one at the merge base of the base ref and ``HEAD``,
never with the base tip, so a branch cut before main released still reads as unchanged. When either
``[project].version`` or ``__version__`` differs, the pull request must do all four of these, and every broken
rule is reported:

* have ``__version__`` in ``src/pytest_gremlins/__init__.py`` equal to ``[project].version``;
* come from the branch ``release/v<version>``, with ``<version>`` the exact version string, prerelease included;
* change only ``pyproject.toml``, ``uv.lock``, ``src/pytest_gremlins/__init__.py`` and ``CHANGELOG.md``
  (the changed files are taken from the same merge base);
* have a topmost ``CHANGELOG.md`` entry for that version.

Nothing skips this check: it has no flag, environment variable or input that turns it off.

Usage: ``check_version_change.py --branch BRANCH [--base-ref REF] [--repo PATH] [--github-output FILE]``. The branch
defaults to the ``HEAD_REF`` environment variable. With ``--github-output`` the script appends
``version_changed=true|false`` and ``version=<head version>`` to that file, for later steps and jobs to read.

Every file the guard reads (``pyproject.toml``, ``__init__.py`` and ``CHANGELOG.md``) is read as a git blob, at
``HEAD`` and at the merge base alike, and must be a regular file there (git mode 100644 or 100755). A symlink or
submodule is refused with exit 2, so the two sides cannot disagree about what a path holds. The files at ``HEAD`` are
also compared with the checked-out files, which the build reads: a file that is not a regular file, one under a
symlinked directory, or one whose bytes differ from the blob (a ``.gitattributes`` ``ident``, ``filter``,
``working-tree-encoding`` or ``eol`` transform) is refused with exit 2.

Exit codes: 0 when the version is unchanged, or changed and all four rules hold; 1 when a rule is broken (each is
printed on stdout with a ``PROBLEM:`` prefix, naming the offending files); 2 when the check could not run (a git
failure, a version file that is not a regular file, a missing or unreadable ``pyproject.toml``, ``__init__.py`` or
changelog, a missing or non-literal ``__version__``, a star import or an import that names ``__version__`` (a
submodule or a name), a version that is not PEP 440 shaped, bad arguments; the reason is printed on stderr).
Exit 2 is never a pass.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import (
    Iterator,
    Sequence,
)
import io
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tokenize
import tomllib

from check_release_docs import (
    CannotCheckError,
    newest_version,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
INIT_PATH = 'src/pytest_gremlins/__init__.py'
REGULAR_FILE_MODES = frozenset({'100644', '100755'})
RELEASE_FILES = frozenset({'pyproject.toml', 'uv.lock', INIT_PATH, 'CHANGELOG.md'})
PROBLEM_PREFIX = 'PROBLEM: '
VERSION_NAME = '__version__'
VERSION_SHAPE = re.compile(r'[0-9A-Za-z.+!_-]+')


def release_branch(version: str) -> str:
    """Return the branch a release of ``version`` must come from.

    Examples:
        >>> release_branch('1.15.0b0')
        'release/v1.15.0b0'
    """
    return f'release/v{version}'


def _checked_shape(version: str, source: str) -> str:
    """Return ``version`` when it is PEP 440 shaped; raise ``CannotCheckError`` before it can reach any output."""
    if not VERSION_SHAPE.fullmatch(version):
        raise CannotCheckError(f'the version in {source} is not a PEP 440 shaped string: {version!r}')
    return version


def project_version(pyproject: str) -> str:
    r"""Return ``[project].version`` from the text of a ``pyproject.toml``.

    Args:
        pyproject: The text of the file.

    Returns:
        The version string.

    Raises:
        CannotCheckError: When the text is not valid TOML or has no string ``[project].version``.

    Examples:
        >>> project_version('[project]\\nversion = "1.2.3"\\n')
        '1.2.3'
    """
    try:
        version = tomllib.loads(pyproject).get('project', {}).get('version')
    except tomllib.TOMLDecodeError as error:
        raise CannotCheckError(f'pyproject.toml is not valid TOML: {error}') from error
    if not isinstance(version, str) or not version:
        raise CannotCheckError('pyproject.toml has no [project].version string')
    return _checked_shape(version, 'pyproject.toml')


def module_version(source: str | bytes) -> str:
    """Return the module-level ``__version__ = '<str>'`` from the text of a Python module.

    Every binding of ``__version__`` anywhere in the module is counted (assignments at any depth, unpacking, loop,
    ``with``, ``except`` and walrus targets, imports, ``def``, ``class``, ``global``, ``match`` captures), and there
    must be exactly one, a top-level ``__version__ = '<str>'`` or ``__version__: str = '<str>'``. Python keeps the last
    binding, so any other rebinding would hide the real value. A star import (``from x import *``) may bind
    ``__version__`` without naming it, so any star import is refused. So is any import with ``__version__`` as a
    dotted module component (``import pkg.__version__``, ``from .__version__ import x``) or as an imported name
    (``from . import __version__ as v``), because importing a submodule named ``__version__`` rebinds the attribute.

    Known gap: a runtime write such as ``globals()['__version__'] = ...`` is not visible to this static check.

    Args:
        source: The text of the module.

    Returns:
        The version string.

    Raises:
        CannotCheckError: When the module does not parse, has no ``__version__`` binding, has more than one, or its
            single binding is not a top-level assignment of a string literal.

    Examples:
        >>> module_version("__version__ = '1.2.3'")
        '1.2.3'
    """
    # Parse the bytes the way Python does, so a PEP 263 coding cookie decides what the statements are.
    module_bytes = source.encode('utf-8') if isinstance(source, str) else source
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(module_bytes).readline)
        module_bytes.decode(encoding)
        tree = ast.parse(module_bytes)
    except (SyntaxError, UnicodeDecodeError, LookupError, ValueError) as error:
        raise CannotCheckError(f'{INIT_PATH} does not parse: {error}') from error
    if _has_star_import(tree):
        raise CannotCheckError(
            f'{INIT_PATH} has a star import (from x import *), which may bind __version__ and cannot be checked'
            ' statically'
        )
    if _imports_version(tree):
        raise CannotCheckError(f'{INIT_PATH} imports a module or name called __version__, which rebinds it')
    bindings = list(_version_bindings(tree))
    if not bindings:
        raise CannotCheckError(f'{INIT_PATH} has no module-level __version__ assignment')
    if len(bindings) > 1:
        raise CannotCheckError(f'{INIT_PATH} has {len(bindings)} module-level __version__ bindings; there must be one')
    assigned_node = _top_level_value(tree, bindings[0])
    if assigned_node is None:
        raise CannotCheckError(f'__version__ in {INIT_PATH} must be a top-level assignment')
    if isinstance(assigned_node, ast.Constant) and isinstance(assigned_node.value, str):
        return _checked_shape(assigned_node.value, INIT_PATH)
    raise CannotCheckError(f'__version__ in {INIT_PATH} is not a string literal')


def _version_bindings(tree: ast.AST) -> Iterator[ast.AST]:
    """Yield every node anywhere in ``tree`` that binds or rebinds, or deletes, the name ``__version__``."""
    for node in ast.walk(tree):
        if _binds_version(node):
            yield node


def _has_star_import(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.ImportFrom) and any(alias.name == '*' for alias in node.names) for node in ast.walk(tree)
    )


def _imports_version(tree: ast.AST) -> bool:
    """Return True when an import has ``__version__`` as a module path component or as an imported name.

    Importing ``pytest_gremlins.__version__`` sets the package attribute ``__version__`` to the submodule.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            parts = [part for alias in node.names for part in alias.name.split('.')]
        elif isinstance(node, ast.ImportFrom):
            parts = (node.module or '').split('.') + [alias.name for alias in node.names]
        else:
            continue
        if VERSION_NAME in parts:
            return True
    return False


def _binds_version(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == VERSION_NAME and not isinstance(node.ctx, ast.Load)
    if isinstance(node, ast.Global):
        return VERSION_NAME in node.names
    return _bound_name(node) == VERSION_NAME


def _bound_name(node: ast.AST) -> str | None:
    """Return the name a non-Name node binds, or None when it binds none."""
    if isinstance(node, ast.alias):
        return node.asname or node.name.split('.')[0]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler)):
        return node.name
    if isinstance(node, (ast.MatchAs, ast.MatchStar)):
        return node.name
    if isinstance(node, ast.MatchMapping):
        return node.rest
    return None


def _top_level_value(tree: ast.Module, binding: ast.AST) -> ast.expr | None:
    """Return the value when ``binding`` is the target of a top-level assignment, or None otherwise."""
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and statement.targets[0] is binding:
            return statement.value
        if isinstance(statement, ast.AnnAssign) and statement.target is binding:
            return statement.value
    return None


def _changelog_problem(changelog: str, version: str) -> str | None:
    try:
        newest = newest_version(changelog)
    except CannotCheckError as error:
        return f'CHANGELOG.md has no topmost entry for {version}: {error}'
    if newest != version:
        return f'the topmost CHANGELOG.md entry is for {newest}, not {version}'
    return None


def check_version_change(
    *,
    branch: str,
    base_version: str,
    head_version: str,
    base_module_version: str,
    head_module_version: str,
    changed_files: Sequence[str],
    changelog: str,
) -> list[str]:
    """Return the broken rules for a pull request; empty when the version is unchanged or every rule holds.

    Args:
        branch: The pull request's head branch.
        base_version: ``[project].version`` at the merge base.
        head_version: ``[project].version`` at ``HEAD``.
        base_module_version: ``__version__`` at the merge base.
        head_module_version: ``__version__`` at ``HEAD``.
        changed_files: The paths changed since the merge base.
        changelog: The text of ``CHANGELOG.md`` at ``HEAD``.

    Returns:
        One message per broken rule.
    """
    if head_version == base_version and head_module_version == base_module_version:
        return []
    problems: list[str] = []
    if head_module_version != head_version:
        problems.append(
            f'__version__ in {INIT_PATH} is {head_module_version}, but [project].version in pyproject.toml is '
            f'{head_version}; they must be equal'
        )
    expected_branch = release_branch(head_version)
    if branch != expected_branch:
        problems.append(
            f'the version changed from {base_version} to {head_version}, '
            f'so the branch must be {expected_branch}, not {branch!r}'
        )
    files_outside_release = sorted(set(changed_files) - RELEASE_FILES)
    if files_outside_release:
        allowed_files = ', '.join(sorted(RELEASE_FILES))
        problems.append(
            f'a version change may touch only {allowed_files}, but it also changes: {", ".join(files_outside_release)}'
        )
    changelog_problem = _changelog_problem(changelog, head_version)
    if changelog_problem:
        problems.append(changelog_problem)
    return problems


def _git_bytes(repo: Path, *args: str) -> bytes:
    """Run git in ``repo`` and return its stdout bytes; raise ``CannotCheckError`` when it fails."""
    try:
        completed = subprocess.run(
            ['git', *args],  # noqa: S607
            cwd=repo,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise CannotCheckError(f'cannot run git {args[0]}: {error}') from error
    if completed.returncode != 0:
        # git merge-base exits 1 with no stderr when the refs share no ancestor (a shallow or unrelated history)
        detail = (
            completed.stderr.decode('utf-8', 'replace').strip()
            or 'no error output (for merge-base: no common ancestor; fetch full history)'
        )
        raise CannotCheckError(f'git {" ".join(args)} failed with exit {completed.returncode}: {detail}')
    return completed.stdout


def _git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` and return its stdout as text; raise ``CannotCheckError`` when it fails."""
    try:
        return _git_bytes(repo, *args).decode('utf-8')
    except UnicodeDecodeError as error:
        raise CannotCheckError(f'git {" ".join(args)} printed output that is not UTF-8: {error}') from error


def _read_blob(repo: Path, ref: str, path: str) -> bytes:
    """Return the bytes of the regular file ``path`` at ``ref``, read from git and never from the working tree.

    Both sides of the comparison are blobs from the commit graph, so a symlink swapped in at either side cannot make
    one side read a link's target and the other the link's text. A path that is not a regular file blob is refused.
    """
    listing = _git(repo, 'ls-tree', ref, '--', path).strip()
    if not listing:
        raise CannotCheckError(f'{path} does not exist at {ref}')
    mode = listing.split(maxsplit=1)[0]
    if mode not in REGULAR_FILE_MODES:
        raise CannotCheckError(
            f'{path} at {ref} is not a regular file (git mode {mode}); a symlink or submodule is refused'
        )
    return _git_bytes(repo, 'show', f'{ref}:{path}')


def _require_plain_checkout_path(repo: Path, path: str) -> Path:
    """Return the working-tree path of ``path``; refuse when it or a parent directory below ``repo`` is a link."""
    current = repo
    for part in Path(path).parts[:-1]:
        current = current / part
        if not stat.S_ISDIR(_lstat(current, path).st_mode):
            raise CannotCheckError(f'{path}: {current.relative_to(repo)} is not a real directory (a symlink?)')
    target = repo / path
    if not stat.S_ISREG(_lstat(target, path).st_mode):
        raise CannotCheckError(f'{path} in the working tree is not a regular file (a symlink?)')
    return target


def _lstat(location: Path, path: str) -> os.stat_result:
    try:
        return location.lstat()
    except OSError as error:
        raise CannotCheckError(f'cannot inspect {path} in the working tree: {error}') from error


def _read_head_blob(repo: Path, path: str) -> bytes:
    """Return the ``HEAD`` blob of ``path``; refuse when the checked-out file is not byte-identical to it.

    The build and the release workflows read the working tree, so a checkout transform (the ``ident`` attribute, a
    filter, ``working-tree-encoding``, ``eol``) could make the shipped file differ from the blob the guard reads.
    """
    blob = _read_blob(repo, 'HEAD', path)
    target = _require_plain_checkout_path(repo, path)
    try:
        checked_out = target.read_bytes()
    except OSError as error:
        raise CannotCheckError(f'cannot read {path} in the working tree: {error}') from error
    if checked_out != blob:
        raise CannotCheckError(
            f'{path}: the checked-out file differs from the committed blob; '
            'check .gitattributes (ident, filter, working-tree-encoding, eol)'
        )
    return blob


def _read_text_head_blob(repo: Path, path: str) -> str:
    blob = _read_head_blob(repo, path)
    try:
        return blob.decode('utf-8')
    except UnicodeDecodeError as error:
        raise CannotCheckError(f'cannot read {path} at HEAD: {error}') from error


def _read_text_blob(repo: Path, ref: str, path: str) -> str:
    blob = _read_blob(repo, ref, path)
    try:
        return blob.decode('utf-8')
    except UnicodeDecodeError as error:
        raise CannotCheckError(f'cannot read {path} at {ref}: {error}') from error


def _write_outputs(path: Path | None, *, changed: bool, version: str) -> None:
    if path is None:
        return
    with path.open('a', encoding='utf-8') as handle:
        handle.write(f'version_changed={str(changed).lower()}\nversion={version}\n')


def _run(args: argparse.Namespace) -> tuple[list[str], str]:
    """Run the guard; return the broken rules and the message to print on a pass."""
    repo: Path = args.repo
    head_version = project_version(_read_text_head_blob(repo, 'pyproject.toml'))
    head_module_version = module_version(_read_head_blob(repo, INIT_PATH))
    merge_base = _git(repo, 'merge-base', args.base_ref, 'HEAD').strip()
    base_version = project_version(_read_text_blob(repo, merge_base, 'pyproject.toml'))
    base_module_version = module_version(_read_blob(repo, merge_base, INIT_PATH))
    is_version_changed = head_version != base_version or head_module_version != base_module_version
    if not is_version_changed:
        _write_outputs(args.github_output, changed=False, version=head_version)
        return [], f'The version is {head_version}, unchanged since the merge base.'
    changed_files = _git(repo, 'diff', '--name-only', '--no-renames', f'{merge_base}...HEAD').splitlines()
    changelog = _read_text_head_blob(repo, 'CHANGELOG.md')
    _write_outputs(args.github_output, changed=True, version=head_version)
    problems = check_version_change(
        branch=args.branch,
        base_version=base_version,
        head_version=head_version,
        base_module_version=base_module_version,
        head_module_version=head_module_version,
        changed_files=changed_files,
        changelog=changelog,
    )
    return problems, f'The version changed from {base_version} to {head_version} on {args.branch}, as a release must.'


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--branch', default=os.environ.get('HEAD_REF', ''), help='head branch (default: $HEAD_REF)')
    parser.add_argument('--base-ref', default='origin/main', help='ref to take the merge base with HEAD from')
    parser.add_argument('--repo', type=Path, default=REPO_ROOT, help='repository root')
    parser.add_argument('--github-output', type=Path, default=None, help='file to append version_changed= and version=')
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns 0 on a pass, 1 when a rule is broken, 2 when the check could not run."""
    args = _parse_args(argv)
    try:
        problems, pass_message = _run(args)
    except CannotCheckError as error:
        print(f'could not check the version change: {error}', file=sys.stderr)
        return 2
    except Exception as error:  # exit 2 must never be confused with a failed check (exit 1) or a pass
        print(f'could not check the version change: unexpected {type(error).__name__}: {error}', file=sys.stderr)
        return 2
    if problems:
        print('This pull request changes the version but is not a valid release pull request:')
        for problem in problems:
            print(f'{PROBLEM_PREFIX}{problem}')
        return 1
    print(pass_message)
    return 0


if __name__ == '__main__':
    sys.exit(main())
