"""Unit tests for memory system."""

import tempfile
from pathlib import Path

import pytest

from drawagent.memory.index import IndexEntry, MemoryIndex
from drawagent.memory.store import MemoryStore
from drawagent.memory.tools import LoadMemoryTool, SaveMemoryTool, SearchMemoryTool
from drawagent.tools.base import ToolContext


@pytest.fixture
def tmp_store():
    d = Path(tempfile.mkdtemp())
    store = MemoryStore(d)
    yield store
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def tmp_index(tmp_store):
    return MemoryIndex(tmp_store.base_dir)


class TestMemoryStore:
    async def test_write_and_read(self, tmp_store):
        await tmp_store.write("test/cat", "# Test\n\nContent", append=False)
        content = await tmp_store.read("test/cat")
        assert "# Test" in content

    async def test_append(self, tmp_store):
        await tmp_store.write("test/cat", "# Part 1", append=False)
        await tmp_store.write("test/cat", "# Part 2")
        content = await tmp_store.read("test/cat")
        assert "Part 1" in content
        assert "Part 2" in content

    async def test_read_nonexistent(self, tmp_store):
        assert await tmp_store.read("nonexistent") is None

    async def test_delete(self, tmp_store):
        await tmp_store.write("test/cat", "data", append=False)
        assert await tmp_store.delete("test/cat") is True
        assert await tmp_store.delete("test/cat") is False

    async def test_list_categories(self, tmp_store):
        await tmp_store.write("a/test", "A", append=False)
        await tmp_store.write("b/test", "B", append=False)
        cats = await tmp_store.list_categories()
        assert "a/test" in cats
        assert "b/test" in cats

    async def test_search(self, tmp_store):
        await tmp_store.write("cat1", "Hello world", append=False)
        await tmp_store.write("cat2", "Goodbye moon", append=False)
        results = await tmp_store.search("world")
        assert len(results) >= 1
        assert any("cat1" in r["file"] for r in results)

    async def test_search_no_match(self, tmp_store):
        results = await tmp_store.search("zzzzz")
        assert len(results) == 0

    def test_path_safety_rejects_traversal(self, tmp_store):
        with pytest.raises(ValueError):
            tmp_store._safe_path("../escape")
        with pytest.raises(ValueError):
            tmp_store._safe_path("valid/../../../bad")

    def test_path_safety_accepts_valid(self, tmp_store):
        path = tmp_store._safe_path("prompts/portraits")
        assert path.parent == tmp_store.base_dir / "prompts"


class TestMemoryIndex:
    async def test_save_and_load(self, tmp_index):
        entries = [
            IndexEntry(category="a", title="A Title", tags=["t1"], entry_count=2, last_updated="2026-01-01"),
            IndexEntry(category="b", title="B Title", tags=["t2"], entry_count=1, last_updated="2026-01-02"),
        ]
        await tmp_index.save(entries)
        loaded = await tmp_index.load()
        assert len(loaded) == 2
        assert loaded[0].title == "A Title"
        assert loaded[0].tags == ["t1"]

    async def test_rebuild(self, tmp_store, tmp_index):
        await tmp_store.write("a/test", "# Hello\n\ntags: foo, bar\n\n## Section 1\n\nContent", append=False)
        await tmp_store.write("b/test", "# World\n\n## S1\n\n## S2", append=False)
        cats = await tmp_store.list_categories()
        entries = await tmp_index.rebuild(cats, tmp_store)
        assert len(entries) >= 2
        found_a = next((e for e in entries if e.category == "a/test"), None)
        assert found_a is not None
        assert found_a.title == "Hello"
        assert "foo" in found_a.tags

    async def test_update_from_file(self, tmp_store, tmp_index):
        await tmp_store.write("x/cat", "# Original\n\n## One", append=False)
        await tmp_index.update_from_file("x/cat", tmp_store)
        loaded = await tmp_index.load()
        assert any(e.category == "x/cat" for e in loaded)

        await tmp_store.write("x/cat", "# Updated\n\n## One\n\n## Two\n\n## Three", append=False)
        await tmp_index.update_from_file("x/cat", tmp_store)
        loaded2 = await tmp_index.load()
        entry = next(e for e in loaded2 if e.category == "x/cat")
        assert entry.title == "Updated"

    async def test_removes_deleted_file(self, tmp_store, tmp_index):
        await tmp_store.write("d/test", "data", append=False)
        await tmp_index.update_from_file("d/test", tmp_store)
        await tmp_store.delete("d/test")
        await tmp_index.update_from_file("d/test", tmp_store)
        loaded = await tmp_index.load()
        assert not any(e.category == "d/test" for e in loaded)


class TestMemoryTools:
    async def test_load_memory(self, tmp_store):
        await tmp_store.write("test/cat", "# Content", append=False)
        tool = LoadMemoryTool(tmp_store)
        ctx = ToolContext(session_id="s1", agent="A")
        result = await tool.execute({"category": "test/cat"}, ctx)
        assert result.success
        assert "<memory" in result.output
        assert "# Content" in result.output

    async def test_load_memory_not_found(self, tmp_store):
        tool = LoadMemoryTool(tmp_store)
        ctx = ToolContext(session_id="s1", agent="A")
        result = await tool.execute({"category": "no/exist"}, ctx)
        assert result.success
        assert "memory_not_found" in result.output

    async def test_search_memory(self, tmp_store):
        await tmp_store.write("a/test", "apple banana", append=False)
        await tmp_store.write("b/test", "cherry date", append=False)
        tool = SearchMemoryTool(tmp_store)
        ctx = ToolContext(session_id="s1", agent="A")
        result = await tool.execute({"query": "apple"}, ctx)
        assert result.success
        assert "a/test" in result.output

    async def test_search_empty(self, tmp_store):
        tool = SearchMemoryTool(tmp_store)
        ctx = ToolContext(session_id="s1", agent="A")
        result = await tool.execute({"query": "zzzz"}, ctx)
        assert result.success
        assert "No matching" in result.output

    async def test_save_memory(self, tmp_store, tmp_index):
        tool = SaveMemoryTool(tmp_store, tmp_index)
        ctx = ToolContext(session_id="s1", agent="A")
        result = await tool.execute(
            {"category": "saved/test", "content": "## New entry", "reason": "test"},
            ctx,
        )
        assert result.success
        assert "Memory saved" in result.output
        content = await tmp_store.read("saved/test")
        assert "New entry" in content
        assert "test" in content.lower()
