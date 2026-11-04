#!/usr/bin/env python3
"""Checks that every Chinese UI text in the source is translatable and has an English translation.

The source texts are Chinese. A text is translatable when it is the literal argument of
tr(...) / N_(...) (Python), or tr(...) / QT_TR_NOOP(...) / translate("ctx", ...) /
QT_TRANSLATE_NOOP("ctx", ...) (C++), written on one line. Any other Chinese in code (comments are free) is
an error, unless the line carries one of these markers in a comment:

    i18n: value   a file-format value (for example a .uidp enum such as "主站"). It stays Chinese in
                  the file, but it is shown through tr(value) somewhere, so it needs a translation.
    i18n: ignore  not UI text at all (test data, a character table, a language's own name).

The English texts are in one table, the same file in PyQt UI Designer and FluentHMI Studio:
app/resource/i18n/en.json or resources/i18n/en.json, a JSON object {"中文": "English"}.

    python3 tools/check_i18n.py            check; exit status 1 on any problem
    python3 tools/check_i18n.py --keys     print every key with where it is used, as JSON
    python3 tools/check_i18n.py --missing  print the keys the table lacks, as a JSON object to fill in
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[㐀-鿿＀-￯　-〿]")
PLACEHOLDER = re.compile(r"%(\d)")
STR = r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
FIRST_ARG = re.compile(r"(?<![\w.])(?:tr|N_|QT_TR_NOOP)\(\s*(?:QStringLiteral\(\s*)?" + STR)
SECOND_ARG = re.compile(r"(?<![\w])(?:translate|QT_TRANSLATE_NOOP)\(\s*" + STR + r"\s*,\s*(?:QStringLiteral\(\s*)?" + STR)
ANY_STR = re.compile(STR)


def layout():
    if (ROOT / "app").is_dir():
        files = sorted((ROOT / "app").rglob("*.py")) + [ROOT / "main.py"]
        return files, ROOT / "app" / "resource" / "i18n" / "en.json"
    files = sorted(p for p in (ROOT / "src").rglob("*") if p.suffix in (".cpp", ".h"))
    return files, ROOT / "resources" / "i18n" / "en.json"


def unquote(literal):
    try:
        return ast.literal_eval(literal)
    except (ValueError, SyntaxError):
        return literal[1:-1]


def code_and_comment(line, python):
    """Splits a line into its code and its trailing comment, ignoring comment marks inside strings."""
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif python and c == "#":
            return line[:i], line[i:]
        elif not python and line.startswith("//", i):
            return line[:i], line[i:]
        i += 1
    return line, ""


def scan(files):
    keys = {}       # key -> ["file:line", ...]
    problems = []
    for path in files:
        python = path.suffix == ".py"
        text = path.read_text(encoding="utf-8")
        if not python:
            text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
        rel = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(text.splitlines(), 1):
            if not CJK.search(line):
                continue
            code, comment = code_and_comment(line, python)
            where = f"{rel}:{number}"
            if "i18n: ignore" in comment:
                continue
            found = [m.group(1) for m in FIRST_ARG.finditer(code)]
            found += [m.group(2) for m in SECOND_ARG.finditer(code)]
            rest = FIRST_ARG.sub("", SECOND_ARG.sub("", code))
            if "i18n: value" in comment:
                found += [s for s in ANY_STR.findall(rest) if CJK.search(s)]
                rest = ANY_STR.sub("", rest)
            for literal in found:
                key = unquote(literal)
                if CJK.search(key):
                    keys.setdefault(key, []).append(where)
            if CJK.search(rest):
                problems.append(f"{where}: Chinese outside tr(): {line.strip()}")
    return keys, problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys", action="store_true")
    parser.add_argument("--missing", action="store_true")
    args = parser.parse_args()
    files, table_path = layout()
    keys, problems = scan(files)
    if args.keys:
        json.dump(keys, sys.stdout, ensure_ascii=False, indent=1, sort_keys=True)
        return 0
    table = json.loads(table_path.read_text(encoding="utf-8")) if table_path.is_file() else {}
    missing = sorted(k for k in keys if k not in table)
    if args.missing:
        json.dump({k: "" for k in missing}, sys.stdout, ensure_ascii=False, indent=1)
        return 0
    for key in missing:
        problems.append(f"{keys[key][0]}: no English for {key!r}")
    for key, english in table.items():
        if not isinstance(english, str) or not english.strip():
            problems.append(f"{table_path.name}: empty English for {key!r}")
        elif CJK.search(english):
            problems.append(f"{table_path.name}: Chinese in the English for {key!r}")
        elif sorted(PLACEHOLDER.findall(key)) != sorted(PLACEHOLDER.findall(english)):
            problems.append(f"{table_path.name}: placeholders differ for {key!r}")
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
