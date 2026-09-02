import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

SourceKind = Literal["all", "category", "feed"]


class SourceConfig(TypedDict):
    kind: SourceKind
    id: NotRequired[int]


@dataclass
class PresetConfig:
    title: str | None = None
    from_value: str | None = None
    to_value: str | None = None


@dataclass
class AgentConfig:
    name: str
    sources: list[SourceConfig]
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
    def sources(self) -> list[SourceConfig]:
        return self.agent.sources

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


def _parse_source(value: object, agent_name: str, index: int) -> SourceConfig:
    if not isinstance(value, dict):
        raise ValueError(f"Error: agent '{agent_name}' source at index {index} must be an object")

    kind = value.get("kind")
    if kind not in ("all", "category", "feed"):
        raise ValueError(
            f"Error: agent '{agent_name}' source at index {index} kind must be 'all', 'category', or 'feed'"
        )

    if kind == "all":
        if "id" in value:
            raise ValueError(f"Error: agent '{agent_name}' source at index {index} kind 'all' must not include 'id'")
        return {"kind": "all"}

    if "id" not in value:
        raise ValueError(f"Error: agent '{agent_name}' source at index {index} requires 'id'")
    source_id = value["id"]
    if isinstance(source_id, bool) or not isinstance(source_id, int):
        raise ValueError(f"Error: agent '{agent_name}' source at index {index} id must be an integer")

    return {"kind": cast(SourceKind, kind), "id": source_id}


def parse_sources(value: object, agent_name: str) -> list[SourceConfig]:
    if not isinstance(value, list):
        raise ValueError(f"Error: agent '{agent_name}' sources must be a list")
    if not value:
        raise ValueError(f"Error: agent '{agent_name}' sources must be non-empty")
    return [_parse_source(source, agent_name, index) for index, source in enumerate(value)]


def _parse_ignore_rules(value: object, agent_name: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError(f"Error: agent '{agent_name}' ignore must be a list")

    rules: list[dict[str, str]] = []
    for index, raw_rule in enumerate(value):
        if not isinstance(raw_rule, dict):
            raise ValueError(f"Error: agent '{agent_name}' ignore rule at index {index} must be an object")

        rule_type = raw_rule.get("type")
        if not isinstance(rule_type, str):
            raise ValueError(f"Error: agent '{agent_name}' ignore rule at index {index} requires 'type'")

        if rule_type == "generated_digests":
            if "value" in raw_rule:
                raise ValueError(
                    f"Error: agent '{agent_name}' generated_digests ignore rule must be without a value"
                )
            rules.append({"type": rule_type})
            continue

        rule_value = raw_rule.get("value")
        if rule_value is None:
            rules.append({"type": rule_type})
        elif isinstance(rule_value, str):
            rules.append({"type": rule_type, "value": rule_value})
        else:
            raise ValueError(f"Error: agent '{agent_name}' ignore rule at index {index} value must be a string")

    return rules


def load_config(config_path: Path, agent_name: str, preset_name: str | None = None) -> Config:
    raw = json.loads(Path(config_path).read_text())

    if agent_name not in raw.get("agents", {}):
        raise ValueError(f"Error: agent '{agent_name}' not found in config")

    agent_raw = raw["agents"][agent_name]

    if "sources" not in agent_raw:
        raise ValueError(f"Error: agent '{agent_name}' requires 'sources'")

    sources = parse_sources(agent_raw["sources"], agent_name)

    if "source_feed_id" in agent_raw:
        raise ValueError(f"Error: agent '{agent_name}' no longer supports 'source_feed_id'; use 'sources'")

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
        sources=sources,
        target_feed_id=agent_raw["target_feed_id"],
        prompt=agent_raw["prompt"],
        history_lookback=history_lookback,
        ignore=_parse_ignore_rules(agent_raw.get("ignore", []), agent_name),
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
