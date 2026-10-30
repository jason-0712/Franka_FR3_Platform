"""Read-only URDF FK using explicit fixed transforms; no IK or planning."""
import math
import xml.etree.ElementTree as ET
from .protocol import require, vector
from .transforms import multiply, rotate


def axis_quaternion(axis, radians):
    norm = math.sqrt(sum(x*x for x in axis))
    require(norm > 0, "CONFIGURATION_ERROR", "URDF contains a zero joint axis")
    s = math.sin(radians/2)/norm
    return [*(x*s for x in axis), math.cos(radians/2)]


def compose(a, b):
    offset = rotate(a[1], b[0])
    return ([x+y for x, y in zip(a[0], offset)], multiply(a[1], b[1]))


class UrdfFK:
    def __init__(self, path, base, tool, joint_names):
        root = ET.parse(path).getroot()
        by_child = {j.find("child").get("link"): j for j in root.findall("joint")}
        self.chain = []
        current, seen = tool, set()
        while current != base:
            require(current not in seen and current in by_child, "CONFIGURATION_ERROR", "URDF cannot connect base to tool")
            seen.add(current)
            j = by_child[current]
            self.chain.append(j)
            current = j.find("parent").get("link")
        self.chain.reverse()
        actual = [j.get("name") for j in self.chain if j.get("type") != "fixed"]
        require(actual == joint_names, "CONFIGURATION_ERROR", "URDF FK chain does not match configured joint order")
        self.names = joint_names
        for j in self.chain:
            require(j.get("type") in ("fixed", "revolute", "continuous"), "CONFIGURATION_ERROR", "Unsupported FK joint type")

    def pose(self, positions):
        values = dict(zip(self.names, vector(positions, 7, "FK positions")))
        out = ([0., 0., 0.], [0., 0., 0., 1.])
        for j in self.chain:
            origin = j.find("origin")
            xyz = [float(x) for x in (origin.get("xyz", "0 0 0") if origin is not None else "0 0 0").split()]
            r, p, y = [float(x) for x in (origin.get("rpy", "0 0 0") if origin is not None else "0 0 0").split()]
            q = multiply(axis_quaternion([0, 0, 1], y), multiply(axis_quaternion([0, 1, 0], p), axis_quaternion([1, 0, 0], r)))
            out = compose(out, (vector(xyz, 3, "URDF origin"), q))
            if j.get("type") != "fixed":
                a = j.find("axis")
                axis = [float(x) for x in (a.get("xyz", "1 0 0") if a is not None else "1 0 0").split()]
                out = compose(out, ([0., 0., 0.], axis_quaternion(vector(axis, 3, "URDF axis"), values[j.get("name")])))
        return {"position_m": out[0], "quaternion_xyzw": out[1]}
