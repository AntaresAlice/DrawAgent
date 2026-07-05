# DrawAgent — Your AI Art Director

> Describe what you want. Leave the rest to the Agent. DrawAgent empowers an LLM to act like a seasoned art director — understanding your vision, crafting prompts, orchestrating image generation, inspecting results, and iterating autonomously until you're satisfied.

---

## Why DrawAgent?

AI image generation is powerful in theory, but frustrating in practice:

| Pain Point | The Reality | How DrawAgent Solves It |
|------------|-------------|--------------------------|
| **Prompts are hard to write** | You don't know how to precisely describe the image in your head; vague terms like "detailed" or "atmospheric" fall flat | The LLM translates fuzzy natural language into rich, specific visual descriptions — filling in lighting, materials, composition, and mood |
| **Prompts don't transfer** | A great Midjourney prompt fails on Stable Diffusion. Every model speaks its own "dialect" | The Agent understands each model's quirks and adapts prompts accordingly. Effective patterns are saved and reused across sessions |
| **Too much waiting** | Generate → not happy → tweak prompt → generate again → repeat. Hours wasted staring at progress bars | The Agent runs the full generate→inspect→refine→regenerate loop autonomously. You sit back, watch, and jump in only when you want to |

**In short**: DrawAgent frees you from being a "prompt engineer." Speak naturally, and let AI handle the professional craft.

---

## Core Features

### 1. LLM-Driven Agent with Tools — Automated Iteration

DrawAgent's core is a single LLM Agent that orchestrates the entire image generation process. It has access to a suite of tools:

```
                    ┌── generate_image ──→ Image Generation Model (HTTP / MCP)
You ──→ [LLM Agent] ──┼── inspect_image ──→ Vision Model
                    ├── compare_images ──→ Vision Model (side-by-side)
                    └── load/search/save_memory ──→ Memory System
```

- **generate_image** — Calls the image generation model (Z-Image, SD, DALL·E, etc.) to turn prompts into images
- **inspect_image / compare_images** — Calls a vision model to examine generated images, checking requirements point by point
- **Memory tools** — Load past experience, search for relevant templates, save effective prompt patterns

Each generation follows a five-phase automated iteration loop:

```
Plan Inspections → Refine Prompt → Generate → Inspect → Evaluate
    ↑                                                        │
    └──── Issues found — automatically start next iteration ──┘
```

After the vision model inspects images, the Agent pinpoints specific issues — "Is the left hand correct?" "Is the lighting direction right?" "Are the background details sufficient?" — then surgically revises the prompt and regenerates. This closed loop runs automatically until quality standards are met or the iteration limit is reached.

### 2. Smart Prompt Decomposition — Automatic Variant Splitting

Diffusion models struggle with composite semantics. Type "wearing a T-shirt / shirt / short-sleeve" and the model gets confused — it might pick one at random, or worse, cram all three into one image.

DrawAgent's LLM intelligently parses natural language for branching relationships:

- Detects `/` (slash), "or", "either...or...", enumeration lists, and other branching markers
- Automatically splits into multiple independent images, each focused on one coherent set of elements
- For example: "ponytail/short hair + T-shirt/tank top" → the Agent generates 2×2 = 4 images covering all combinations

### 3. Fuzzy Semantic Completion — Turning Vibes into Visuals

Non-expert users often write abstract, emotional descriptions: "atmospheric," "detailed," "more refined," "freestyle." Image generation models have no idea what to do with these.

DrawAgent's LLM automatically translates vague descriptions into concrete visual instructions the model can understand:

- "Classroom background, detailed" → expands to "A dark green chalkboard at the back, a national flag above, white curtains billowing at the window, sunlight slanting across wooden desk surfaces"
- "Atmospheric" → supplements with specific lighting, color palette, and composition details
- "Freestyle" / "Surprise me" → selects concrete styles, elements, and compositions and writes them into the prompt

This is the core value of the LLM — understanding fuzzy semantics and outputting deterministic visual descriptions, bridging the gap between human natural language and model prompts.

### 4. Continuous Learning — Skill & Memory System

Every successful generation feeds back into the knowledge base:

- **Prompt Templates** — Verified effective prompt fragments saved as Markdown documents, categorized by theme (portraits / landscapes / objects / conceptual art). Automatically loaded when similar requests come up
- **Inspection Checklists** — Domain-specific quality dimensions (universal, portrait, scene) ensure nothing is missed during review
- **Cross-Session Reuse** — Portrait techniques discovered today are automatically available tomorrow. Knowledge never evaporates

All memory files are plain Markdown — readable and editable by both humans and agents.

### 5. Conversational UI with Real-Time Control

A user-friendly chat interface that keeps you in the loop:

- **Live Observation** — Watch the Agent write prompts, dispatch generation, and inspect results as streaming cards, all in real time
- **Interrupt Anytime** — Like or dislike a direction? Send a steering command — "emphasize the subject," "change the weather to rainy," "fix the left hand, it looks weird" — and the Agent pivots immediately
- **Step Mode** — Pause after each iteration and decide: Continue / Accept / Steer / Rollback
- **Fork & Resume** — Branch off from any intermediate state to explore alternatives without touching the original session. All sessions persisted to SQLite — pick up right where you left off

---

## Supported Models

DrawAgent locks you into no specific model. All components connect via OpenAI-compatible APIs:

| Component | Supported Model Types | Verified Models |
|-----------|----------------------|-----------------|
| LLM Agent | Any OpenAI-compatible API | DeepSeek v4, GPT-4o, Qwen, Ollama |
| Image Generation (generate_image) | HTTP API / MCP protocol | Z-Image, SD series, DALL·E |
| Vision Model (inspect/compare) | Any vision-capable OpenAI-compatible API | GPT-4o, Qwen VL, Ollama |

All config values support `${ENV_VAR}` environment variable references — no secrets in files.

---

## Quick Start

### Prerequisites

- Python 3.11+
- At least one accessible LLM API (DeepSeek / OpenAI / local Ollama, etc.)
- (Optional) An image generation API or locally deployed image model

### Installation

```bash
git clone https://github.com/yourorg/DrawAgent.git
cd DrawAgent
pip install -e .
```

### Configuration

Create `.drawagent.yaml` in the project root, using the shipped `.drawagent.default.yaml` as a template. Config loading priority (later wins):

> Package default → `~/.drawagent/config.yaml` → project `.drawagent.yaml` → `--config` flag → CLI flags

### Launch Web UI

```bash
drawagent serve --port 8000
# Open http://127.0.0.1:8000 in your browser
```

Describe your desired image in the chat input. The Agent handles the rest.

---

## Usage Guide

DrawAgent offers three runtime modes for different scenarios.

### `drawagent serve` — Web Server

Starts a FastAPI server with the Web UI. Best for daily use.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--port N` | 8000 | Listening port |
| `--host HOST` | 127.0.0.1 | Bind address |
| `--output-dir PATH` | ./outputs | Image output directory |
| `--config PATH` | Auto-discovered | Config file path |

```bash
drawagent serve                        # Default
drawagent serve --port 8080            # Custom port
drawagent serve --host 0.0.0.0 --port 8080  # LAN access
```

### `drawagent cli` — Interactive Terminal

Chat-style generation in the terminal. Ideal for headless servers or CLI enthusiasts.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--output-dir PATH` | ./outputs | Image output directory |
| `--config PATH` | Auto-discovered | Config file path |
| `--db PATH` | None | Enable SQLite persistence |
| `--step` | false | Step mode — pause after each iteration |
| `--resume ID` | None | Resume a specific session |
| `--from-iteration N` | 0 | Resume from iteration N |
| `--rerun-last` | false | Re-run the last iteration |

**Normal mode commands**:

| Command | Description |
|---------|-------------|
| Plain text | Start a generation workflow |
| `/quit` | Exit |
| `/help` | Show help |
| `/status` | Show session status |

**Step mode commands** (requires `--step`):

| Command | Description |
|---------|-------------|
| Enter or `/next` | Continue to next iteration |
| `/accept` | Accept current result and finish |
| `/steer <msg>` | Adjust direction for subsequent generation |
| `/rollback` | Roll back to previous iteration |
| `/quit` | Exit |

```bash
drawagent cli                                   # Quick start
drawagent cli --db ~/.drawagent/sessions.db     # Persistent, resumable
drawagent cli --step                            # Step-through debugging
drawagent cli --db ~/.drawagent/sessions.db --step  # Full debug setup
```

### `drawagent run` — Non-Interactive Execution

GDB-style precise control for debugging and scripting.

| Parameter | Description |
|-----------|-------------|
| `PROMPT` | Image generation request (positional) |
| `--config PATH` | Config file |
| `--db PATH` | SQLite database path |
| `--resume ID` | Resume a specific session |
| `--from-iteration N` | Trim iterations from N onward, then execute |
| `--fork` | Copy session into a new branch (original untouched) |
| `--user-input TEXT` | Inject a steering command |
| `--steps N` | Execute N iterations (0 = unlimited) |
| `--gen-params PATH` | Load a generation preset YAML |
| `--width PX` / `--height PX` | Image dimensions |
| `--steps-param N` | Diffusion steps |
| `--guidance N` | CFG guidance scale |
| `--seed N` | Random seed (-1 for random) |
| `--num-images N` | Images per iteration |
| `--model-a/c MODEL` | Override model name |
| `--api-key-a/c KEY` | Override API key |
| `--agent-b-type http\|mcp` | Agent B protocol type |

```bash
# One-shot generation
drawagent run "a warrior princess portrait, cinematic lighting"

# Resume from iteration 2, inject a steer, execute 1 step (observe LLM adjustment)
drawagent run --db debug.db --resume run-xxx \
  --from-iteration 2 --user-input "make the armor more ornate" --steps 1

# Fork a new branch, inject steer, execute 3 steps
drawagent run --db debug.db --resume run-xxx --fork \
  --user-input "change to nighttime scene" --steps 3

# Pure fork (no execution) — get a branch point
drawagent run --db debug.db --resume run-xxx --fork

# Continue on the forked session
drawagent run --db debug.db --resume fork-run-2026... --steps 1
```

### Generation Presets

Four presets are provided in `gen_presets/`:

| Preset | Resolution | Steps | Guidance | Images | Use Case |
|--------|-----------|-------|----------|--------|----------|
| `high-quality.yaml` | 1280×1280 | 30 | 7.0 | 1 | Final output |
| `fast-preview.yaml` | 768×768 | 4 | 3.5 | 2 | Quick preview |
| `portrait.yaml` | 960×1280 | 30 | 7.0 | 4 | Portraits |
| `seed-sweep.yaml` | 1024×1024 | 8 | 3.5 | 4 | Seed exploration |

Usage with `run`:

```bash
drawagent run "a cat in a garden" --gen-params gen_presets/fast-preview.yaml
```

---

## Architecture

```
DrawAgent/
├── src/drawagent/
│   ├── config/           # Pydantic config models + multi-layer loader
│   ├── core/             # Session, Iteration, EventBus, error hierarchy
│   ├── providers/        # LLM/Vision abstraction layer + OpenAI-compatible impl
│   ├── tools/            # Tool system (register → materialize → settle)
│   ├── agents/           # Main Agent reasoning engine + system prompts
│   ├── orchestrator/     # SessionManager, 5-phase state machine, InterruptHandler
│   ├── context/          # 5-layer context assembly, iteration compaction
│   ├── memory/           # Markdown memory store + index + search
│   ├── persistence/      # aiosqlite database
│   ├── api/              # FastAPI + WebSocket real-time events
│   ├── ui/static/        # Pure HTML/CSS/JS frontend (zero framework dependency)
│   └── main.py           # CLI entry point
├── memory/               # Built-in prompt templates & inspection checklists
├── gen_presets/          # Generation parameter presets
├── tests/                # Test suite (14 test files)
├── docs/                 # Design docs, roadmap, etc.
└── outputs/              # Generated images (gitignored)
```

### Memory System

DrawAgent's memory is stored as human-and-agent-readable Markdown files:

```
~/.drawagent/memory/
├── index.md                   # Auto-maintained index
├── prompts/                   # Prompt template library
│   ├── portraits.md
│   ├── landscapes.md
│   ├── objects.md
│   └── concepts.md
└── inspections/               # Inspection checklist library
    ├── _builtin_common.md
    ├── _builtin_portrait.md
    └── _builtin_scene.md
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Server health check |
| POST | `/api/sessions` | Create a session |
| GET | `/api/sessions` | List all sessions |
| POST | `/api/sessions/{id}/message` | Send a user message |
| POST | `/api/sessions/{id}/interrupt` | Interrupt control (pause/steer/accept/rollback) |
| GET | `/api/sessions/{id}/history` | Get session history |
| DELETE | `/api/sessions/{id}` | Delete a session |
| GET | `/api/images/{filename}` | Serve a generated image |
| GET / PUT | `/api/config` | Read/write runtime config |
| GET | `/api/sessions/{id}/export` | Export session as ZIP |
| WS | `/ws/sessions/{id}` | WebSocket real-time event stream |

---

## Demo

### Workflow Example

```
You: Draw an ancient Chinese warrior woman in the rain,
     wearing a bamboo hat, red cape, cinematic lighting

Agent: [Analyzing] A female warrior in ancient Chinese style —
       rainy scene, bamboo hat, red cape, cinematic lighting
       [Refining prompt...]
       Ancient Chinese swordswoman, bamboo conical hat,
       red cape billowing in rain, raindrops dripping from
       hat brim, cool background, rim light illuminating
       the figure, cinematic lighting, 85mm, shallow DOF

Agent: [generate_image] Generating... gen_001.png ✓

Agent: [inspect_image — checking each dimension]
       ✅ Bamboo hat: clearly visible, texture visible
       ✅ Red cape: vibrant, natural movement in rain
       ✅ Rain scene: raindrops visible, puddle reflections
       ⚠️ Face: expression slightly stiff, gaze not sharp enough
       ⚠️ Lighting: rim light effect insufficient

Agent: [Iteration 2] Adjusting facial expression and lighting,
       increasing rim light contrast, sharpening gaze,
       adding: "sharp determined gaze, dramatic side lighting,
       raindrops visible on face"...

Agent: [generate_image] Generating... gen_002.png ✓

Agent: [inspect_image] All dimensions passed ✓

Agent: [Delivering] 2 iterations, quality target met
```

In the Web UI, this entire process unfolds as live streaming cards with clear visual feedback at every stage.

### Web UI Highlights

- **Session Sidebar** — Manage multiple sessions, switch on the fly
- **Quick Parameter Bar** — Width, height, count, steps, guidance at your fingertips
- **Image Viewer** — Fullscreen, prev/next navigation, download, copy
- **Iteration Compare** — Side-by-side comparison across iterations
- **Interrupt Controls** — Accept / Steer / Pause mid-generation
- **System Settings** — Change Providers, Models, API Keys at runtime, no restart needed
- **Bilingual UI** — Chinese / English toggle
- **Keyboard Shortcuts** — `Ctrl+Enter` to send, `Esc` to close modals, `Ctrl+Shift+N` new session

---

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/

# Type check
pyright src/
```

---

## Roadmap

- [ ] **MCP Cold Start Elimination** — Keep MCP alive between iterations to avoid GPU model reload overhead
- [ ] **Parallel Tool Calls** — Batch-execute vision inspections concurrently for dramatic speed gains
- [ ] **Skill System** — On-demand domain-specific skill modules (inspired by OpenCode's skill architecture)
- [ ] **Multimodal User Input** — Upload reference images with text for style transfer and img2img workflows
- [ ] **Vision-capable Main Agent** — When the LLM itself supports vision, inspect images directly, bypassing external vision model calls
- [ ] **Multiple Image Model Support** — Connect to multiple image generation models simultaneously, auto-select by task type
- [ ] **Prompt Template Library Evolution** — More domain templates with automatic recommendation

See [docs/ROADMAP.md](docs/ROADMAP.md) for details.

---

## FAQ

<details>
<summary><b>Q: Can I use DrawAgent without a GPU?</b></summary>

Yes. The LLM and vision models use cloud APIs (DeepSeek / OpenAI / any OpenAI-compatible service). Image generation can also use cloud APIs (e.g., DALL·E or a remotely deployed Stable Diffusion). You only need API keys — no local GPU required.

</details>

<details>
<summary><b>Q: How do I connect local Ollama models?</b></summary>

Configure as follows:

```yaml
agent_a:
  provider: openai
  model: qwen3:14b
  api_base: http://localhost:11434/v1
  api_key: ollama

agent_c:
  provider: openai
  model: qwen3-vl:latest
  api_base: http://localhost:11434/v1
  api_key: ollama
```

Note: The vision model needs a large context window (32K+ recommended). Models smaller than 9B may produce empty VLM responses.

</details>

<details>
<summary><b>Q: How do I use MCP protocol for image generation?</b></summary>

```yaml
agent_b:
  type: mcp
  mcp_command: ["python", "mcp_server.py"]
  mcp_keep_alive: false   # false = release GPU VRAM after each generation
```

`mcp_keep_alive: false` is ideal when GPU is shared between programs (e.g., Ollama and image generation sharing the same GPU).

</details>

<details>
<summary><b>Q: How do I debug a specific iteration?</b></summary>

Use the precision controls of `drawagent run`:

```bash
# Load session, roll back to iteration 2, inject a steer, execute 1 step
drawagent run --db debug.db --resume SESSION_ID \
  --from-iteration 2 --user-input "brighten the scene" --steps 1
```

Combine with `--fork` to safely explore alternatives without touching the original session.

</details>

<details>
<summary><b>Q: How do environment variable references work in the config?</b></summary>

Use `${ENV_VAR_NAME}` syntax — automatically resolved at load time:

```yaml
api_key: ${OPENAI_API_KEY}
```

The API key is never written to the config file. Just set the corresponding environment variable.

</details>

---

## License

MIT

---

## Contributing

Issues and pull requests are welcome. Before contributing, we recommend reading [DESIGN.md](DESIGN.md) for the architecture design and [docs/ROADMAP.md](docs/ROADMAP.md) for current development plans.
