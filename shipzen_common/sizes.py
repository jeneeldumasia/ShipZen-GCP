"""Instance sizes and scaling limits for user apps (shared by the API and the controller).

Caps keep the worst case inside the tenant ResourceQuota (limits 8 CPU / 16 GiB):
during a blue-green switch two releases run at max instances for a few minutes,
plus up to three small PR previews (1.5 CPU / 1.5 GiB of limits).
"""
from typing import Optional

SIZES = {
    #          requests              limits                most instances
    "small":  {"cpu": "100m", "memory": "128Mi", "cpu_limit": "500m", "memory_limit": "512Mi",
               "vcpu": 0.1, "gib": 0.125, "max_instances": 5},
    "medium": {"cpu": "250m", "memory": "512Mi", "cpu_limit": "1", "memory_limit": "1Gi",
               "vcpu": 0.25, "gib": 0.5, "max_instances": 3},
    "large":  {"cpu": "500m", "memory": "1Gi", "cpu_limit": "1", "memory_limit": "2Gi",
               "vcpu": 0.5, "gib": 1.0, "max_instances": 2},
}
DEFAULT_SIZE = "small"


def size_spec(name: Optional[str]) -> dict:
    return SIZES.get(name or DEFAULT_SIZE) or SIZES[DEFAULT_SIZE]


def scaling_problem(size: str, min_instances: int, max_instances: int) -> Optional[str]:
    """Why these settings aren't allowed, or None."""
    if size not in SIZES:
        return f"Size must be one of: {', '.join(SIZES)}."
    if min_instances < 1:
        return "At least 1 instance must run."
    if max_instances < min_instances:
        return "Maximum instances can't be lower than minimum instances."
    cap = SIZES[size]["max_instances"]
    if max_instances > cap:
        return f"A {size} app can run at most {cap} instances."
    return None
