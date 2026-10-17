"""Check the five project documents, requirement coverage, and their local links.

Scope includes the five documents and the root AGENTS/CLAUDE pointers when present.
External URLs are not fetched. Code examples are not interpreted as Markdown links.
This checks structure, not the truth of product claims or task completion.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

DOCUMENTS = ("PRD.md", "Architecture.md", "Design.md", "Rules.md", "tasks.md")
REQUIREMENT = re.compile(r"\b(?:FR|NFR)-\d{2,}\b")
INLINE_LINK = re.compile(
    r"!?\[[^\]\n]*\]\(\s*(?:<(?P<angle>[^>]+)>|(?P<plain>[^\s)]+))"
    r"(?:\s+[\"'][^\n]*?[\"'])?\s*\)"
)
REFERENCE = re.compile(r"^\s*\[([^\]]+)\]:\s*(?:<([^>]+)>|(\S+))", re.M)
REFERENCE_USE = re.compile(r"!?\[([^\]\n]+)\]\[([^\]\n]*)\]")


def prose(text: str) -> str:
    """Ignore fenced code while retaining line numbers for useful diagnostics."""
    lines = []
    fence_char, fence_size = "", 0
    for line in text.splitlines():
        fence = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            marker = fence[1]
            if not fence_char:
                fence_char, fence_size = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_size:
                fence_char, fence_size = "", 0
            lines.append("")
        else:
            lines.append("" if fence_char else line)
    return "\n".join(lines)


def heading_ids(text: str) -> set[str]:
    """Resolve GitHub-style anchors for the plain ATX headings in this doc set."""
    seen: dict[str, int] = {}
    anchors = set()
    for match in re.finditer(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", prose(text), re.M):
        label = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", match[1])
        label = re.sub(r"<[^>]+>", "", label).lower().strip()
        slug = re.sub(r"[^\w\- ]", "", label).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(f"{slug}-{count}" if count else slug)
    return anchors


def local_links(text: str) -> list[tuple[int, str]]:
    """Read inline links and explicit reference links with their source line."""
    source = prose(text)
    found = [
        (source.count("\n", 0, match.start()) + 1, match["angle"] or match["plain"])
        for match in INLINE_LINK.finditer(source)
    ]
    references = {m[1].strip().casefold(): m[2] or m[3] for m in REFERENCE.finditer(source)}
    for match in REFERENCE_USE.finditer(source):
        key = (match[2] or match[1]).strip().casefold()
        # Missing explicit references are errors, rather than silently omitted links.
        target = references.get(key, "missing-reference:" + key)
        found.append((source.count("\n", 0, match.start()) + 1, target))
    return found


def check_docs(root: Path) -> list[str]:
    """Return actionable failures without mutating files or making network requests."""
    root = root.resolve()
    paths = [root / "docs" / name for name in DOCUMENTS]
    errors = [f"Missing document: {path.relative_to(root)}" for path in paths if not path.is_file()]
    text_by_path: dict[Path, str] = {}
    for path in paths + [root / "AGENTS.md", root / "CLAUDE.md"]:
        if not path.is_file():
            continue
        try:
            text_by_path[path] = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            errors.append(f"Cannot read {path.relative_to(root)}: {type(exc).__name__}")
    prd = root / "docs" / "PRD.md"
    tasks = root / "docs" / "tasks.md"
    if prd in text_by_path and tasks in text_by_path:
        requirements = set(REQUIREMENT.findall(prose(text_by_path[prd])))
        referenced = set(REQUIREMENT.findall(prose(text_by_path[tasks])))
        if not requirements:
            errors.append("PRD.md defines no FR-/NFR- requirement IDs.")
        errors.extend(
            f"Requirement not referenced in tasks.md: {r}"
            for r in sorted(requirements - referenced)
        )
        errors.extend(
            f"Unknown requirement in tasks.md: {r}" for r in sorted(referenced - requirements)
        )
    for path, text in text_by_path.items():
        for line, link in local_links(text):
            location = f"{path.relative_to(root)}:{line}"
            if link.startswith("missing-reference:"):
                errors.append(f"{location}: undefined Markdown reference {link.split(':', 1)[1]}")
                continue
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            destination = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            if not destination.exists():
                errors.append(f"{location}: broken relative link {link}")
                continue
            if parsed.fragment and destination.suffix.lower() == ".md":
                try:
                    target_text = destination.read_text(encoding="utf-8-sig")
                except (OSError, UnicodeError) as exc:
                    errors.append(f"{location}: cannot read {link}: {type(exc).__name__}")
                    continue
                if unquote(parsed.fragment) not in heading_ids(target_text):
                    errors.append(f"{location}: missing heading anchor {link}")
    return errors


def main() -> int:
    """Run from any directory; --root supports isolated checker regression fixtures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if errors := check_docs(args.root):
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(
        "Documentation checks passed: 5 documents, requirement coverage, and local links/anchors."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
