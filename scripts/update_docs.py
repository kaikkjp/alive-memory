#!/usr/bin/env python3
"""
Post-merge documentation updater.

Run after every task completion to keep ARCHITECTURE.md accurate.
Usage: python scripts/update_docs.py

What it does:
1. Scans the codebase for all .py and .ts/.tsx files
2. Counts lines per file and per area
3. Lists any files NOT mentioned in ARCHITECTURE.md (drift detection)
4. Updates the summary table in ARCHITECTURE.md
"""

import os
import re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
ARCH_FILE = ROOT / "ARCHITECTURE.md"

# Directories to skip
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.next', 'venv', '.venv', 'data'}

# Area classification
def classify_file(rel_path: str) -> str:
    if rel_path.startswith('pipeline/'):
        return 'Pipeline (pipeline/*.py)'
    if rel_path.startswith('config/'):
        return 'Config'
    if rel_path.startswith('models/'):
        return 'Models'
    if rel_path.startswith('tests/'):
        return 'Tests'
    if rel_path.startswith('window/src/'):
        return 'Frontend (window/src/)'
    if rel_path.startswith('deploy/') or rel_path.startswith('nginx/'):
        return 'Deploy'
    if rel_path.startswith('scripts/'):
        return 'Scripts'
    if rel_path.startswith('docs/'):
        return 'Docs (*.md)'
    if rel_path.startswith('api/'):
        return 'API'
    if rel_path.endswith('.md') and '/' not in rel_path:
        return 'Docs (*.md)'
    if rel_path.endswith('.py') and '/' not in rel_path:
        return 'Core engine (*.py root)'
    return 'Other'


def count_lines(filepath: Path) -> int:
    try:
        return sum(1 for _ in open(filepath, 'r', encoding='utf-8', errors='ignore'))
    except Exception:
        return 0


def scan_codebase():
    """Scan all source files and return structured data."""
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Prune skipped directories
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            full = Path(dirpath) / fname
            rel = str(full.relative_to(ROOT))

            # Only count source files and docs
            if fname.endswith(('.py', '.ts', '.tsx', '.md', '.yaml', '.yml',
                               '.sh', '.sql', '.css', '.json', '.conf')):
                lines = count_lines(full)
                area = classify_file(rel)
                files.append({
                    'path': rel,
                    'lines': lines,
                    'area': area,
                })

    return files


def check_architecture_coverage(files):
    """Find source files not mentioned in ARCHITECTURE.md."""
    if not ARCH_FILE.exists():
        print("⚠️  ARCHITECTURE.md not found!")
        return []

    arch_content = ARCH_FILE.read_text()
    unmentioned = []

    for f in files:
        # Only check source files, not configs/locks
        if not f['path'].endswith(('.py', '.ts', '.tsx')):
            continue
        if f['path'].startswith('tests/'):
            continue  # Tests are listed as a group, not individually checked
        if f['path'] in ('pytest.ini',):
            continue

        # Check if the filename (not full path) appears in ARCHITECTURE.md
        basename = os.path.basename(f['path'])
        if basename not in arch_content and f['path'] not in arch_content:
            # Check for wildcard patterns like "dashboard/*.tsx"
            parent_dir = os.path.basename(os.path.dirname(f['path']))
            wildcard = f"{parent_dir}/*.{basename.split('.')[-1]}"
            if wildcard not in arch_content:
                unmentioned.append(f)

    return unmentioned


def build_summary_table(files):
    """Build the area summary table."""
    areas = defaultdict(lambda: {'files': 0, 'lines': 0})

    for f in files:
        # Only count meaningful source files
        if f['path'].endswith(('.json', '.conf', '.css', '.ini')):
            continue
        if f['path'] in ('window/package-lock.json',):
            continue
        area = f['area']
        areas[area]['files'] += 1
        areas[area]['lines'] += f['lines']

    return dict(areas)


def update_architecture_md(summary):
    """Update the summary table in ARCHITECTURE.md."""
    if not ARCH_FILE.exists():
        print("⚠️  ARCHITECTURE.md not found — skipping update")
        return

    content = ARCH_FILE.read_text()

    # Build the new table
    rows = []
    total_files = 0
    total_lines = 0

    # Desired display order
    order = [
        'Core engine (*.py root)',
        'Pipeline (pipeline/*.py)',
        'API',
        'Config',
        'Models',
        'Scripts',
        'Tests',
        'Frontend (window/src/)',
        'Docs (*.md)',
        'Deploy',
    ]

    for area in order:
        if area in summary:
            s = summary[area]
            rows.append(f"| {area} | {s['files']} | ~{s['lines']:,} |")
            total_files += s['files']
            total_lines += s['lines']

    # Handle any areas not in our order
    for area, s in summary.items():
        if area not in order and area != 'Other':
            rows.append(f"| {area} | {s['files']} | ~{s['lines']:,} |")
            total_files += s['files']
            total_lines += s['lines']

    rows.append(f"| **Total** | **~{total_files}** | **~{total_lines:,}** |")

    new_table = "| Area | Files | Lines |\n|------|-------|-------|\n" + "\n".join(rows)

    # Replace the existing table using regex
    # Look for the table that starts with "| Area | Files | Lines |"
    pattern = r'\| Area \| Files \| Lines \|.*?\| \*\*Total\*\*.*?\|'
    match = re.search(pattern, content, re.DOTALL)

    if match:
        content = content[:match.start()] + new_table + content[match.end():]
        ARCH_FILE.write_text(content)
        print("✅ Updated summary table in ARCHITECTURE.md")
    else:
        print("⚠️  Could not find summary table in ARCHITECTURE.md — skipping update")


def main():
    print("📂 Scanning codebase...\n")
    files = scan_codebase()

    # Summary by area
    summary = build_summary_table(files)

    print("📊 Codebase Summary")
    print("=" * 50)
    total_files = 0
    total_lines = 0
    for area, s in sorted(summary.items()):
        print(f"  {area:35s}  {s['files']:3d} files  {s['lines']:6,} lines")
        total_files += s['files']
        total_lines += s['lines']
    print(f"  {'TOTAL':35s}  {total_files:3d} files  {total_lines:6,} lines")
    print()

    # Top 10 largest files
    source_files = [f for f in files if f['path'].endswith(('.py', '.ts', '.tsx'))]
    source_files.sort(key=lambda f: f['lines'], reverse=True)
    print("📏 Largest Source Files")
    print("=" * 50)
    for f in source_files[:10]:
        print(f"  {f['lines']:5d}  {f['path']}")
    print()

    # Coverage check
    unmentioned = check_architecture_coverage(files)
    if unmentioned:
        print("⚠️  Files NOT in ARCHITECTURE.md (add them!):")
        print("=" * 50)
        for f in unmentioned:
            print(f"  {f['path']:40s}  ({f['lines']} lines)")
        print()
    else:
        print("✅ All source files mentioned in ARCHITECTURE.md\n")

    # Update the summary table
    update_architecture_md(summary)

    print("Done. Review ARCHITECTURE.md and commit if changes look correct.")


if __name__ == '__main__':
    main()
