#!/usr/bin/env python3
"""
pdf_runner.py – Extract source code from a PDF and optionally execute it.

Usage:
    python pdf_runner.py <path-to-pdf> [--run] [--language LANG]

Options:
    --run           Execute the extracted code blocks (Python only by default).
    --language LANG Only extract blocks for this language (e.g. python, javascript).
    --block N       Only process block number N (1-based).
    --list          List discovered code blocks without running them.
"""

import argparse
import re
import subprocess
import sys
import tempfile
import os

try:
    from pypdf import PdfReader
except ImportError:
    print("Error: 'pypdf' is required. Install it with: pip install pypdf", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Code-block detection
# ---------------------------------------------------------------------------

# Fence markers commonly found in Markdown-style PDFs (e.g. textbooks, slides)
_FENCE_RE = re.compile(
    r"```(?P<lang>[a-zA-Z0-9_+-]*)[ \t]*\n(?P<code>.*?)```",
    re.DOTALL,
)

# Indented blocks that look like code (4-space or tab indented, ≥2 consecutive lines)
_INDENT_RE = re.compile(
    r"(?:(?:^    .+|^\t.+)\n){2,}",
    re.MULTILINE,
)

# Language keywords used to guess the language of an indented block
_LANG_HINTS = {
    "python": [
        r"\bdef\s+\w+\s*\(", r"\bimport\s+\w+", r"\bprint\s*\(",
        r"\bclass\s+\w+", r"if\s+__name__\s*==",
    ],
    "javascript": [
        r"\bfunction\s+\w+\s*\(", r"\bconst\s+\w+\s*=", r"\blet\s+\w+\s*=",
        r"\bconsole\.log\s*\(",
    ],
    "swift": [
        r"\bfunc\s+\w+\s*\(", r"\bvar\s+\w+\s*:", r"\blet\s+\w+\s*:",
        r"\bimport\s+Foundation",
    ],
    "java": [
        r"\bpublic\s+class\s+\w+", r"\bSystem\.out\.println\s*\(",
        r"\bvoid\s+main\s*\(", r"@Override",
    ],
    "c": [
        r"#include\s*<", r"\bint\s+main\s*\(", r"\bprintf\s*\(",
    ],
    "bash": [
        r"^#!\s*/bin/", r"\becho\s+", r"\bexport\s+\w+",
    ],
}


def _guess_language(code: str) -> str:
    """Return a best-guess language name for the given code snippet."""
    if not _LANG_HINTS:
        return "unknown"
    scores = {lang: 0 for lang in _LANG_HINTS}
    for lang, patterns in _LANG_HINTS.items():
        for pat in patterns:
            if re.search(pat, code, re.MULTILINE):
                scores[lang] += 1
    best_lang, best_score = max(scores.items(), key=lambda kv: kv[1])
    return best_lang if best_score > 0 else "unknown"


def extract_text(pdf_path: str) -> str:
    """Extract all text from the PDF at *pdf_path*."""
    reader = PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n".join(pages)


def find_code_blocks(text: str) -> list[dict]:
    """
    Return a list of code-block dicts, each with keys:
        'code'     – the extracted source code string
        'language' – detected or declared language (may be 'unknown')
        'source'   – 'fenced' or 'indented'
    """
    blocks = []

    # 1. Fenced blocks (``` … ```)
    for m in _FENCE_RE.finditer(text):
        lang = m.group("lang").strip().lower() or None
        code = m.group("code")
        blocks.append({
            "code": code,
            "language": lang or _guess_language(code),
            "source": "fenced",
        })

    # 2. Indented blocks (fallback when no fences are present)
    if not blocks:
        for m in _INDENT_RE.finditer(text):
            code = re.sub(r"^(?:    |\t)", "", m.group(0), flags=re.MULTILINE)
            blocks.append({
                "code": code,
                "language": _guess_language(code),
                "source": "indented",
            })

    return blocks


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _run_python(code: str) -> None:
    """Execute *code* as Python in a subprocess."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            print(f"\n[pdf_runner] Process exited with code {result.returncode}.")
            if result.stderr:
                print("[pdf_runner] Stderr:", result.stderr.decode(errors="replace"))
    finally:
        os.unlink(tmp_path)


_RUNNERS = {
    "python": _run_python,
}


def run_block(block: dict) -> None:
    """Execute *block* if a runner exists for its language."""
    lang = block["language"]
    runner = _RUNNERS.get(lang)
    if runner is None:
        print(
            f"[pdf_runner] No runner available for language '{lang}'. "
            "Cannot execute this block."
        )
        return
    print(f"[pdf_runner] Running {lang} block …")
    runner(block["code"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract and optionally run source code found inside a PDF.",
    )
    parser.add_argument("pdf", help="Path to the PDF file.")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Execute the extracted code blocks (Python only).",
    )
    parser.add_argument(
        "--language",
        metavar="LANG",
        help="Filter blocks by language (e.g. python, javascript).",
    )
    parser.add_argument(
        "--block",
        type=int,
        metavar="N",
        help="Only process block number N (1-based index).",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip the confirmation prompt before executing code.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_only",
        help="List discovered code blocks without running them.",
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.pdf):
        print(f"Error: '{args.pdf}' not found.", file=sys.stderr)
        return 1

    print(f"[pdf_runner] Reading '{args.pdf}' …")
    text = extract_text(args.pdf)
    blocks = find_code_blocks(text)

    if not blocks:
        print("[pdf_runner] No code blocks found in the PDF.")
        return 0

    # Apply language filter
    if args.language:
        lang_filter = args.language.lower()
        blocks = [b for b in blocks if b["language"] == lang_filter]
        if not blocks:
            print(f"[pdf_runner] No '{lang_filter}' code blocks found.")
            return 0

    # Apply block-number filter
    if args.block is not None:
        if args.block < 1 or args.block > len(blocks):
            print(
                f"Error: --block {args.block} is out of range "
                f"(found {len(blocks)} block(s)).",
                file=sys.stderr,
            )
            return 1
        blocks = [blocks[args.block - 1]]

    print(f"[pdf_runner] Found {len(blocks)} code block(s).\n")

    for i, block in enumerate(blocks, start=1):
        separator = "─" * 60
        print(f"{separator}")
        print(f"Block {i}  │  language: {block['language']}  │  source: {block['source']}")
        print(separator)
        print(block["code"])
        print()

        if not args.list_only and args.run:
            if not args.yes:
                answer = input(
                    f"[pdf_runner] Execute block {i} ({block['language']})? [y/N] "
                ).strip().lower()
                if answer not in ("y", "yes"):
                    print("[pdf_runner] Skipped.")
                    continue
            run_block(block)

    return 0


if __name__ == "__main__":
    sys.exit(main())
