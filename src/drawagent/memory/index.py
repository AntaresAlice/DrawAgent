from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class IndexEntry:
    """An entry in the memory index for a single memory category."""

    category: str
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    entry_count: int = 0
    last_updated: str = ""


class MemoryIndex:
    """Master index of all memory categories for efficient lookup.

    The index lives at the root of the memory directory as index.md.
    It provides a quick overview so Agent A doesn't need to read every file
    to know what categories exist.
    """

    INDEX_FILENAME = "index.md"

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.index_path = base_dir / self.INDEX_FILENAME

    async def load(self) -> list[IndexEntry]:
        """Parse the index file and return all entries."""
        if not self.index_path.exists():
            return []
        content = self.index_path.read_text(encoding="utf-8")
        return self._parse_index(content)

    async def save(self, entries: list[IndexEntry]) -> None:
        """Write the index file from entries."""
        lines = [
            "# Memory Index",
            "",
            f"Last rebuilt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "| Category | Title | Tags | Entries | Last Updated |",
            "|----------|-------|------|---------|--------------|",
        ]

        for e in entries:
            tags = ", ".join(e.tags) if e.tags else "-"
            lines.append(
                f"| `{e.category}` | {e.title} | {tags} | {e.entry_count} | {e.last_updated or '-'} |"
            )

        lines.extend([
            "",
            "---",
            "",
            "## How to use this index",
            "",
            "- Use `load_memory` with the category name to load a specific category.",
            "- Use `search_memory` to find relevant memories by keyword.",
            "- Categories in `prompts/` contain reusable prompt templates.",
            "- Categories in `inspections/` contain quality checklists.",
            "",
        ])

        self.index_path.write_text("\n".join(lines), encoding="utf-8")

    async def rebuild(
        self, categories: list[str], store: "MemoryStore"
    ) -> list[IndexEntry]:
        """Rebuild the index by scanning all memory files."""
        entries: list[IndexEntry] = []

        for category in categories:
            content = await store.read(category)
            if content is None:
                continue

            title = category.split("/")[-1].replace("_", " ").title()
            match = re.search(r"^#\s+(.+)", content, re.MULTILINE)
            if match:
                title = match.group(1).strip()

            tags = self._extract_tags(content)
            entry_count = content.count("## ")

            entries.append(IndexEntry(
                category=category,
                title=title,
                description=content.split("\n\n")[0][:200] if content else "",
                tags=tags,
                entry_count=max(entry_count, 1),
                last_updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))

        await self.save(entries)
        return entries

    def _parse_index(self, content: str) -> list[IndexEntry]:
        """Parse the markdown table in the index file."""
        entries: list[IndexEntry] = []
        in_table = False

        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("| Category"):
                in_table = True
                continue
            if in_table:
                if not line.startswith("|"):
                    break
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 5 and parts[0].startswith("`"):
                    category = parts[0].strip("`")
                    title = parts[1]
                    tags_str = parts[2]
                    tags = [t.strip() for t in tags_str.split(",")] if tags_str != "-" else []
                    entry_count = int(parts[3]) if parts[3].isdigit() else 0
                    last_updated = parts[4] if parts[4] != "-" else ""

                    entries.append(IndexEntry(
                        category=category,
                        title=title,
                        tags=tags,
                        entry_count=entry_count,
                        last_updated=last_updated,
                    ))

        return entries

    def _extract_tags(self, content: str) -> list[str]:
        """Extract tags from markdown frontmatter or metadata lines."""
        tags: list[str] = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("tags:"):
                tags_str = line.split(":", 1)[1].strip()
                tags = [t.strip() for t in tags_str.split(",")]
                break
        return tags[:5]

    async def update_from_file(self, category: str, store: "MemoryStore") -> None:
        """Update a single entry in the index after a file changes."""
        entries = await self.load()
        content = await store.read(category)

        if content is None:
            entries = [e for e in entries if e.category != category]
        else:
            title = category.split("/")[-1].replace("_", " ").title()
            match = re.search(r"^#\s+(.+)", content, re.MULTILINE)
            if match:
                title = match.group(1).strip()
            new_entry = IndexEntry(
                category=category,
                title=title,
                tags=self._extract_tags(content),
                entry_count=content.count("## ") or 1,
                last_updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            replaced = False
            for i, e in enumerate(entries):
                if e.category == category:
                    entries[i] = new_entry
                    replaced = True
                    break
            if not replaced:
                entries.append(new_entry)

        await self.save(entries)
