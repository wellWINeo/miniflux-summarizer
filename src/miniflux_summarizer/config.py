import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PresetConfig:
    title: str | None = None
    from_value: str | None = None
    to_value: str | None = None


@dataclass
class AgentConfig:
    name: str
    source: str
    target_feed_id: int
    prompt: str
    source_feed_id: int | None = None
    history_lookback: int | None = None
    ignore: list[dict[str, str]] = field(default_factory=list)
    presets: dict[str, PresetConfig] = field(default_factory=dict)


@dataclass
class Config:
    miniflux_base_url: str
    miniflux_api_key: str
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    agent_name: str
    agent: AgentConfig
    digest_feed_ids: set[int]

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


def parse_history_lookback(value: str) -> int:
    if not isinstance(value, str):
        raise ValueError("history_lookback must be a relative duration such as '-7d'")

    match = re.fullmatch(r"-(\d+)([hdwm])", value)
    if match is None:
        raise ValueError("history_lookback must be a relative duration such as '-7d'")

    amount = int(match.group(1))
    if amount == 0:
        raise ValueError("history_lookback must be greater than zero")

    multipliers = {"h": 3600, "d": 86400, "w": 7 * 86400, "m": 30 * 86400}
    return amount * multipliers[match.group(2)]


def load_config(config_path: Path, agent_name: str, preset_name: str | None = None) -> Config:
    raw = json.loads(Path(config_path).read_text())

    if agent_name not in raw.get("agents", {}):
        raise ValueError(f"Error: agent '{agent_name}' not found in config")

    agent_raw = raw["agents"][agent_name]

    if agent_raw["source"] == "digests" and "source_feed_id" not in agent_raw:
        raise ValueError(f"Error: agent '{agent_name}' with source 'digests' requires 'source_feed_id'")

    history_lookback_raw = agent_raw.get("history_lookback")
    history_lookback = (
        parse_history_lookback(history_lookback_raw)
        if history_lookback_raw is not None
        else None
    )

    presets = {}
    for preset_key, preset_data in agent_raw.get("presets", {}).items():
        presets[preset_key] = PresetConfig(
            title=preset_data.get("title"),
            from_value=preset_data.get("from"),
            to_value=preset_data.get("to"),
        )

    agent = AgentConfig(
        name=agent_name,
        source=agent_raw["source"],
        target_feed_id=agent_raw["target_feed_id"],
        prompt=agent_raw["prompt"],
        source_feed_id=agent_raw.get("source_feed_id"),
        history_lookback=history_lookback,
        ignore=agent_raw.get("ignore", []),
        presets=presets,
    )

    digest_feed_ids = {
        int(agent_data["target_feed_id"])
        for agent_data in raw.get("agents", {}).values()
    }

    if preset_name is not None:
        if preset_name not in agent.presets:
            raise ValueError(f"Error: preset '{preset_name}' not found in agent '{agent_name}'")

    return Config(
        miniflux_base_url=raw["miniflux"]["base_url"],
        miniflux_api_key=raw["miniflux"]["api_key"],
        llm_model=raw["llm"]["model"],
        llm_base_url=raw["llm"]["base_url"],
        llm_api_key=raw["llm"]["api_key"],
        agent_name=agent_name,
        agent=agent,
        digest_feed_ids=digest_feed_ids,
    )
