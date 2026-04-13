"""Hallucination gate: verify every symbol Codex claims exists actually does.

A symbol is "known" if one of:
  - kind == "import": matches sys.stdlib_module_names, or is declared in
    pyproject.toml [project].dependencies / optional-dependencies, or its
    top-level name resolves under project src/ (importlib.util.find_spec)
  - kind == "call":  top-level name is known as above AND the attr exists
                     on the imported module (best-effort)
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import tomllib
from pathlib import Path

from omc.gates.path_whitelist import GateResult


def _declared_packages(root: Path) -> set[str]:
    """Extract top-level package names from pyproject.toml dependencies."""
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return set()
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return set()

    project = data.get("project", {})
    raw_deps: list[str] = list(project.get("dependencies", []))
    opt_deps = project.get("optional-dependencies", {})
    for extra_list in opt_deps.values():
        raw_deps.extend(extra_list)

    packages: set[str] = set()
    for dep in raw_deps:
        # Strip markers (";...") first
        dep = dep.split(";", 1)[0].strip()
        # Strip extras ("[extra]")
        dep = dep.split("[", 1)[0].strip()
        # Strip version specifiers (>=, <=, ==, ~=, !=, >, <)
        for op in ("~=", "!=", ">=", "<=", "==", ">", "<"):
            dep = dep.split(op, 1)[0].strip()
        # Normalize hyphens to underscores (PEP 503)
        name = dep.replace("-", "_").lower()
        if name:
            packages.add(name)
    return packages


def _top_level_resolves(top: str) -> bool:
    """Return True if importlib.util.find_spec can locate the top-level name."""
    try:
        return importlib.util.find_spec(top) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _attr_exists(dotted: str) -> bool:
    """Check that the dotted path resolves, even when intermediate segments
    are classes rather than submodules (e.g. ``pathlib.Path.is_dir``).

    Strategy: find the longest leftward prefix that imports as a module, then
    walk the remaining segments via ``getattr``.
    """
    if "." not in dotted:
        return True
    parts = dotted.split(".")
    mod_obj = None
    mod_len = 0
    for i in range(len(parts), 0, -1):
        prefix = ".".join(parts[:i])
        try:
            mod_obj = importlib.import_module(prefix)
            mod_len = i
            break
        except Exception:
            continue
    if mod_obj is None:
        return False
    obj = mod_obj
    for attr in parts[mod_len:]:
        if not hasattr(obj, attr):
            return False
        obj = getattr(obj, attr)
    return True


def check_symbols(symbols: list[dict], project_root: Path) -> GateResult:
    """Validate that every symbol in *symbols* actually exists.

    Parameters
    ----------
    symbols:
        List of dicts with keys ``name`` (dotted string), ``kind``
        (``"import"`` or ``"call"``), and ``file`` (source path, informational).
    project_root:
        Repository root that contains ``pyproject.toml``.

    Returns
    -------
    GateResult
        ``ok=True`` when no offenders are found.
    """
    declared = _declared_packages(project_root)
    stdlib = set(sys.stdlib_module_names)
    offenders: list[str] = []

    for s in symbols:
        kind = s.get("kind")
        name = s.get("name", "")
        file_ = s.get("file", "?")

        if not name:
            offenders.append(f"empty symbol: {s!r}")
            continue

        top = name.split(".", 1)[0].lower()

        # --- Determine whether the top-level name is known ---
        top_known = (
            top in stdlib
            or top in declared
            or _top_level_resolves(top)
            # Worker-produced modules live in the workspace source tree, not
            # in an installed package. Accept a symbol whose dotted path maps
            # to a real .py file the worker just wrote.
            or _symbol_in_source_tree(name, project_root)
        )

        if not top_known:
            offenders.append(f"{file_}: unknown top-level '{top}' in '{name}'")
            continue

        # --- For calls, additionally verify the attribute exists ---
        if kind == "call" and not _attr_exists(name):
            if _symbol_in_source_tree(name, project_root):
                continue
            offenders.append(
                f"{file_}: attribute not found for call '{name}'"
            )

    return GateResult(ok=not offenders, offenders=offenders)


def _symbol_in_source_tree(dotted: str, source_root: Path) -> bool:
    """Return True if any prefix of *dotted* maps to a real .py file under
    *source_root* (or a common ``src/`` / ``tests/`` subdir).

    Example: ``omc.projects_index.list_projects`` → matches
    ``<source_root>/src/omc/projects_index.py`` if the worker just wrote it.
    """
    parts = dotted.split(".")
    roots = [source_root, source_root / "src", source_root / "tests"]
    for i in range(len(parts), 0, -1):
        rel_parts = parts[:i]
        for root in roots:
            candidate_file = root.joinpath(*rel_parts).with_suffix(".py")
            candidate_pkg = root.joinpath(*rel_parts, "__init__.py")
            if candidate_file.exists() or candidate_pkg.exists():
                return True
    return False
