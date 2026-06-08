"""Small local docs search helper for Scout AI OS agents."""

from __future__ import annotations

from pathlib import Path


class DocsSearch:
    """Search local Markdown docs with simple keyword matching."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def search(self, query: str, limit: int = 5) -> list[str]:
        terms = [term.casefold() for term in query.split() if term.strip()]
        if not terms:
            return []
        matches: list[str] = []
        for path in sorted(self._root.rglob("*.md")):
            try:
                text = path.read_text(encoding="utf-8").casefold()
            except UnicodeDecodeError:
                continue
            if all(term in text for term in terms):
                matches.append(str(path.relative_to(self._root)))
            if len(matches) >= limit:
                break
        return matches


__all__ = ["DocsSearch"]
