from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


SEMANTIC_STATUS_ABSENT = "absent"
SEMANTIC_STATUS_STRUCTURED_SUPPORTED = "structured_supported"
SEMANTIC_STATUS_RAW_ONLY_SUPPORTED = "raw_only_supported"
SEMANTIC_STATUS_INVALID = "invalid"

_TOKENS_RE = re.compile(r"--[^\s]+")
_TOP_LEVEL_OUT_RANGE_RE = re.compile(r"^--out-range=(.*)$", re.IGNORECASE)
_INLINE_OUT_RANGE_RE = re.compile(r":out_range=([^:\s]*)(?=(:|$))", re.IGNORECASE)
_STRUCTURED_OUT_RANGE_RE = re.compile(r"^-([nd])(\d+)$", re.IGNORECASE)
_RAW_ONLY_OUT_RANGE_RE = re.compile(r"^-?[A-Za-z0-9][A-Za-z0-9._,-]*$")


@dataclass
class OutRangeState:
    status: str = SEMANTIC_STATUS_ABSENT
    tokens: tuple[str, ...] = ()
    raw_value: str = ""
    source: str = ""
    out_range: int | None = None
    out_range_mode: str = ""
    preserve_token_raw: bool = False

    @property
    def explicit(self) -> bool:
        return bool(self.tokens)


@dataclass
class SendState:
    status: str = SEMANTIC_STATUS_ABSENT
    tokens: tuple[str, ...] = ()
    structured: dict[str, Any] = field(default_factory=dict)
    preserve_token_raw: bool = False


@dataclass
class SyndataState:
    status: str = SEMANTIC_STATUS_ABSENT
    tokens: tuple[str, ...] = ()
    structured: dict[str, Any] = field(default_factory=dict)
    preserve_token_raw: bool = False


@dataclass
class BlockSemantics:
    out_range: OutRangeState = field(default_factory=OutRangeState)
    send: SendState = field(default_factory=SendState)
    syndata: SyndataState = field(default_factory=SyndataState)

    @property
    def has_explicit_out_range(self) -> bool:
        return self.out_range.explicit

    @property
    def can_edit_out_range_structurally(self) -> bool:
        return self.out_range.status == SEMANTIC_STATUS_STRUCTURED_SUPPORTED

    @property
    def should_warn_about_out_range(self) -> bool:
        return self.out_range.status in {
            SEMANTIC_STATUS_ABSENT,
            SEMANTIC_STATUS_INVALID,
        }

    @property
    def should_preserve_any_token_raw(self) -> bool:
        return bool(
            self.out_range.preserve_token_raw
            or self.send.preserve_token_raw
            or self.syndata.preserve_token_raw
        )

    def has_structured_advanced_state(self, *, protocol: str = "tcp") -> bool:
        proto = str(protocol or "").strip().lower()
        if self.out_range.status == SEMANTIC_STATUS_STRUCTURED_SUPPORTED:
            return True
        if proto == "tcp":
            return (
                self.send.status == SEMANTIC_STATUS_STRUCTURED_SUPPORTED
                or self.syndata.status == SEMANTIC_STATUS_STRUCTURED_SUPPORTED
            )
        return False

    def advanced_state_status(self, *, protocol: str = "tcp") -> str:
        proto = str(protocol or "").strip().lower()
        states = [self.out_range.status]
        if proto == "tcp":
            states.extend([self.send.status, self.syndata.status])

        present = [status for status in states if status != SEMANTIC_STATUS_ABSENT]
        if not present:
            return SEMANTIC_STATUS_ABSENT
        if any(status == SEMANTIC_STATUS_INVALID for status in present):
            return SEMANTIC_STATUS_INVALID
        if any(status == SEMANTIC_STATUS_RAW_ONLY_SUPPORTED for status in present):
            return SEMANTIC_STATUS_RAW_ONLY_SUPPORTED
        return SEMANTIC_STATUS_STRUCTURED_SUPPORTED


@dataclass
class _OutRangeOccurrence:
    token: str
    raw_value: str
    source: str
    status: str
    out_range: int | None = None
    out_range_mode: str = ""
    preserve_token_raw: bool = False


@dataclass
class _TokenSendAnalysis:
    state: SendState
    inline_out_range: list[_OutRangeOccurrence] = field(default_factory=list)


@dataclass
class _TokenSyndataAnalysis:
    state: SyndataState
    inline_out_range: list[_OutRangeOccurrence] = field(default_factory=list)


def _iter_tokens(text: str) -> list[str]:
    return [token.strip() for token in _TOKENS_RE.findall(str(text or "")) if token.strip()]


def _classify_out_range_value(raw_value: str) -> tuple[str, int | None, str]:
    value = str(raw_value or "").strip()
    if not value:
        return SEMANTIC_STATUS_INVALID, None, ""

    structured_match = _STRUCTURED_OUT_RANGE_RE.fullmatch(value)
    if structured_match:
        return (
            SEMANTIC_STATUS_STRUCTURED_SUPPORTED,
            int(structured_match.group(2)),
            str(structured_match.group(1) or "").lower(),
        )

    if _RAW_ONLY_OUT_RANGE_RE.fullmatch(value):
        return SEMANTIC_STATUS_RAW_ONLY_SUPPORTED, None, ""

    return SEMANTIC_STATUS_INVALID, None, ""


def _classify_out_range_values(
    values: list[tuple[str, str]],
    *,
    allow_structured_roundtrip: bool,
    token: str,
) -> list[_OutRangeOccurrence]:
    occurrences: list[_OutRangeOccurrence] = []

    if not values:
        return occurrences

    individual: list[_OutRangeOccurrence] = []
    for raw_value, source in values:
        status, out_range, out_range_mode = _classify_out_range_value(raw_value)
        individual.append(
            _OutRangeOccurrence(
                token=token,
                raw_value=str(raw_value or "").strip(),
                source=source,
                status=status,
                out_range=out_range,
                out_range_mode=out_range_mode,
            )
        )

    if len(individual) == 1:
        item = individual[0]
        if item.status == SEMANTIC_STATUS_STRUCTURED_SUPPORTED and not allow_structured_roundtrip:
            item.status = SEMANTIC_STATUS_RAW_ONLY_SUPPORTED
        item.preserve_token_raw = item.status != SEMANTIC_STATUS_STRUCTURED_SUPPORTED
        return [item]

    raw_values = {item.raw_value.lower() for item in individual}
    if any(item.status == SEMANTIC_STATUS_INVALID for item in individual):
        aggregate_status = SEMANTIC_STATUS_INVALID
    elif len(raw_values) == 1:
        aggregate_status = SEMANTIC_STATUS_RAW_ONLY_SUPPORTED
    else:
        aggregate_status = SEMANTIC_STATUS_INVALID

    for item in individual:
        item.status = aggregate_status
        item.out_range = None
        item.out_range_mode = ""
        item.preserve_token_raw = True

    return individual


def _build_out_range_state(occurrences: list[_OutRangeOccurrence]) -> OutRangeState:
    if not occurrences:
        return OutRangeState()

    if len(occurrences) == 1:
        item = occurrences[0]
        return OutRangeState(
            status=item.status,
            tokens=(item.token,),
            raw_value=item.raw_value,
            source=item.source,
            out_range=item.out_range,
            out_range_mode=item.out_range_mode,
            preserve_token_raw=item.preserve_token_raw,
        )

    if any(item.status == SEMANTIC_STATUS_INVALID for item in occurrences):
        status = SEMANTIC_STATUS_INVALID
    else:
        raw_values = {item.raw_value.lower() for item in occurrences}
        status = (
            SEMANTIC_STATUS_RAW_ONLY_SUPPORTED
            if len(raw_values) == 1
            else SEMANTIC_STATUS_INVALID
        )

    first = occurrences[0]
    return OutRangeState(
        status=status,
        tokens=tuple(item.token for item in occurrences),
        raw_value=first.raw_value,
        source=first.source if len({item.source for item in occurrences}) == 1 else "",
        out_range=None,
        out_range_mode="",
        preserve_token_raw=status != SEMANTIC_STATUS_STRUCTURED_SUPPORTED,
    )


def _merge_send_states(states: list[SendState]) -> SendState:
    present = [state for state in states if state.status != SEMANTIC_STATUS_ABSENT]
    if not present:
        return SendState()
    if len(present) == 1:
        return present[0]

    if any(state.status == SEMANTIC_STATUS_INVALID for state in present):
        status = SEMANTIC_STATUS_INVALID
    else:
        status = SEMANTIC_STATUS_RAW_ONLY_SUPPORTED

    return SendState(
        status=status,
        tokens=tuple(token for state in present for token in state.tokens),
        structured={},
        preserve_token_raw=True,
    )


def _merge_syndata_states(states: list[SyndataState]) -> SyndataState:
    present = [state for state in states if state.status != SEMANTIC_STATUS_ABSENT]
    if not present:
        return SyndataState()
    if len(present) == 1:
        return present[0]

    if any(state.status == SEMANTIC_STATUS_INVALID for state in present):
        status = SEMANTIC_STATUS_INVALID
    else:
        status = SEMANTIC_STATUS_RAW_ONLY_SUPPORTED

    return SyndataState(
        status=status,
        tokens=tuple(token for state in present for token in state.tokens),
        structured={},
        preserve_token_raw=True,
    )


def _parse_send_key_value(key: str, value: str) -> tuple[bool, str, Any]:
    key_l = str(key or "").strip().lower()
    value_s = str(value or "").strip()

    if key_l == "repeats":
        if not re.fullmatch(r"-?\d+", value_s):
            return False, "", None
        return True, "send_repeats", int(value_s)
    if key_l == "ttl":
        if not re.fullmatch(r"-?\d+", value_s):
            return False, "", None
        return True, "send_ip_ttl", int(value_s)
    if key_l == "ttl6":
        if not re.fullmatch(r"-?\d+", value_s):
            return False, "", None
        return True, "send_ip6_ttl", int(value_s)
    if key_l == "ip_id":
        if value_s == "":
            return False, "", None
        return True, "send_ip_id", value_s
    if key_l == "badsum":
        lowered = value_s.lower()
        if lowered not in {"true", "false"}:
            return False, "", None
        return True, "send_badsum", lowered == "true"

    return False, "", None


def _parse_syndata_key_value(key: str, value: str) -> tuple[bool, str, Any]:
    key_l = str(key or "").strip().lower()
    value_s = str(value or "").strip()

    if key_l == "blob":
        if value_s == "":
            return False, "", None
        return True, "blob", value_s
    if key_l == "tls_mod":
        if value_s == "":
            return False, "", None
        return True, "tls_mod", value_s
    if key_l == "ip_autottl":
        match = re.fullmatch(r"(-?\d+),(\d+)-(\d+)", value_s)
        if not match:
            return False, "", None
        return True, "ip_autottl", {
            "autottl_delta": int(match.group(1)),
            "autottl_min": int(match.group(2)),
            "autottl_max": int(match.group(3)),
        }
    if key_l == "tcp_flags_unset":
        if value_s == "":
            return False, "", None
        return True, "tcp_flags_unset", value_s

    return False, "", None


def _analyze_send_token(token: str) -> _TokenSendAnalysis:
    token_s = str(token or "").strip()
    token_l = token_s.lower()
    prefix = "--lua-desync=send"

    if token_l == prefix:
        return _TokenSendAnalysis(
            state=SendState(
                status=SEMANTIC_STATUS_RAW_ONLY_SUPPORTED,
                tokens=(token_s,),
                structured={},
                preserve_token_raw=True,
            )
        )

    if not token_l.startswith(prefix + ":"):
        return _TokenSendAnalysis(state=SendState())

    payload = token_s[len(prefix) + 1:]
    if not payload:
        return _TokenSendAnalysis(
            state=SendState(
                status=SEMANTIC_STATUS_INVALID,
                tokens=(token_s,),
                structured={},
                preserve_token_raw=True,
            )
        )

    inline_values: list[tuple[str, str]] = []
    parsed: dict[str, Any] = {"send_enabled": True}
    saw_unknown = False
    saw_invalid = False
    saw_duplicate = False
    seen_structured_keys: set[str] = set()

    for part in payload.split(":"):
        part_s = str(part or "").strip()
        if not part_s:
            saw_invalid = True
            continue

        if "=" not in part_s:
            saw_unknown = True
            continue

        key, _sep, value = part_s.partition("=")
        key_l = str(key or "").strip().lower()
        if key_l == "out_range":
            inline_values.append((value, "inline"))
            continue

        ok, target_key, parsed_value = _parse_send_key_value(key_l, value)
        if not ok:
            if key_l in {"repeats", "ttl", "ttl6", "ip_id", "badsum"}:
                saw_invalid = True
            else:
                saw_unknown = True
            continue

        if key_l in seen_structured_keys:
            saw_duplicate = True
        seen_structured_keys.add(key_l)

        if target_key == "send_badsum":
            parsed[target_key] = bool(parsed_value)
        elif target_key:
            parsed[target_key] = parsed_value

    if saw_invalid:
        base_status = SEMANTIC_STATUS_INVALID
    elif saw_unknown or saw_duplicate:
        base_status = SEMANTIC_STATUS_RAW_ONLY_SUPPORTED
    else:
        base_status = SEMANTIC_STATUS_STRUCTURED_SUPPORTED

    occurrences = _classify_out_range_values(
        inline_values,
        allow_structured_roundtrip=base_status == SEMANTIC_STATUS_STRUCTURED_SUPPORTED,
        token=token_s,
    )

    if occurrences:
        inline_statuses = {item.status for item in occurrences}
        if SEMANTIC_STATUS_INVALID in inline_statuses:
            base_status = SEMANTIC_STATUS_INVALID
        elif SEMANTIC_STATUS_RAW_ONLY_SUPPORTED in inline_statuses:
            base_status = SEMANTIC_STATUS_RAW_ONLY_SUPPORTED

    if base_status != SEMANTIC_STATUS_STRUCTURED_SUPPORTED:
        parsed = {}

    return _TokenSendAnalysis(
        state=SendState(
            status=base_status,
            tokens=(token_s,),
            structured=parsed,
            preserve_token_raw=base_status != SEMANTIC_STATUS_STRUCTURED_SUPPORTED,
        ),
        inline_out_range=occurrences,
    )


def _analyze_syndata_token(token: str) -> _TokenSyndataAnalysis:
    token_s = str(token or "").strip()
    token_l = token_s.lower()
    prefix = "--lua-desync=syndata"

    if token_l == prefix:
        return _TokenSyndataAnalysis(
            state=SyndataState(
                status=SEMANTIC_STATUS_RAW_ONLY_SUPPORTED,
                tokens=(token_s,),
                structured={},
                preserve_token_raw=True,
            )
        )

    if not token_l.startswith(prefix + ":"):
        return _TokenSyndataAnalysis(state=SyndataState())

    payload = token_s[len(prefix) + 1:]
    if not payload:
        return _TokenSyndataAnalysis(
            state=SyndataState(
                status=SEMANTIC_STATUS_INVALID,
                tokens=(token_s,),
                structured={},
                preserve_token_raw=True,
            )
        )

    inline_values: list[tuple[str, str]] = []
    parsed: dict[str, Any] = {"enabled": True}
    saw_unknown = False
    saw_invalid = False
    saw_duplicate = False
    saw_blob = False
    saw_autottl = False
    seen_structured_keys: set[str] = set()

    for part in payload.split(":"):
        part_s = str(part or "").strip()
        if not part_s:
            saw_invalid = True
            continue

        if "=" not in part_s:
            saw_unknown = True
            continue

        key, _sep, value = part_s.partition("=")
        key_l = str(key or "").strip().lower()
        if key_l == "out_range":
            inline_values.append((value, "inline"))
            continue

        ok, target_key, parsed_value = _parse_syndata_key_value(key_l, value)
        if not ok:
            if key_l in {"blob", "tls_mod", "ip_autottl", "tcp_flags_unset"}:
                saw_invalid = True
            else:
                saw_unknown = True
            continue

        if key_l in seen_structured_keys:
            saw_duplicate = True
        seen_structured_keys.add(key_l)

        if target_key == "blob":
            saw_blob = True
            parsed[target_key] = parsed_value
        elif target_key == "ip_autottl":
            saw_autottl = True
            parsed.update(parsed_value)
        elif target_key:
            parsed[target_key] = parsed_value

    if not saw_autottl:
        parsed["autottl_delta"] = 0

    if saw_invalid:
        base_status = SEMANTIC_STATUS_INVALID
    elif not saw_blob:
        base_status = SEMANTIC_STATUS_RAW_ONLY_SUPPORTED
    elif saw_unknown or saw_duplicate:
        base_status = SEMANTIC_STATUS_RAW_ONLY_SUPPORTED
    else:
        base_status = SEMANTIC_STATUS_STRUCTURED_SUPPORTED

    occurrences = _classify_out_range_values(
        inline_values,
        allow_structured_roundtrip=base_status == SEMANTIC_STATUS_STRUCTURED_SUPPORTED,
        token=token_s,
    )

    if occurrences:
        inline_statuses = {item.status for item in occurrences}
        if SEMANTIC_STATUS_INVALID in inline_statuses:
            base_status = SEMANTIC_STATUS_INVALID
        elif SEMANTIC_STATUS_RAW_ONLY_SUPPORTED in inline_statuses:
            base_status = SEMANTIC_STATUS_RAW_ONLY_SUPPORTED

    if base_status != SEMANTIC_STATUS_STRUCTURED_SUPPORTED:
        parsed = {}

    return _TokenSyndataAnalysis(
        state=SyndataState(
            status=base_status,
            tokens=(token_s,),
            structured=parsed,
            preserve_token_raw=base_status != SEMANTIC_STATUS_STRUCTURED_SUPPORTED,
        ),
        inline_out_range=occurrences,
    )


def _analyze_generic_out_range_token(token: str) -> list[_OutRangeOccurrence]:
    token_s = str(token or "").strip()
    token_l = token_s.lower()

    top_level_match = _TOP_LEVEL_OUT_RANGE_RE.fullmatch(token_s)
    if top_level_match:
        return _classify_out_range_values(
            [(top_level_match.group(1), "line")],
            allow_structured_roundtrip=True,
            token=token_s,
        )

    if token_l.startswith("--out-range="):
        return [
            _OutRangeOccurrence(
                token=token_s,
                raw_value="",
                source="line",
                status=SEMANTIC_STATUS_INVALID,
                out_range=None,
                out_range_mode="",
                preserve_token_raw=True,
            )
        ]

    inline_values = [(match.group(1), "inline") for match in _INLINE_OUT_RANGE_RE.finditer(token_s)]
    if inline_values:
        return _classify_out_range_values(
            inline_values,
            allow_structured_roundtrip=True,
            token=token_s,
        )

    return []


def analyze_block_semantics(block_text: str) -> BlockSemantics:
    tokens = _iter_tokens(block_text)

    send_states: list[SendState] = []
    syndata_states: list[SyndataState] = []
    out_range_occurrences: list[_OutRangeOccurrence] = []

    for token in tokens:
        send_analysis = _analyze_send_token(token)
        if send_analysis.state.status != SEMANTIC_STATUS_ABSENT:
            send_states.append(send_analysis.state)
            out_range_occurrences.extend(send_analysis.inline_out_range)
            continue

        syndata_analysis = _analyze_syndata_token(token)
        if syndata_analysis.state.status != SEMANTIC_STATUS_ABSENT:
            syndata_states.append(syndata_analysis.state)
            out_range_occurrences.extend(syndata_analysis.inline_out_range)
            continue

        out_range_occurrences.extend(_analyze_generic_out_range_token(token))

    return BlockSemantics(
        out_range=_build_out_range_state(out_range_occurrences),
        send=_merge_send_states(send_states),
        syndata=_merge_syndata_states(syndata_states),
    )


def has_explicit_out_range(block_text: str) -> bool:
    return analyze_block_semantics(block_text).has_explicit_out_range


def should_preserve_token_raw(token: str) -> bool:
    semantics = analyze_block_semantics(token)
    return semantics.should_preserve_any_token_raw


def extract_structured_out_range(block_text: str) -> dict[str, Any]:
    state = analyze_block_semantics(block_text).out_range
    if state.status != SEMANTIC_STATUS_STRUCTURED_SUPPORTED:
        return {}
    if state.out_range is None or not state.out_range_mode:
        return {}
    return {
        "out_range": state.out_range,
        "out_range_mode": state.out_range_mode,
    }


def extract_structured_send(block_text: str) -> dict[str, Any]:
    state = analyze_block_semantics(block_text).send
    if state.status != SEMANTIC_STATUS_STRUCTURED_SUPPORTED:
        return {"send_enabled": False}
    return dict(state.structured)


def extract_structured_syndata(block_text: str) -> dict[str, Any]:
    state = analyze_block_semantics(block_text).syndata
    if state.status != SEMANTIC_STATUS_STRUCTURED_SUPPORTED:
        return {"enabled": False}
    return dict(state.structured)


def extract_structured_block_overrides(block_text: str, *, protocol: str = "tcp") -> dict[str, Any]:
    semantics = analyze_block_semantics(block_text)
    proto = str(protocol or "").strip().lower()
    result: dict[str, Any] = {}

    if semantics.out_range.status == SEMANTIC_STATUS_STRUCTURED_SUPPORTED:
        result.update(extract_structured_out_range(block_text))

    if proto == "tcp":
        if semantics.syndata.status == SEMANTIC_STATUS_STRUCTURED_SUPPORTED:
            result.update(extract_structured_syndata(block_text))
        if semantics.send.status == SEMANTIC_STATUS_STRUCTURED_SUPPORTED:
            result.update(extract_structured_send(block_text))

    return result


def apply_structured_block_overrides_to_category(category: Any, block_text: str, *, protocol: str = "tcp") -> None:
    overrides = extract_structured_block_overrides(block_text, protocol=protocol)
    proto = str(protocol or "").strip().lower()

    if proto in ("udp", "quic", "l7", "raw"):
        settings = getattr(category, "syndata_udp")
        settings.out_range = int(overrides.get("out_range", 0) or 0)
        settings.out_range_mode = str(overrides.get("out_range_mode") or "n")
        return

    settings = getattr(category, "syndata_tcp")
    settings.out_range = int(overrides.get("out_range", 0) or 0)
    settings.out_range_mode = str(overrides.get("out_range_mode") or "n")

    if overrides.get("enabled"):
        settings.enabled = True
        settings.blob = overrides.get("blob", "none")
        settings.tls_mod = overrides.get("tls_mod", "none")
        settings.autottl_delta = overrides.get("autottl_delta", 0)
        settings.autottl_min = overrides.get("autottl_min", 3)
        settings.autottl_max = overrides.get("autottl_max", 20)
        settings.tcp_flags_unset = overrides.get("tcp_flags_unset", "none")
    else:
        settings.enabled = False

    if overrides.get("send_enabled"):
        settings.send_enabled = True
        settings.send_repeats = overrides.get("send_repeats", 2)
        settings.send_ip_ttl = overrides.get("send_ip_ttl", 0)
        settings.send_ip6_ttl = overrides.get("send_ip6_ttl", 0)
        settings.send_ip_id = overrides.get("send_ip_id", "")
        settings.send_badsum = overrides.get("send_badsum", False)
    else:
        settings.send_enabled = False


def reset_structured_advanced_state(category: Any) -> None:
    category.syndata_tcp.enabled = False
    category.syndata_tcp.send_enabled = False
    category.syndata_tcp.out_range = 0
    category.syndata_tcp.out_range_mode = "n"
    category.syndata_udp.out_range = 0
    category.syndata_udp.out_range_mode = "n"


def strip_structured_inline_out_range(token: str) -> str:
    semantics = analyze_block_semantics(token)
    state = semantics.out_range
    if state.status != SEMANTIC_STATUS_STRUCTURED_SUPPORTED:
        return str(token or "").strip()
    if state.source != "inline":
        return str(token or "").strip()
    return _INLINE_OUT_RANGE_RE.sub("", str(token or "").strip())
