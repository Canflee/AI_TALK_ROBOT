from pathlib import Path

import yaml

from .models import Persona

VALID_TRIGGERS = {"private_all", "mention", "prefix", "off"}


def _build_persona(key: str, raw: dict, default_model: str) -> Persona:
    trigger = str(raw.get("trigger", "private_all")).strip().lower()
    if trigger not in VALID_TRIGGERS:
        raise ValueError(f"人设 {key} 的 trigger 无效: {trigger}，可选 {sorted(VALID_TRIGGERS)}")

    prefix = str(raw.get("prefix", ""))
    if trigger == "prefix" and not prefix:
        raise ValueError(f"人设 {key} 使用 prefix 触发，但未配置 prefix")

    system_prompt = str(raw.get("system_prompt", "")).strip()
    if not system_prompt:
        raise ValueError(f"人设 {key} 缺少 system_prompt")

    return Persona(
        key=key,
        display_name=str(raw.get("display_name", key)),
        system_prompt=system_prompt,
        model=str(raw.get("model", default_model)),
        temperature=float(raw.get("temperature", 0.7)),
        max_tokens=int(raw.get("max_tokens", 1200)),
        max_history=int(raw.get("max_history", 20)),
        max_context_chars=int(raw.get("max_context_chars", 6000)),
        cooldown=float(raw.get("cooldown", 2.0)),
        trigger=trigger,
        prefix=prefix,
        whitelist=[str(item) for item in (raw.get("whitelist") or [])],
    )


class PersonaRegistry:
    def __init__(self, default_key: str, personas: dict[str, Persona], bindings: dict[str, str]):
        self.default_key = default_key
        self.personas = personas
        self.bindings = bindings

    @classmethod
    def load(cls, path: Path, default_model: str) -> "PersonaRegistry":
        if not path.exists():
            raise FileNotFoundError(f"人设配置不存在: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw_personas = data.get("personas") or {}
        if not isinstance(raw_personas, dict) or not raw_personas:
            raise ValueError(f"{path} 中未配置任何 personas")

        personas = {
            str(key): _build_persona(str(key), raw or {}, default_model)
            for key, raw in raw_personas.items()
        }

        default_key = str(data.get("default") or next(iter(personas)))
        if default_key not in personas:
            raise ValueError(f"默认人设 {default_key} 不存在")

        bindings = {
            str(session): str(persona)
            for session, persona in (data.get("bindings") or {}).items()
        }
        unknown = set(bindings.values()) - set(personas)
        if unknown:
            raise ValueError(f"bindings 引用了不存在的人设: {sorted(unknown)}")

        return cls(default_key, personas, bindings)

    def get(self, key: str) -> Persona | None:
        return self.personas.get(key)

    def resolve(self, session_key: str, override_key: str | None = None) -> Persona:
        for key in (override_key, self.bindings.get(session_key), self.default_key):
            if key and key in self.personas:
                return self.personas[key]
        return self.personas[self.default_key]

    def describe(self) -> str:
        lines = [
            f"{persona.key} ({persona.display_name})"
            for persona in self.personas.values()
        ]
        return "可用人设：\n" + "\n".join(lines)
