from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import asyncio


class SessionState(Enum):
    IDLE = "idle"
    REFINING = "refining"
    PLANNING = "planning"
    GENERATING = "generating"
    INSPECTING = "inspecting"
    ANALYZING = "analyzing"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"


@dataclass
class ImageRecord:
    filename: str
    path: str
    iteration: int
    seed: int
    width: int
    height: int
    prompt: str
    quality_score: float | None = None
    has_critical_artifact: bool = False


@dataclass
class InspectionTaskResult:
    task_name: str
    task_description: str
    passed: bool
    observation: str
    issues: list[str] = field(default_factory=list)


@dataclass
class QualityDecision:
    passed: bool
    confidence: float
    reasoning: str
    remaining_issues: list[dict] = field(default_factory=list)
    recommendation: str = ""


@dataclass
class InspectionRecord:
    iteration: int
    prompt: str
    tasks: list[InspectionTaskResult] = field(default_factory=list)
    decision: QualityDecision | None = None


@dataclass
class Iteration:
    number: int
    prompt: str
    gen_params: dict = field(default_factory=dict)
    images: list[ImageRecord] = field(default_factory=list)
    inspections: list[InspectionTaskResult] = field(default_factory=list)
    decision: QualityDecision | None = None
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None


@dataclass
class Session:
    id: str
    created_at: datetime = field(default_factory=datetime.now)
    state: SessionState = SessionState.IDLE

    user_request: str = ""
    iterations: list[Iteration] = field(default_factory=list)

    interrupt_event: asyncio.Event = field(default_factory=asyncio.Event)
    pending_action: str | None = None
    steer_message: str | None = None

    max_iterations: int = 7
    loaded_memories: list[str] = field(default_factory=list)
