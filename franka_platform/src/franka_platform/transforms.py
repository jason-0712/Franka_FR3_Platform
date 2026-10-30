"""xyzw Hamilton quaternions; R_base_tool maps tool vectors to base vectors."""
import math
from .protocol import require, vector


def quaternion(value, tolerance=1e-3):
    q = vector(value, 4, "quaternion_xyzw")
    norm = math.sqrt(sum(x*x for x in q))
    require(norm > 0 and abs(norm-1) <= tolerance, "INVALID_ACTION",
            f"Quaternion norm must be within {tolerance} of 1")
    return [x/norm for x in q]


def multiply(a, b):
    x, y, z, w = a
    X, Y, Z, W = b
    return [w*X+x*W+y*Z-z*Y, w*Y-x*Z+y*W+z*X,
            w*Z+x*Y-y*X+z*W, w*W-x*X-y*Y-z*Z]


def inverse(q):
    return [-q[0], -q[1], -q[2], q[3]]


def rotate(q, p):
    return multiply(multiply(q, [*p, 0]), inverse(q))[:3]


def angle(a, b):
    # q and -q represent the same orientation.
    return 2*math.acos(min(1.0, abs(sum(x*y for x, y in zip(a, b)))))


def delta_pose(reference, translation, rotation):
    return {"position_m": [a+b for a, b in zip(reference["position_m"], translation)],
            "quaternion_xyzw": multiply(rotation, reference["quaternion_xyzw"])}


def controller_pose(tool_pose, controller_to_tool):
    """T_base_controller = T_base_tool * inverse(T_controller_tool)."""
    q = multiply(tool_pose["quaternion_xyzw"], inverse(controller_to_tool["quaternion_xyzw"]))
    offset = rotate(q, controller_to_tool["position_m"])
    return {"position_m": [a-b for a, b in zip(tool_pose["position_m"], offset)],
            "quaternion_xyzw": q}


def tool_pose(controlled_pose, controller_to_tool):
    offset = rotate(controlled_pose["quaternion_xyzw"], controller_to_tool["position_m"])
    return {"position_m": [a+b for a, b in zip(controlled_pose["position_m"], offset)],
            "quaternion_xyzw": multiply(controlled_pose["quaternion_xyzw"],
                                         controller_to_tool["quaternion_xyzw"])}
