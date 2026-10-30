"""Version 1 JSON protocol; no executable deserialization."""
import json
import math

SCHEMA_VERSION = 1
ACTION_MODES = {"cartesian_absolute": "cartesian", "cartesian_delta": "cartesian",
                "joint_absolute": "joint", "gripper_width": None}
TERMINAL = {"validated", "completed", "rejected", "aborted"}


class PlatformError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

    def as_dict(self):
        return {"code": self.code, "message": str(self)}


def require(condition, code, message):
    if not condition:
        raise PlatformError(code, message)


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def vector(value, size, name):
    require(isinstance(value, list) and len(value) == size and all(map(finite, value)),
            "INVALID_ACTION", f"{name}: expected {size} finite numbers")
    return [float(x) for x in value]


def fields(value, expected, name):
    require(isinstance(value, dict) and set(value) == set(expected), "INVALID_ACTION",
            f"{name}: expected fields {sorted(expected)}")


def identifier(value, name):
    require(isinstance(value, str) and 0 < len(value) <= 128,
            "INVALID_ACTION", f"{name}: expected nonempty string, maximum 128 characters")


def loads(raw):
    def number(value):
        parsed = float(value)
        require(math.isfinite(parsed), "INVALID_ACTION", "Non-finite JSON number")
        return parsed

    def invalid(constant):
        raise PlatformError("INVALID_ACTION", f"Non-finite JSON number: {constant}")

    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, "INVALID_ACTION", f"Duplicate JSON key: {k}")
            result[k] = v
        return result

    require(isinstance(raw, str), "INVALID_ACTION", "Expected a JSON text frame")
    try:
        return json.loads(raw, parse_constant=invalid, parse_float=number, object_pairs_hook=pairs)
    except (ValueError, RecursionError) as exc:
        raise PlatformError("INVALID_ACTION", "Malformed JSON") from exc


def dumps(value):
    try:
        return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (ValueError, TypeError, RecursionError) as exc:
        raise PlatformError("INVALID_ACTION", "Message must contain finite JSON values") from exc
