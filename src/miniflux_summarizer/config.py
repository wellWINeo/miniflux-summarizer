import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentConfig:
    name: str
    source: str
    target_feed_id: int
    prompt: str
    source_feed_id: int | None = None
    ignore: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Config:
    miniflux_base_url: str
    miniflux_api_key: str
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    agent_name: str
    agent: AgentConfig

    @property
    def source(self) -> str:
        return self.agent.source

    @property
    def target_feed_id(self) -> int:
        return self.agent.target_feed_id

    @property
    def prompt(self) -> str:
        return self.agent.prompt

    @property
    def source_feed_id(self) -> int | None:
        return self.agent.source_feed_id

    @property
    def ignore(self) -> list[dict[str, str]]:
        return self.agent.ignore


def load_config(config_path: Path, agent_name: str) -> Config:
    raw = json.loads(Path(config_path).read_text())

    if agent_name not in raw.get("agents", {}):
        raise ValueError(f"Error: agent '{agent_name}' not found in config")

    agent_raw = raw["agents"][agent_name]

    if agent_raw["source"] == "digests" and "source_feed_id" not in agent_raw:
        raise ValueError(f"Error: agent '{agent_name}' with source 'digests' requires 'source_feed_id'")

    agent = AgentConfig(
        name=agent_name,
        source=agent_raw["source"],
        target_feed_id=agent_raw["target_feed_id"],
        prompt=agent_raw["prompt"],
        source_feed_id=agent_raw.get("source_feed_id"),
        ignore=agent_raw.get("ignore", []),
    )

    return Config(
        miniflux_base_url=raw["miniflux"]["base_url"],
        miniflux_api_key=raw["miniflux"]["api_key"],
        llm_model=raw["llm"]["model"],
        llm_base_url=raw["llm"]["base_url"],
        llm_api_key=raw["llm"]["api_key"],
        agent_name=agent_name,
        agent=agent,
    )
