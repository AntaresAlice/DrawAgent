from __future__ import annotations

import re
from pathlib import Path


class MemoryStore:
    """Markdown-based memory file read/write with path safety.

    Reference: opencode's file-based persistence with security checks.
    Human-readable (markdown) + agent-readable (structured sections).
    """

    ALLOWED_CATEGORY_RE = re.compile(r"^[a-zA-Z0-9_/\-]+$")

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, category: str) -> Path:
        """Validate and resolve category to a safe path within base_dir."""
        if not self.ALLOWED_CATEGORY_RE.match(category):
            raise ValueError(f"Invalid category name: {category}")
        path = (self.base_dir / f"{category}.md").resolve()
        if not str(path).startswith(str(self.base_dir)):
            raise ValueError(f"Path traversal attempt: {category}")
        return path

    async def read(self, category: str) -> str | None:
        """Read entire memory file for a category."""
        path = self._safe_path(category)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    async def write(
        self,
        category: str,
        content: str,
        append: bool = True,
    ) -> None:
        """Write to a memory file."""
        path = self._safe_path(category)
        path.parent.mkdir(parents=True, exist_ok=True)

        if append and path.exists():
            existing = path.read_text(encoding="utf-8")
            if not existing.endswith("\n\n"):
                content = "\n\n" + content
            content = existing + content

        path.write_text(content, encoding="utf-8")

    async def delete(self, category: str) -> bool:
        """Delete a memory file."""
        path = self._safe_path(category)
        if path.exists():
            path.unlink()
            return True
        return False

    async def list_categories(self) -> list[str]:
        """List all memory categories (relative paths without .md extension)."""
        results = []
        for md_file in self.base_dir.rglob("*.md"):
            if md_file.name == "index.md":
                continue
            rel = md_file.relative_to(self.base_dir)
            # Strip .md suffix
            category = str(rel).rsplit(".md", 1)[0].replace("\\", "/")
            results.append(category)
        return sorted(results)

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        """Simple keyword search across all memory files.

        Phase 1: regex keyword matching.
        Future: SQLite full-text or vector search.
        """
        results: list[dict] = []
        keywords = query.lower().split()

        for md_file in self.base_dir.rglob("*.md"):
            if md_file.name == "index.md":
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            score = sum(1 for kw in keywords if kw in content.lower())
            if score <= 0:
                continue

            rel_path = str(md_file.relative_to(self.base_dir)).replace("\\", "/")

            # Extract sections that contain matches
            snippets = []
            for kw in keywords:
                idx = content.lower().find(kw)
                if idx >= 0:
                    start = max(0, idx - 50)
                    end = min(len(content), idx + 200)
                    snippet = content[start:end].replace("\n", " ").strip()
                    snippets.append(snippet)

            results.append({
                "file": rel_path,
                "category": rel_path.rsplit(".md", 1)[0],
                "score": score,
                "snippet": snippets[0][:300] if snippets else content[:300],
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:max_results]
