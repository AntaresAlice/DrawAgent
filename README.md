# DrawAgent

AI-powered image generation agent system — a collaborative multi-agent architecture
for automated prompt engineering, image generation, and quality inspection.

## Overview

DrawAgent uses three specialized agents working together:

```
User -> [Agent A: Art Director] -> [Agent B: Image Generator] -> Image
                |                          ^
                +--> [Agent C: Inspector] --+
```

- **Agent A** (LLM): Understands your request, writes prompts, plans inspections, judges quality
- **Agent B** (Image Model): Generates images via HTTP API (Z-Image, SD, DALL-E, etc.)
- **Agent C** (Vision LLM): Inspects generated images and reports observations

## Quick Start

```bash
# Install
pip install -e .

# Start web server
drawagent serve --port 8000

# Or use CLI mode
drawagent cli
```

Open `http://127.0.0.1:8000` in your browser for the web UI.

## Configuration

Configuration is discovered in 3 layers (later wins):

1. Package default: `.drawagent.default.yaml` (shipped with the package)
2. User global: `~/.drawagent/config.yaml`
3. Project directory: `.drawagent.yaml` (walk up from current directory)

### Example: `.drawagent.yaml`

```yaml
agent_a:
  provider: openai
  model: gpt-4o
  api_base: https://api.openai.com/v1
  api_key: ${OPENAI_API_KEY}    # Read from environment variable
  temperature: 0.7

agent_b:
  provider: local_zimage
  model: Z-Image-Turbo
  api_base: http://localhost:8000
  endpoint: /api/generate

agent_c:
  provider: openai
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}
  temperature: 0.3

loop:
  max_iterations: 7

memory:
  base_dir: ~/.drawagent/memory
  auto_load: true
```

## Architecture

```
DrawAgent/
├── src/drawagent/
│   ├── config/          # Pydantic config schema + 3-layer loader
│   ├── core/            # Session, Iteration, EventBus, error hierarchy
│   ├── providers/       # LLMProvider/VisionProvider abstracts, OpenAI-compat
│   ├── tools/           # ToolRegistry (register→materialize→settle), generate/inspect/ask
│   ├── orchestrator/    # SessionManager, 5-phase InnerLoop state machine, InterruptHandler
│   ├── agents/          # AgentA reasoning engine, system prompts
│   ├── context/         # 5-layer context assembly, iteration compaction
│   ├── memory/          # Markdown store, index, load/search/save tools
│   ├── persistence/     # aiosqlite database, session/iteration/image records
│   ├── api/             # FastAPI app, REST routes, WebSocket manager
│   ├── ui/static/       # Chat UI (HTML/CSS/JS, no framework)
│   └── main.py          # CLI entry: drawagent serve | drawagent cli
├── memory/              # Built-in prompt templates and inspection checklists
├── tests/               # Pytest unit + integration tests
└── outputs/             # Generated images (gitignored)
```

## Inner Loop

Each image generation iteration follows a fixed 5-phase state machine:

```
PLANNING -> PROMPT_REFINEMENT -> GENERATING -> INSPECTING -> EVALUATING
    ^                                                            |
    +------- (if issues found, iterate up to max_iterations) -----+
```

- **Planning**: Agent A designs inspection tasks for this round
- **Refinement**: Agent A improves the prompt based on previous issues (from round 2)
- **Generation**: Agent B produces images from the prompt
- **Inspection**: Agent C examines images for each inspection task
- **Evaluation**: Agent A judges overall quality — accept, iterate, or ask user

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Server status |
| POST | `/api/sessions` | Create a session |
| GET | `/api/sessions` | List all sessions |
| POST | `/api/sessions/{id}/message` | Send a user message |
| POST | `/api/sessions/{id}/interrupt` | Send interrupt (pause/steer/accept/rollback) |
| GET | `/api/sessions/{id}/history` | Get session history |
| DELETE | `/api/sessions/{id}` | Delete a session |
| GET | `/api/images/{filename}` | Serve generated image |
| WS | `/ws/sessions/{id}` | Real-time event stream |

## Memory System

Built-in memories are stored as Markdown files for both human and agent readability:

- `memory/prompts/` — Reusable prompt templates (portraits, landscapes, objects, concepts)
- `memory/inspections/` — Quality inspection checklists (common, portrait, scene)
- `memory/index.md` — Master index for quick category discovery

Agent A uses three memory tools:
- `load_memory` — Load a specific category
- `search_memory` — Full-text keyword search
- `save_memory` — Save reusable knowledge for future sessions

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

## License

MIT
