"""Fails (exit 1) when a NEW migration contains a destructive operation: drop column, drop table,
rename, or a column type change that narrows or cannot be proven safe. Meant for CI.

    python scripts/check_migration_safety.py --base origin/main      # migrations added since that ref
    python scripts/check_migration_safety.py path/to/migration.py    # specific files
    python scripts/check_migration_safety.py --all                   # every migration (old ones may fail)

A deliberate, reviewed exception: put the comment  # migration-safety: allow  on the line of the call.
Anything inside downgrade() is ignored (it is expected to undo the upgrade).
"""
import ast
import os
import re
import subprocess
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSIONS_DIR = os.path.join(BACKEND_DIR, "migrations", "versions")
ALLOW = "migration-safety: allow"

TEXT_TYPES = {"String", "VARCHAR", "Text", "TEXT", "Unicode", "UnicodeText", "CHAR"}
INT_RANK = {"SmallInteger": 1, "SMALLINT": 1, "Integer": 2, "INTEGER": 2, "BigInteger": 3, "BIGINT": 3}
DESTRUCTIVE_SQL = re.compile(r"\b(drop\s+(table|column)|rename\s+(to|column)|truncate|alter\s+column\s+\S+\s+type)\b", re.I)


def _type_info(node):
    """('String', 50) for sa.String(50) / sa.String(length=50); (name, None) otherwise; None if not a type call."""
    if isinstance(node, ast.Call):
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
    elif isinstance(node, (ast.Attribute, ast.Name)):
        name, node = (node.attr if isinstance(node, ast.Attribute) else node.id), None
    else:
        return None
    length = None
    if isinstance(node, ast.Call):
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, int):
            length = node.args[0].value
        for kw in node.keywords:
            if kw.arg == "length" and isinstance(kw.value, ast.Constant):
                length = kw.value.value
    return name, length


def _alter_problem(call):
    kw = {k.arg: k.value for k in call.keywords if k.arg}
    if "new_column_name" in kw:
        return "renames a column"
    if "type_" not in kw:
        return None
    new = _type_info(kw["type_"])
    old = _type_info(kw["existing_type"]) if "existing_type" in kw else None
    if new is None:
        return "changes a column type in a way that cannot be checked"
    if old is None:
        return "changes a column type without existing_type, so narrowing cannot be ruled out"
    (n_name, n_len), (o_name, o_len) = new, old
    if n_name in TEXT_TYPES and o_name in TEXT_TYPES:
        if n_name in ("Text", "TEXT", "UnicodeText"):
            return None  # anything -> text only widens
        if n_len is None or o_len is None:
            return None if (n_len is None) else "narrows an unbounded text column to a limited length"
        return "narrows a text column" if n_len < o_len else None
    if n_name in INT_RANK and o_name in INT_RANK:
        return "narrows an integer column" if INT_RANK[n_name] < INT_RANK[o_name] else None
    if n_name == o_name:
        return None
    return f"changes a column type from {o_name} to {n_name}"


def scan_source(source):
    """Returns [(line, message)] for destructive operations outside downgrade()."""
    tree = ast.parse(source)
    lines = source.splitlines()
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            skip |= {id(n) for n in ast.walk(node)}
    findings = []
    for node in ast.walk(tree):
        if id(node) in skip or not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        problem = None
        if attr == "drop_column":
            problem = "drops a column"
        elif attr == "drop_table":
            problem = "drops a table"
        elif attr == "rename_table":
            problem = "renames a table"
        elif attr == "alter_column":
            problem = _alter_problem(node)
        elif attr in ("execute", "exec_driver_sql") and node.args:
            arg = node.args[0]
            text = arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else ast.unparse(arg)
            if DESTRUCTIVE_SQL.search(text):
                problem = "runs raw SQL that drops, renames or truncates"
        if problem and ALLOW not in lines[node.lineno - 1]:
            findings.append((node.lineno, problem))
    return sorted(findings)


def _new_files(base):
    rel = os.path.relpath(VERSIONS_DIR, os.path.dirname(BACKEND_DIR)).replace(os.sep, "/")
    try:
        out = subprocess.run(["git", "diff", "--name-only", "--diff-filter=A", f"{base}...HEAD", "--", rel],
                             capture_output=True, text=True, check=True, cwd=os.path.dirname(BACKEND_DIR)).stdout
    except Exception as e:
        print(f"Could not ask git for new migrations ({type(e).__name__}). Pass file names or --all.")
        return None
    return [os.path.join(os.path.dirname(BACKEND_DIR), p) for p in out.split() if p.endswith(".py")]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    files = []
    if "--all" in argv:
        files = [os.path.join(VERSIONS_DIR, f) for f in sorted(os.listdir(VERSIONS_DIR)) if f.endswith(".py")]
    elif "--base" in argv:
        files = _new_files(argv[argv.index("--base") + 1])
        if files is None:
            return 2
    else:
        files = [a for a in argv if a.endswith(".py")]
        if not files:
            print(__doc__)
            return 2
    bad = 0
    for path in files:
        with open(path, encoding="utf-8") as fh:
            found = scan_source(fh.read())
        for line, message in found:
            bad += 1
            try:
                shown = os.path.relpath(path, BACKEND_DIR)
            except ValueError:  # on Windows, a file on another drive has no relative path
                shown = path
            print(f"{shown}:{line}: {message}")
    if bad:
        print(f"FAILED: {bad} destructive operation(s) in new migrations. Add '# {ALLOW}' only after review.")
        return 1
    print(f"OK: {len(files)} migration file(s) checked, nothing destructive.")
    return 0


if __name__ == "__main__":
    sys.exit(main())