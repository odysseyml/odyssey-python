"""Public O3 control snapshots and their versioned transport envelope."""

import math
from typing import Any, Literal, NotRequired, TypedDict, get_args

ActionControlKey = Literal[
    "w", "a", "s", "d", "e", "f", "lalt", "lctrl", "lshift", "rctrl", "space", "tab", "i", "j", "k", "l"
]
ActionControlButton = Literal["mouse_left", "mouse_middle", "mouse_right"]
ActionControlBinding = Literal["shift", "e", "f", "mouse_left", "mouse_right", "space", "c"]


class ActionControlsSemanticMap(TypedDict):
    version_id: Literal["action_controls_semantic_map/1"]
    mapping_id: str
    bindings: dict[ActionControlBinding, str]
    active_subject: NotRequired[str | None]


class ActionControls(TypedDict, total=False):
    """Complete held state plus relative mouse movement for one update.

    Empty keys/buttons release held inputs. Mouse deltas apply once and are
    clamped to [-50, 50]. I/J/K/L and look_key_level are display metadata;
    looking reaches the model through mouse_dx and mouse_dy.
    """

    keys: list[ActionControlKey]
    buttons: list[ActionControlButton]
    mouse_dx: float
    mouse_dy: float
    look_key_level: int
    semantic_map: ActionControlsSemanticMap | None


_KEYS = frozenset(get_args(ActionControlKey))
_BUTTONS = frozenset(get_args(ActionControlButton))


def action_controls_event(controls: ActionControls, stream_id: str, sequence: int) -> dict[str, Any]:
    if not isinstance(controls, dict):
        raise ValueError("Action controls must be an object")
    unknown = set(controls) - set(ActionControls.__annotations__)
    if unknown:
        raise ValueError(f"Unknown action control fields: {sorted(unknown)}")
    payload: dict[str, Any] = {}
    for name, allowed in (("keys", _KEYS), ("buttons", _BUTTONS)):
        values = controls.get(name, [])
        if not isinstance(values, (list, tuple)) or any(not isinstance(v, str) or v not in allowed for v in values):
            raise ValueError(f"{name} must contain supported control names")
        if len(set(values)) != len(values):
            raise ValueError(f"{name} must contain unique controls")
        payload[name] = list(values)
    for name in ("mouse_dx", "mouse_dy"):
        value = controls.get(name, 0.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        payload[name] = min(50.0, max(-50.0, float(value)))
    if "look_key_level" in controls:
        level = controls["look_key_level"]
        if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 3:
            raise ValueError("look_key_level must be an integer from 0 through 3")
        payload["look_key_level"] = level
    if controls.get("semantic_map") is not None:
        semantic = controls["semantic_map"]
        if not isinstance(semantic, dict) or set(semantic) - set(ActionControlsSemanticMap.__annotations__):
            raise ValueError("semantic_map must contain supported semantic map fields")
        if semantic.get("version_id") != "action_controls_semantic_map/1":
            raise ValueError("Unsupported semantic_map version")
        for name, maximum in (("mapping_id", 128), ("active_subject", 96)):
            value = semantic.get(name)
            if name == "active_subject" and value is None:
                continue
            if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
                raise ValueError(f"semantic_map.{name} must be a nonblank trimmed identifier")
        bindings = semantic.get("bindings")
        if not isinstance(bindings, dict) or set(bindings) != set(get_args(ActionControlBinding)):
            raise ValueError("semantic_map.bindings must define all seven controls")
        if any(
            not isinstance(v, str) or not v or v != v.strip() or "\n" in v or len(v) > 96 for v in bindings.values()
        ):
            raise ValueError("semantic_map bindings must be concise one-line phrases")
        shift = bindings["shift"]
        if len(shift.split()) != 1 or not shift.replace("-", "").isalpha():
            raise ValueError("semantic_map shift binding must be one impulse verb")
        payload["semantic_map"] = {**semantic, "bindings": dict(bindings)}
    return {
        "type": "action_controls",
        "payload": payload,
        "meta": {
            "version_id": "action_controls/1",
            "inference_session_id": stream_id,
            "inference_session_epoch": 0,
            "source_id": "odyssey-python-sdk",
            "sequence": sequence,
        },
    }
