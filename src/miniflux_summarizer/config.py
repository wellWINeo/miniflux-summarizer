import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict, cast

SourceKind = Literal["category", "feed"]


class SourceConfig(TypedDict):
    kind: SourceKind
    id: int


@dataclass
class PresetConfig:
    title: str | None = None
    from_value: str | None = None
    to_value: str | None = None


@dataclass
class AgentConfig:
    name: str
    source: SourceConfig
    target_feed_id: int
    prompt: str
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
    def source(self) -> SourceConfig:
        return self.agent.source

    @property
    def target_feed_id(self) -> int:
        return self.agent.target_feed_id

    @property
    def prompt(self) -> str:
        return self.agent.prompt

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


def parse_source(value: object, agent_name: str) -> SourceConfig:
    if not isinstance(value, dict):
        raise ValueError(f"Error: agent '{agent_name}' source must be an object with 'kind' and integer 'id'")

    if "kind" not in value:
        raise ValueError(f"Error: agent '{agent_name}' source requires 'kind'")
    kind = value["kind"]
    if kind not in ("category", "feed"):
        raise ValueError(f"Error: agent '{agent_name}' source kind must be 'category' or 'feed'")

    if "id" not in value:
        raise ValueError(f"Error: agent '{agent_name}' source requires 'id'")
    source_id = value["id"]
    if isinstance(source_id, bool) or not isinstance(source_id, int):
        raise ValueError(f"Error: agent '{agent_name}' source id must be an integer")

    return {"kind": cast(SourceKind, kind), "id": source_id}


def load_config(config_path: Path, agent_name: str, preset_name: str | None = None) -> Config:
    raw = json.loads(Path(config_path).read_text())

    if agent_name not in raw.get("agents", {}):
        raise ValueError(f"Error: agent '{agent_name}' not found in config")

    agent_raw = raw["agents"][agent_name]

    if "source" not in agent_raw:
        raise ValueError(f"Error: agent '{agent_name}' requires 'source'")

    source = parse_source(agent_raw["source"], agent_name)

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
        source=source,
        target_feed_id=agent_raw["target_feed_id"],
        prompt=agent_raw["prompt"],
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
