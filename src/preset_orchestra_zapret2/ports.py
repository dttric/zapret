"""
Port list parsing and normalization helpers.

Used for:
- Normalizing `--wf-*-out=` values
- Merging category `--filter-tcp/--filter-udp` ports into wf lists
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class PortSpec:
    wildcard: bool
    intervals: Tuple[Tuple[int, int], ...]


def _parse_token(token: str) -> Optional[Tuple[bool, Tuple[int, int]]]:
    token = token.strip()
    if not token:
        return None
    if token == "*":
        return (True, (1, 65535))
    if "-" in token:
        left, right = token.split("-", 1)
        if not left.isdigit() or not right.isdigit():
            return None
        start = int(left)
        end = int(right)
        if start <= 0 or end <= 0:
            return None
        if start > end:
            start, end = end, start
        start = max(1, min(65535, start))
        end = max(1, min(65535, end))
        return (False, (start, end))
    if token.isdigit():
        value = int(token)
        if value <= 0:
            return None
        value = max(1, min(65535, value))
        return (False, (value, value))
    return None


def parse_port_spec(value: str) -> PortSpec:
    """
    Parses a comma-separated port specification into intervals.

    Supports:
    - "443"
    - "80,443"
    - "21000-21999"
    - "*"
    """
    wildcard = False
    intervals: List[Tuple[int, int]] = []
    for raw in value.split(","):
        parsed = _parse_token(raw)
        if not parsed:
            continue
        is_wildcard, interval = parsed
        if is_wildcard:
            wildcard = True
        intervals.append(interval)

    if wildcard:
        return PortSpec(wildcard=True, intervals=((1, 65535),))

    merged = merge_intervals(intervals)
    return PortSpec(wildcard=False, intervals=tuple(merged))


def merge_intervals(intervals: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
    items = [(int(a), int(b)) for a, b in intervals]
    items = [(min(a, b), max(a, b)) for a, b in items if a > 0 and b > 0]
    if not items:
        return []
    items.sort(key=lambda t: (t[0], t[1]))

    merged: List[Tuple[int, int]] = []
    cur_start, cur_end = items[0]
    for start, end in items[1:]:
        if start <= cur_end + 1:
            cur_end = max(cur_end, end)
            continue
        merged.append((cur_start, cur_end))
        cur_start, cur_end = start, end
    merged.append((cur_start, cur_end))
    return merged


def format_port_spec(spec: PortSpec) -> str:
    if spec.wildcard:
        return "*"
    parts: List[str] = []
    for start, end in spec.intervals:
        if start == end:
            parts.append(str(start))
        else:
            parts.append(f"{start}-{end}")
    return ",".join(parts)


def union_port_specs(values: Iterable[str]) -> str:
    """
    Unions multiple port spec strings and returns a normalized spec.

    Normalization:
    - Sorts by port ascending
    - Merges overlapping/adjacent ranges
    - Removes singles covered by a range (implicit after merge)
    """
    wildcard = False
    intervals: List[Tuple[int, int]] = []

    for value in values:
        if not value:
            continue
        spec = parse_port_spec(str(value))
        if spec.wildcard:
            wildcard = True
        intervals.extend(list(spec.intervals))

    if wildcard:
        return "*"

    merged = merge_intervals(intervals)
    return format_port_spec(PortSpec(wildcard=False, intervals=tuple(merged)))


def subtract_port_specs(value: str, remove: str) -> str:
    """
    Subtracts one port spec from another and returns a normalized spec.

    Examples:
    - subtract_port_specs("80,443", "443") -> "80"
    - subtract_port_specs("1-10", "5-6") -> "1-4,7-10"
    - subtract_port_specs("*", "1-65534") -> "65535"

    Returns empty string if nothing remains.
    """
    if not value:
        return ""
    if not remove:
        return union_port_specs([value])

    left = parse_port_spec(str(value))
    right = parse_port_spec(str(remove))

    if right.wildcard:
        return ""

    left_intervals = [(1, 65535)] if left.wildcard else list(left.intervals)
    right_intervals = list(right.intervals)

    if not left_intervals:
        return ""
    if not right_intervals:
        return format_port_spec(left)

    result: List[Tuple[int, int]] = []
    j = 0
    for start, end in left_intervals:
        cur = start
        while j < len(right_intervals) and right_intervals[j][1] < cur:
            j += 1

        k = j
        while k < len(right_intervals) and right_intervals[k][0] <= end:
            r_start, r_end = right_intervals[k]
            if r_start > cur:
                result.append((cur, min(end, r_start - 1)))
            cur = max(cur, r_end + 1)
            if cur > end:
                break
            k += 1

        if cur <= end:
            result.append((cur, end))

    merged = merge_intervals(result)
    if not merged:
        return ""
    return format_port_spec(PortSpec(wildcard=False, intervals=tuple(merged)))
