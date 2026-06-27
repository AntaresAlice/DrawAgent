"""M3 smoke tests for DrawAgent Memory System."""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")


async def smoke_test():
    # ── Setup: temp memory directory ──
    tmp_dir = Path(tempfile.mkdtemp())
    print(f"Using temp dir: {tmp_dir}")

    try:
        # ── 1. MemoryStore: create, write, read ──
        from drawagent.memory.store import MemoryStore

        store = MemoryStore(tmp_dir)
        assert store.base_dir == tmp_dir.resolve()

        await store.write("test/hello", "# Hello\n\nWorld content.", append=False)
        content = await store.read("test/hello")
        assert content == "# Hello\n\nWorld content."
        print("1. MemoryStore write/read: OK")

        # ── 2. MemoryStore: append ──
        await store.write("test/hello", "\n## Section 2\n\nMore content.")
        appended = await store.read("test/hello")
        assert "World content" in appended
        assert "Section 2" in appended
        print("2. MemoryStore append: OK")

        # ── 3. MemoryStore: list categories ──
        await store.write("category_a", "A", append=False)
        await store.write("category_b", "B", append=False)
        await store.write("nested/cat", "C", append=False)
        cats = await store.list_categories()
        assert "test/hello" in cats
        assert "category_a" in cats
        assert "category_b" in cats
        assert "nested/cat" in cats
        print("3. MemoryStore list_categories: OK")

        # ── 4. MemoryStore: search ──
        results = await store.search("World")
        assert len(results) >= 1
        assert any("test/hello" in r["file"] for r in results)
        print("4. MemoryStore search: OK")

        # ── 5. MemoryStore: path safety ──
        try:
            await store.read("../escape")
            assert False, "Should have raised"
        except ValueError:
            pass

        try:
            await store.read("valid/../../../escape")
            assert False, "Should have raised"
        except ValueError:
            pass
        print("5. MemoryStore path safety: OK")

        # ── 6. MemoryIndex: save and load ──
        from drawagent.memory.index import MemoryIndex, IndexEntry

        index = MemoryIndex(tmp_dir)
        entries = [
            IndexEntry(
                category="test/hello",
                title="Hello World",
                description="A test entry",
                tags=["test", "hello"],
                entry_count=2,
                last_updated="2026-01-01",
            ),
            IndexEntry(
                category="category_a",
                title="Category A",
                tags=["a"],
                entry_count=1,
                last_updated="2026-01-02",
            ),
        ]
        await index.save(entries)

        loaded = await index.load()
        assert len(loaded) == 2
        assert loaded[0].title == "Hello World"
        assert loaded[0].tags == ["test", "hello"]
        assert loaded[1].title == "Category A"
        print("6. MemoryIndex save/load: OK")

        # ── 7. MemoryIndex: rebuild and update ──
        cats2 = await store.list_categories()
        rebuilt = await index.rebuild(cats2, store)
        assert len(rebuilt) >= 3

        await store.write("test/hello", "\n## New Section\n\nFresh content.")
        await index.update_from_file("test/hello", store)

        loaded2 = await index.load()
        hello_entry = next((e for e in loaded2 if e.category == "test/hello"), None)
        assert hello_entry is not None
        assert hello_entry.entry_count >= 1
        print("7. MemoryIndex rebuild/update: OK")

        # ── 8. LoadMemoryTool ──
        from drawagent.memory.tools import LoadMemoryTool
        from drawagent.tools.base import ToolContext

        load_tool = LoadMemoryTool(store)
        ctx = ToolContext(session_id="s1", agent="A")

        result = await load_tool.execute({"category": "test/hello"}, ctx)
        assert result.success
        assert "Hello" in result.output
        assert "<memory category='test/hello'>" in result.output
        print("8. LoadMemoryTool: OK")

        # ── 9. LoadMemoryTool: not found ──
        result_nf = await load_tool.execute({"category": "nonexistent"}, ctx)
        assert result_nf.success
        assert "memory_not_found" in result_nf.output
        print("9. LoadMemoryTool not_found: OK")

        # ── 10. SearchMemoryTool ──
        from drawagent.memory.tools import SearchMemoryTool

        search_tool = SearchMemoryTool(store)
        result_s = await search_tool.execute({"query": "World content"}, ctx)
        assert result_s.success
        assert "<search_results>" in result_s.output
        assert "test/hello" in result_s.output
        print("10. SearchMemoryTool: OK")

        # ── 11. SearchMemoryTool: no results ──
        result_ns = await search_tool.execute({"query": "zzzznonexistent"}, ctx)
        assert result_ns.success
        assert "No matching" in result_ns.output
        print("11. SearchMemoryTool empty: OK")

        # ── 12. SaveMemoryTool ──
        from drawagent.memory.tools import SaveMemoryTool

        save_tool = SaveMemoryTool(store, index)
        result_sv = await save_tool.execute(
            {
                "category": "user/test",
                "content": "## My Custom Entry\n\nThis is saved knowledge.",
                "reason": "Testing save functionality",
            },
            ctx,
        )
        assert result_sv.success
        assert "Memory saved successfully" in result_sv.output

        saved_content = await store.read("user/test")
        assert "My Custom Entry" in saved_content
        assert "Testing save functionality" in saved_content
        print("12. SaveMemoryTool: OK")

        # ── 13. Built-in memory files exist ──
        project_memory = Path(__file__).parent.parent / "memory"
        assert (project_memory / "prompts" / "portraits.md").exists()
        assert (project_memory / "prompts" / "landscapes.md").exists()
        assert (project_memory / "prompts" / "objects.md").exists()
        assert (project_memory / "prompts" / "concepts.md").exists()
        assert (project_memory / "inspections" / "_builtin_common.md").exists()
        assert (project_memory / "inspections" / "_builtin_portrait.md").exists()
        assert (project_memory / "inspections" / "_builtin_scene.md").exists()
        assert (project_memory / "index.md").exists()
        print("13. Built-in memory files: OK")

        # ── 14. Built-in store can read project memory ──
        project_store = MemoryStore(project_memory)
        portraits = await project_store.read("prompts/portraits")
        assert portraits is not None
        assert "Portrait" in portraits or "portrait" in portraits.lower()
        print("14. Built-in store reads project memory: OK")

        # ── 15. ContextAssembler with memory ──
        from drawagent.context.assembler import ContextAssembler
        from drawagent.config.schema import AgentBConfig
        from drawagent.core.types import Session

        b_cfg = AgentBConfig()
        assembler = ContextAssembler(agent_b_config=b_cfg, memory_store=project_store)

        session = Session(id="test", user_request="draw a person")
        msgs = assembler.assemble_current_turn(session, "draw a person")
        assert len(msgs) == 2
        print("15. ContextAssembler with memory: OK")

        # ── 16. Load memory into session and assemble ──
        session.loaded_memories = ["prompts/portraits"]
        msgs2 = await assembler.assemble(session, None, [])
        assert len(msgs2) >= 2
        memory_msg = next((m for m in msgs2 if "memory source=" in str(m.content)), None)
        assert memory_msg is not None, "Memory not injected into assembled messages"
        print("16. Memory injection into context: OK")

        print()
        print("=== ALL M3 SMOKE TESTS PASSED ===")

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(smoke_test())
