"""Project-owned status-bit definitions, shared with standalone applications."""
import copy
import re

BIT_PROFILE_TYPES = {"StatusWordPanel", "DigitalTimingChart"}


def default_bit_profile(width=8):
    return {"width": width, "bits": [{"name": f"B{i}", "color": "#228866"} for i in range(width)]}


def normalize_bit_profiles(profiles):
    if not isinstance(profiles, dict):
        raise ValueError("bitProfiles must be an object")
    result = {}
    for name, profile in profiles.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(profile, dict):
            raise ValueError("Invalid bit profile")
        width = profile.get("width", 8)
        bits = profile.get("bits", [])
        if type(width) is not int or width not in (8, 16) or not isinstance(bits, list) or len(bits) > width:
            raise ValueError("Bit profiles support 8 or 16 bits")
        normalized = copy.deepcopy(profile)
        normalized.update(default_bit_profile(width))
        for index, bit in enumerate(bits):
            if not isinstance(bit, dict) or not isinstance(bit.get("name", f"B{index}"), str):
                raise ValueError("Invalid bit name")
            color = bit.get("color", "#228866")
            if not isinstance(color, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
                raise ValueError("Invalid bit color")
            normalized["bits"][index] = {**bit, "name": bit.get("name", f"B{index}"), "color": color}
        result[name] = normalized
    return result


def resolve_bit_profile(profiles, name="default"):
    return profiles.get(name, default_bit_profile())
