from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    llm_provider: str = "anthropic"
    main_agent_model: str = "claude-sonnet-4-6"
    classifier_model: str = "claude-haiku-4-5-20251001"
    # The extractor mutates durable memory and makes the hardest judgments
    # (confidence calibration, categorization), so it runs on Sonnet with
    # extended thinking. Set the budget to 0 to disable thinking.
    summarizer_model: str = "claude-sonnet-4-6"
    summarizer_thinking_budget: int = 4000
    # Document extraction reads already-extracted text (PDF text via PyMuPDF,
    # CSV/XLSX rendered to text) and classifies holdings — an easy task, so Haiku.
    document_model: str = "claude-haiku-4-5-20251001"
    memory_dir: Path = Path("memory")
    skills_dir: Path = Path("skills")
    sessions_dir: Path = Path("sessions")
    # Durable runtime logging: rotating file under log_dir so a week of logs and
    # errors survive process restarts (stdout alone is ephemeral).
    log_dir: Path = Path("logs")
    log_max_bytes: int = 5_000_000
    log_backup_count: int = 5
    max_response_tokens: int = 2048
    # Hard cap on tool-use round-trips per turn (Tier 3 agent loop), so a model
    # that keeps asking for tools can never loop forever.
    max_tool_iterations: int = 4
    # How many recent dated session-summary blocks of conversations.md to preload
    # into Tier 1. Older summaries stay on disk, reachable via recall_conversation.
    preloaded_summary_count: int = 5
    enable_cache: bool = True
    cors_origins: list[str] = ["http://localhost:5173"]
    # Advertise the app on the LAN under its own Bonjour/mDNS name so family
    # devices reach it at http://<mdns_name>.local:<mdns_port> without an IP or
    # renaming the host machine. mdns_port is the family-facing port (the Vite
    # dev server), since that is the URL people actually open.
    mdns_enabled: bool = True
    mdns_name: str = "saarthi"
    mdns_port: int = 5173
    project_root: Path = Path(__file__).resolve().parent.parent

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    def resolve(self, p: Path) -> Path:
        return self.project_root / p


settings = Settings()
