"""Coding agent — proposes source code modifications to improve memory algorithms."""

from __future__ import annotations

import ast
import importlib
import logging
import os
import re
import shutil
import sys

from alive_memory.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

# Default target files the agent can modify (relative to package root)
DEFAULT_TARGET_FILES: list[str] = [
    "alive_memory/recall/hippocampus.py",
    "alive_memory/intake/formation.py",
    "alive_memory/intake/thalamus.py",
    "alive_memory/consolidation/__init__.py",
    "alive_memory/consolidation/reflection.py",
    "alive_memory/hot/reader.py",
]

# Modules the agent must NOT import (prevent gaming the eval)
FORBIDDEN_IMPORTS: set[str] = {
    "tools.evolve.scorer",
    "tools.evolve.runner",
    "tools.evolve.analyzer",
    "tools.evolve.suite",
    "tools.evolve.types",
}

# ── Prompt fragments ─────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are modifying the source code of a cognitive memory library "
    "(alive-memory). Your goal is to improve recall quality — the ability "
    "of the memory system to return relevant, complete, and well-ranked "
    "results for user queries.\n\n"
    "You will see the current source code, a failure analysis report from "
    "evaluation, and a history of previous attempts. Make ONE focused, "
    "logical change that addresses the top failure cluster."
)

_OUTPUT_FORMAT_INSTRUCTIONS = (
    "## Output format\n\n"
    "For each file you modify, output a fenced code block tagged with the "
    "file path:\n\n"
    "```python:path/to/file.py\n"
    "# full file content here\n"
    "```\n\n"
    "Rules:\n"
    "- Output the FULL modified file content (not a diff)\n"
    "- Only include files you actually changed\n"
    "- Keep all existing function signatures unchanged\n"
    "- Do NOT import any modules from tools.evolve.*\n"
    "- Start your response with a one-sentence description of the change, "
    "then the code blocks\n"
)


class CodingAgent:
    """Wraps an LLM provider to generate source code modifications.

    The agent receives:
    - Current source code of target files
    - Failure analysis from the train split
    - History of previous iterations (what was tried, what worked/didn't)

    The agent does NOT receive:
    - Held-out or production eval cases
    - The scoring function source
    - The eval case definitions
    """

    def __init__(
        self,
        llm: LLMProvider,
        target_files: list[str] | None = None,
        repo_root: str = "",
    ):
        """Initialize the coding agent.

        Args:
            llm: An LLMProvider instance (Anthropic, OpenRouter, etc.).
            target_files: File paths (relative to *repo_root*) the agent
                          may modify.  Defaults to :data:`DEFAULT_TARGET_FILES`.
            repo_root: Root directory of the repository.  Auto-detected if
                       not provided.
        """
        self.llm = llm
        self.target_files = target_files or list(DEFAULT_TARGET_FILES)
        self.repo_root = repo_root or self._find_repo_root()

    # ── Public API ────────────────────────────────────────────────

    async def propose_change(
        self,
        failure_report: str,
        current_sources: dict[str, str],
        history: list[dict] | None = None,
    ) -> dict[str, str]:
        """Ask the LLM to propose source code modifications.

        Args:
            failure_report: Failure analysis from :func:`analyzer.generate_failure_report`
                            (train split only).
            current_sources: ``{relative_path: source_code}`` for every target file.
            history: Previous iteration summaries, each a dict with keys
                     *iteration*, *change_description*, *promoted*, *score_delta*.

        Returns:
            ``{relative_path: new_source_code}`` for files that changed.
        """
        prompt = self._build_prompt(failure_report, current_sources, history)
        response = await self.llm.complete(
            prompt,
            system=_SYSTEM_PROMPT,
            max_tokens=4000,
            temperature=0.4,
        )
        changes = self._parse_response(response.text, current_sources)
        return changes

    def read_target_sources(self) -> dict[str, str]:
        """Read current source code of all target files.

        Returns:
            ``{relative_path: source_code}`` for every target file that exists.
        """
        sources: dict[str, str] = {}
        for rel_path in self.target_files:
            full_path = os.path.join(self.repo_root, rel_path)
            if os.path.exists(full_path):
                with open(full_path) as f:
                    sources[rel_path] = f.read()
        return sources

    # ── Prompt construction ───────────────────────────────────────

    def _build_prompt(
        self,
        failure_report: str,
        current_sources: dict[str, str],
        history: list[dict] | None = None,
    ) -> str:
        """Build the full prompt for the coding agent."""
        sections: list[str] = []

        # 1. Current source code
        sections.append("## Current source code\n")
        for path, code in sorted(current_sources.items()):
            sections.append(f"### {path}\n```python\n{code}\n```\n")

        # 2. Failure report
        sections.append("## Failure analysis (train split)\n")
        sections.append(failure_report)
        sections.append("")

        # 3. History of previous iterations
        if history:
            sections.append("## Previous iteration history\n")
            for entry in history:
                status = "PROMOTED" if entry.get("promoted") else "reverted"
                delta = entry.get("score_delta", 0)
                delta_str = f"{delta:+.4f}" if isinstance(delta, (int, float)) else str(delta)
                desc = entry.get("change_description", "(no description)")
                sections.append(
                    f"- Iteration {entry.get('iteration', '?')}: "
                    f"{desc} → {status} (score delta {delta_str})"
                )
            sections.append("")

            # Highlight what to avoid
            reverted = [
                e.get("change_description", "")
                for e in history
                if not e.get("promoted")
            ]
            if reverted:
                sections.append(
                    "Avoid repeating these reverted approaches:\n"
                    + "\n".join(f"  - {d}" for d in reverted if d)
                )
                sections.append("")

        # 4. Instructions
        sections.append(_OUTPUT_FORMAT_INSTRUCTIONS)

        return "\n".join(sections)

    # ── Response parsing ──────────────────────────────────────────

    _CODE_BLOCK_RE = re.compile(
        r"```python:([^\n]+)\n(.*?)```",
        re.DOTALL,
    )

    def _parse_response(
        self,
        response: str,
        current_sources: dict[str, str],
    ) -> dict[str, str]:
        """Parse the LLM response to extract modified source code.

        Looks for `````python:filepath`` blocks.  Only returns files whose
        content actually differs from the current source.
        """
        changes: dict[str, str] = {}

        for match in self._CODE_BLOCK_RE.finditer(response):
            filepath = match.group(1).strip()
            code = match.group(2)

            # Normalize path — strip leading "./" or "/"
            filepath = filepath.lstrip("./")

            # Only accept files that are in the allowed target list
            if filepath not in current_sources:
                logger.warning("Agent proposed change to non-target file: %s", filepath)
                continue

            # Only include if actually changed
            if code.rstrip() != current_sources[filepath].rstrip():
                changes[filepath] = code

        return changes

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _find_repo_root() -> str:
        """Find the repo root by walking up from this file's location."""
        current = os.path.dirname(os.path.abspath(__file__))
        # Walk up until we find a directory that contains alive_memory/
        for _ in range(10):
            if os.path.isdir(os.path.join(current, "alive_memory")):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        # Fallback: two levels up from this file (evolve/ -> alive_memory/ -> repo root)
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Validation ────────────────────────────────────────────────────


def validate_changes(
    changes: dict[str, str],
    allowed_files: list[str],
) -> list[str]:
    """Validate proposed code changes.

    Returns a list of error strings (empty means valid).

    Checks:
    1. Only allowed files are modified.
    2. Each file passes :func:`ast.parse` (valid Python syntax).
    3. No imports of forbidden modules (eval/scorer/runner).
    4. File content is not empty.
    """
    errors: list[str] = []
    for filepath, code in changes.items():
        if filepath not in allowed_files:
            errors.append(f"unauthorized file: {filepath}")
            continue
        if not code.strip():
            errors.append(f"empty file: {filepath}")
            continue
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            errors.append(f"syntax error in {filepath}: {exc}")
            continue
        # Check for forbidden imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name.startswith(f) for f in FORBIDDEN_IMPORTS):
                        errors.append(f"forbidden import in {filepath}: {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if any(node.module.startswith(f) for f in FORBIDDEN_IMPORTS):
                    errors.append(f"forbidden import in {filepath}: {node.module}")
    return errors


# ── File operations ───────────────────────────────────────────────


def apply_changes(
    changes: dict[str, str],
    repo_root: str,
    backup_dir: str,
) -> dict[str, str]:
    """Write new source code to files, saving backups first.

    Args:
        changes: ``{relative_path: new_source_code}``.
        repo_root: Repository root directory.
        backup_dir: Directory to store backup copies.

    Returns:
        ``{relative_path: backup_path}`` for each file backed up.
    """
    backups: dict[str, str] = {}
    os.makedirs(backup_dir, exist_ok=True)
    for rel_path, new_code in changes.items():
        full_path = os.path.join(repo_root, rel_path)
        backup_path = os.path.join(backup_dir, rel_path.replace("/", "_"))
        if os.path.exists(full_path):
            shutil.copy2(full_path, backup_path)
        backups[rel_path] = backup_path
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(new_code)
    return backups


def revert_changes(backups: dict[str, str], repo_root: str) -> None:
    """Restore files from backups.

    Args:
        backups: ``{relative_path: backup_path}`` as returned by :func:`apply_changes`.
        repo_root: Repository root directory.
    """
    for rel_path, backup_path in backups.items():
        full_path = os.path.join(repo_root, rel_path)
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, full_path)


def reload_memory_modules(target_files: list[str]) -> None:
    """Reload modified modules **and their importers** so the next eval uses new code.

    Converts file paths to module names and calls :func:`importlib.reload`
    on modules already present in :data:`sys.modules`.  After reloading the
    changed modules, any ``alive_memory.*`` module that imports from them is
    also reloaded so that stale name bindings are refreshed.

    Args:
        target_files: Relative file paths that were modified.
    """
    reloaded: set[str] = set()

    # 1. Reload the directly modified modules
    for rel_path in target_files:
        if not rel_path.endswith(".py"):
            continue
        module_name = rel_path.replace("/", ".").removesuffix(".py")
        # Handle __init__.py → package module name
        if module_name.endswith(".__init__"):
            module_name = module_name.removesuffix(".__init__")
        if module_name in sys.modules:
            try:
                importlib.reload(sys.modules[module_name])
                reloaded.add(module_name)
                logger.debug("Reloaded module %s", module_name)
            except Exception:
                logger.warning("Failed to reload module %s", module_name, exc_info=True)

    if not reloaded:
        return

    # 2. Reload alive_memory.* modules that import from the changed modules.
    #    This ensures that parent packages and sibling importers pick up the
    #    new function objects instead of keeping stale references.
    for mod_name, mod in list(sys.modules.items()):
        if mod is None or not mod_name.startswith("alive_memory."):
            continue
        if mod_name in reloaded:
            continue
        # Check if this module directly references any reloaded module
        try:
            source = getattr(mod, "__file__", None)
            if source is None:
                continue
            # Quick heuristic: check if the module's dict holds objects from
            # any reloaded module by inspecting import relationships.
            for reloaded_name in reloaded:
                # A module that imported from the reloaded one will have the
                # reloaded module's name as a substring of its imports.
                parts = reloaded_name.rsplit(".", 1)
                short_name = parts[-1] if len(parts) > 1 else reloaded_name
                if short_name in dir(mod) or reloaded_name in str(
                    getattr(mod, "__spec__", "")
                ):
                    importlib.reload(mod)
                    logger.debug(
                        "Cascade-reloaded %s (imports from %s)", mod_name, reloaded_name
                    )
                    break
        except Exception:
            logger.debug("Skipped cascade reload for %s", mod_name, exc_info=True)
