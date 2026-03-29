from __future__ import annotations

from pathlib import Path, PureWindowsPath
import re

from ..common.target_key_aliases import resolve_canonical_target_key
from ..common.source_preset_models import FilterProfile, ProfileSegment, SourcePreset


_MATCH_PREFIXES = (
    "--filter-",
    "--hostlist=",
    "--hostlist-domains=",
    "--hostlist-exclude=",
    "--ipset=",
    "--ipset-exclude=",
    "--ipset-ip=",
    "--payload=",
    "--in-range",
)

_ACTION_PREFIXES = (
    "--out-range",
    "--lua-desync=",
    "--dpi-desync",
    "--dup",
    "--wssize",
)

_DIRECTIVE_PREFIXES = (
    "--name",
    "--template",
    "--import",
    "--skip",
    "--cookie",
)

def normalize_text(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def split_header_and_body(text: str) -> tuple[list[str], list[str]]:
    header_lines: list[str] = []
    body_lines: list[str] = []
    in_header = True
    for raw in normalize_text(text).split("\n"):
        stripped = raw.strip()
        if in_header and (stripped.startswith("#") or not stripped):
            header_lines.append(raw)
            continue
        in_header = False
        body_lines.append(raw)
    return header_lines, body_lines


def split_preamble_and_profile_lines(body_lines: list[str]) -> tuple[list[str], list[list[str]]]:
    preamble: list[str] = []
    profiles: list[list[str]] = []
    current: list[str] = []
    saw_profile = False
    for raw in body_lines:
        stripped = raw.strip()
        if stripped == "--new":
            if saw_profile:
                profiles.append(current)
                current = []
            elif current:
                preamble.extend(current)
                current = []
            saw_profile = True
            continue
        if not saw_profile and not _looks_like_profile_line(stripped):
            preamble.append(raw)
            continue
        if not saw_profile and _looks_like_profile_line(stripped):
            saw_profile = True
        current.append(raw)
    if current:
        if saw_profile:
            profiles.append(current)
        else:
            preamble.extend(current)
    return preamble, profiles


def _looks_like_profile_line(stripped: str) -> bool:
    return any(stripped.startswith(prefix) for prefix in _MATCH_PREFIXES + _ACTION_PREFIXES + _DIRECTIVE_PREFIXES)


def protocol_from_match_lines(match_lines: list[str]) -> str:
    for line in match_lines:
        stripped = line.strip().lower()
        if stripped.startswith("--filter-udp="):
            return "udp"
        if stripped.startswith("--filter-l7="):
            return "l7"
        if stripped.startswith("--filter-tcp="):
            return "tcp"
    return "tcp"


def target_keys_for_selector_line(line: str, protocol_kind: str) -> tuple[str, ...]:
    stripped = line.strip()
    lowered = stripped.lower()
    if lowered.startswith("--hostlist="):
        value = stripped.split("=", 1)[1].strip().lstrip("@").strip('"').strip("'")
        base = _base_from_path(value, expect_ipset=False)
        return (_target_key(base, protocol_kind),) if base else ()
    if lowered.startswith("--ipset="):
        value = stripped.split("=", 1)[1].strip().lstrip("@").strip('"').strip("'")
        base = _base_from_path(value, expect_ipset=True)
        return (_target_key(base, protocol_kind),) if base else ()
    if lowered.startswith("--hostlist-domains="):
        value = stripped.split("=", 1)[1].strip()
        return tuple(_target_key(_base_from_domain(token), protocol_kind) for token in value.split(",") if _base_from_domain(token))
    if lowered.startswith("--ipset-ip="):
        value = stripped.split("=", 1)[1].strip()
        tokens = []
        for token in value.split(","):
            norm = re.sub(r"[^0-9a-z]+", "_", token.strip().lower()).strip("_")
            if norm:
                tokens.append(_target_key(f"inline_{norm}", protocol_kind))
        return tuple(tokens)
    return ()


def selector_family_for_line(line: str) -> str:
    lowered = line.strip().lower()
    if lowered.startswith("--hostlist="):
        return "hostlist"
    if lowered.startswith("--hostlist-domains="):
        return "hostlist-domains"
    if lowered.startswith("--hostlist-exclude="):
        return "hostlist-exclude"
    if lowered.startswith("--ipset="):
        return "ipset"
    if lowered.startswith("--ipset-exclude="):
        return "ipset-exclude"
    if lowered.startswith("--ipset-ip="):
        return "ipset-ip"
    return ""


def parse_source_preset(text: str) -> SourcePreset:
    header_lines, body_lines = split_header_and_body(text)
    preamble_lines, raw_profiles = split_preamble_and_profile_lines(body_lines)
    profiles = [parse_filter_profile(lines) for lines in raw_profiles]
    return SourcePreset(header_lines=header_lines, preamble_lines=preamble_lines, profiles=profiles)


def parse_filter_profile(lines: list[str]) -> FilterProfile:
    segments: list[ProfileSegment] = []
    match_lines: list[str] = []
    action_lines: list[str] = []
    protocol_kind = "tcp"
    target_keys: list[str] = []

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            segments.append(ProfileSegment(kind="blank", text=raw))
            continue
        if stripped.startswith("#"):
            segments.append(ProfileSegment(kind="comment", text=raw))
            continue

        if any(stripped.startswith(prefix) for prefix in _DIRECTIVE_PREFIXES):
            segments.append(ProfileSegment(kind="directive", text=stripped))
            continue

        kind = "action" if any(stripped.startswith(prefix) for prefix in _ACTION_PREFIXES) else "match"
        if kind == "match":
            match_lines.append(stripped)
            if stripped.lower().startswith(("--filter-tcp=", "--filter-udp=", "--filter-l7=")):
                protocol_kind = protocol_from_match_lines(match_lines)
            family = selector_family_for_line(stripped)
            keys = target_keys_for_selector_line(stripped, protocol_kind)
            if keys:
                for key in keys:
                    if key not in target_keys:
                        target_keys.append(key)
            segments.append(
                ProfileSegment(
                    kind="match",
                    text=stripped,
                    target_keys=keys,
                    selector_value=stripped.split("=", 1)[1].strip() if "=" in stripped else "",
                    selector_family=family,
                    selector_is_positive=family in {"hostlist", "hostlist-domains", "ipset", "ipset-ip"},
                )
            )
            continue

        action_lines.append(stripped)
        segments.append(ProfileSegment(kind="action", text=stripped))

    return FilterProfile(
        match_lines=match_lines,
        action_lines=action_lines,
        segments=segments,
        protocol_kind=protocol_kind,
        canonical_target_keys=tuple(target_keys),
    )


def serialize_source_preset(source: SourcePreset) -> str:
    lines: list[str] = []
    lines.extend(source.header_lines)
    if lines and source.preamble_lines and lines[-1].strip():
        lines.append("")
    lines.extend(source.preamble_lines)
    if source.preamble_lines and source.preamble_lines[-1].strip():
        lines.append("")
    for index, profile in enumerate(source.profiles):
        if index:
            lines.append("--new")
            lines.append("")
        emitted_any = False
        for segment in profile.segments:
            lines.append(segment.text)
            emitted_any = True
        if not emitted_any:
            lines.extend(profile.match_lines)
            lines.extend(profile.action_lines)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def _base_from_path(value: str, expect_ipset: bool) -> str:
    filename = PureWindowsPath(str(value or "")).name.lower()
    if not filename:
        return ""
    stem = Path(filename).stem
    if expect_ipset and stem.startswith("ipset-"):
        stem = stem[6:]
    stem = re.sub(r"[^0-9a-z]+", "_", stem.strip().lower()).strip("_")
    return stem


def _base_from_domain(value: str) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    token = token.replace("*.", "")
    token = token.split("/", 1)[0]
    token = token.split(":", 1)[0]
    if "." in token:
        token = token.split(".", 1)[0]
    return re.sub(r"[^0-9a-z]+", "_", token).strip("_")


def _target_key(base: str, protocol_kind: str) -> str:
    suffix = {"udp": "udp", "l7": "l7"}.get(protocol_kind, "tcp")
    return resolve_canonical_target_key(f"{base}_{suffix}")
