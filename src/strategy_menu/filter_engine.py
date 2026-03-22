"""
Strategy filtering engine with query parsing and sorting.

Provides SearchQuery dataclass for filter criteria and StrategyFilterEngine
for filtering, sorting, and grouping strategies.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import re

from strategy_menu.strategy_info import StrategyInfo


@dataclass
class SearchQuery:
    """
    Query object for filtering strategies.

    Supports text search and various filter criteria.
    """

    # Text search
    text: str = ""

    # Filter criteria
    labels: Optional[List[str]] = None  # Filter by label (None = all)
    protocols: Optional[List[str]] = None  # TCP, UDP, QUIC
    ports: Optional[List[int]] = None  # Specific ports
    techniques: Optional[List[str]] = None  # fake, split, disorder

    # Feature flags
    uses_hostlist: Optional[bool] = None
    uses_ipset: Optional[bool] = None

    # User preferences
    favorites_only: bool = False
    min_rating: Optional[int] = None

    # Source filter
    sources: Optional[List[str]] = None  # bat, json_tcp, json_quic

    # Exclusions (labels to exclude)
    excluded_labels: List[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Check if query has no filters applied."""
        return (
            not self.text
            and self.labels is None
            and self.protocols is None
            and self.ports is None
            and self.techniques is None
            and self.uses_hostlist is None
            and self.uses_ipset is None
            and not self.favorites_only
            and self.min_rating is None
            and self.sources is None
            and not self.excluded_labels
        )


class StrategyFilterEngine:
    """
    Engine for filtering, sorting, and grouping strategies.

    Provides query parsing, filtering by multiple criteria,
    sorting by various keys, and grouping by label.
    """

    # Label priority order (higher index = higher priority)
    LABEL_PRIORITY = {
        "deprecated": 0,
        "": 1,  # unlabeled
        "unlabeled": 1,
        "experimental": 2,
        "game": 2,
        "recommended": 3,
    }

    # Known filter prefixes
    FILTER_PREFIXES = {
        "label:": "labels",
        "protocol:": "protocols",
        "port:": "ports",
        "technique:": "techniques",
        "source:": "sources",
        "rating:": "min_rating",
    }

    def parse_query(self, text: str) -> SearchQuery:
        """
        Parse search text into SearchQuery object.

        Supports special syntax:
            - Simple text: searches everywhere
            - label:recommended - filter by label
            - port:443 - filter by port
            - technique:fake - filter by technique
            - protocol:TCP - filter by protocol
            - source:bat - filter by source
            - rating:3 - minimum rating
            - -deprecated - exclude label
            - favorites - show only favorites
            - hostlist - has hostlist
            - ipset - has ipset

        Args:
            text: Search text with optional filter syntax

        Returns:
            SearchQuery object with parsed criteria
        """
        query = SearchQuery()

        if not text:
            return query

        # Temporary storage for parsed values
        labels: List[str] = []
        protocols: List[str] = []
        ports: List[int] = []
        techniques: List[str] = []
        sources: List[str] = []
        excluded_labels: List[str] = []
        text_parts: List[str] = []

        # Split by whitespace but preserve quoted strings
        tokens = self._tokenize(text)

        for token in tokens:
            token_lower = token.lower()

            # Check for exclusion prefix (e.g., -deprecated)
            if token.startswith("-") and len(token) > 1:
                excluded = token[1:].lower()
                excluded_labels.append(excluded)
                continue

            # Check for filter prefixes
            matched = False
            for prefix, attr_name in self.FILTER_PREFIXES.items():
                if token_lower.startswith(prefix):
                    value = token[len(prefix):]
                    if value:
                        matched = True
                        self._add_filter_value(
                            attr_name,
                            value,
                            labels,
                            protocols,
                            ports,
                            techniques,
                            sources,
                            query,
                        )
                    break

            if matched:
                continue

            # Special keywords
            if token_lower == "favorites" or token_lower == "favourite":
                query.favorites_only = True
                continue

            if token_lower == "hostlist":
                query.uses_hostlist = True
                continue

            if token_lower == "ipset":
                query.uses_ipset = True
                continue

            # Regular text search
            text_parts.append(token)

        # Apply collected values to query
        if text_parts:
            query.text = " ".join(text_parts)

        if labels:
            query.labels = labels

        if protocols:
            query.protocols = [p.upper() for p in protocols]

        if ports:
            query.ports = ports

        if techniques:
            query.techniques = [t.lower() for t in techniques]

        if sources:
            query.sources = sources

        if excluded_labels:
            query.excluded_labels = excluded_labels

        return query

    def _tokenize(self, text: str) -> List[str]:
        """
        Split text into tokens, preserving quoted strings.

        Args:
            text: Input text

        Returns:
            List of tokens
        """
        tokens = []
        # Match quoted strings or non-whitespace sequences
        pattern = r'"([^"]+)"|\'([^\']+)\'|(\S+)'
        for match in re.finditer(pattern, text):
            # Get the matched group (quoted or unquoted)
            token = match.group(1) or match.group(2) or match.group(3)
            if token:
                tokens.append(token)
        return tokens

    def _add_filter_value(
        self,
        attr_name: str,
        value: str,
        labels: List[str],
        protocols: List[str],
        ports: List[int],
        techniques: List[str],
        sources: List[str],
        query: SearchQuery,
    ) -> None:
        """Add a filter value to the appropriate list or query attribute."""
        if attr_name == "labels":
            labels.append(value.lower())
        elif attr_name == "protocols":
            protocols.append(value.upper())
        elif attr_name == "ports":
            try:
                ports.append(int(value))
            except ValueError:
                pass  # Ignore invalid port
        elif attr_name == "techniques":
            techniques.append(value.lower())
        elif attr_name == "sources":
            sources.append(value.lower())
        elif attr_name == "min_rating":
            try:
                query.min_rating = int(value)
            except ValueError:
                pass  # Ignore invalid rating

    def filter_strategies(
        self, strategies: List[StrategyInfo], query: SearchQuery
    ) -> List[StrategyInfo]:
        """
        Filter strategies by query criteria.

        Uses strategy.matches_query() for filtering and additionally
        applies excluded_labels filter.

        Args:
            strategies: List of strategies to filter
            query: SearchQuery with filter criteria

        Returns:
            Filtered list of strategies
        """
        if query.is_empty():
            return list(strategies)

        result = []
        for strategy in strategies:
            # Check matches_query first
            if not strategy.matches_query(query):
                continue

            # Check excluded labels
            if query.excluded_labels:
                strategy_label = strategy.label.lower() if strategy.label else ""
                if strategy_label in query.excluded_labels:
                    continue
                # Also check if "unlabeled" is excluded and strategy has no label
                if not strategy_label and "unlabeled" in query.excluded_labels:
                    continue

            result.append(strategy)

        return result

    # IDs for "disabled" strategy that should always be first
    DISABLED_STRATEGY_IDS = {"none", "disabled"}
    # Full names (exact match) for disabled strategy
    DISABLED_STRATEGY_NAMES = {"отключено", "выключено", "disabled", "none"}

    def sort_strategies(
        self,
        strategies: List[StrategyInfo],
        sort_key: str,
        reverse: bool = False,
    ) -> List[StrategyInfo]:
        """
        Sort strategies by specified key.

        The "disabled" strategy (id="none" or name containing "Отключено")
        is always placed first, regardless of sort order.

        Args:
            strategies: List of strategies to sort
            sort_key: Sort key - "default", "name", "rating", "label"
            reverse: Reverse sort order

        Returns:
            Sorted list of strategies
        """
        if not strategies:
            return []

        strategies_copy = list(strategies)

        if sort_key == "name":
            strategies_copy.sort(key=lambda s: s.name.lower(), reverse=reverse)
        elif sort_key == "rating":
            strategies_copy.sort(key=lambda s: s.rating, reverse=not reverse)
        elif sort_key == "label":
            # Sort by label priority: recommended > experimental > unlabeled > deprecated
            strategies_copy.sort(
                key=lambda s: self.LABEL_PRIORITY.get(
                    s.label.lower() if s.label else "", 1
                ),
                reverse=not reverse,
            )
        elif sort_key == "default":
            # Default: preserve original order from JSON/source (no sorting)
            # Just return a copy without any sorting applied
            pass
        else:
            # Unknown sort key, return as-is
            pass

        # Move "disabled" strategy to the beginning (always first)
        strategies_copy = self._move_disabled_to_front(strategies_copy)

        return strategies_copy

    def _is_disabled_strategy(self, strategy: StrategyInfo) -> bool:
        """
        Check if strategy is the "disabled" option.

        Args:
            strategy: Strategy to check

        Returns:
            True if this is the disabled/none strategy
        """
        # Check by ID (exact match)
        if strategy.id and strategy.id.lower() in self.DISABLED_STRATEGY_IDS:
            return True

        # Check by name (exact match, not substring!)
        name_lower = strategy.name.lower().strip() if strategy.name else ""
        if name_lower in self.DISABLED_STRATEGY_NAMES:
            return True

        return False

    def _move_disabled_to_front(
        self, strategies: List[StrategyInfo]
    ) -> List[StrategyInfo]:
        """
        Move disabled strategy to the front of the list.

        Args:
            strategies: List of strategies

        Returns:
            List with disabled strategy first (if present)
        """
        disabled = None
        others = []

        for strategy in strategies:
            if disabled is None and self._is_disabled_strategy(strategy):
                disabled = strategy
            else:
                others.append(strategy)

        if disabled:
            return [disabled] + others
        return others

    def group_by_label(
        self, strategies: List[StrategyInfo]
    ) -> Dict[str, List[StrategyInfo]]:
        """
        Group strategies by their label.

        Args:
            strategies: List of strategies to group

        Returns:
            Dictionary with label keys and strategy lists.
            Keys: "recommended", "experimental", "deprecated", "game", "unlabeled"
        """
        groups: Dict[str, List[StrategyInfo]] = {
            "recommended": [],
            "experimental": [],
            "deprecated": [],
            "game": [],
            "unlabeled": [],
        }

        for strategy in strategies:
            label = strategy.label.lower() if strategy.label else ""

            if label in groups:
                groups[label].append(strategy)
            else:
                # Unknown label goes to unlabeled
                groups["unlabeled"].append(strategy)

        return groups

    def get_available_labels(
        self, strategies: List[StrategyInfo]
    ) -> List[str]:
        """
        Get list of labels present in strategies.

        Args:
            strategies: List of strategies

        Returns:
            List of unique labels found
        """
        labels = set()
        for strategy in strategies:
            label = strategy.label.lower() if strategy.label else "unlabeled"
            labels.add(label)
        return sorted(labels)

    def get_available_protocols(
        self, strategies: List[StrategyInfo]
    ) -> List[str]:
        """
        Get list of protocols present in strategies.

        Args:
            strategies: List of strategies

        Returns:
            List of unique protocols found
        """
        protocols = set()
        for strategy in strategies:
            protocols.update(strategy.protocols)
        return sorted(protocols)

    def get_available_techniques(
        self, strategies: List[StrategyInfo]
    ) -> List[str]:
        """
        Get list of techniques present in strategies.

        Args:
            strategies: List of strategies

        Returns:
            List of unique techniques found
        """
        techniques = set()
        for strategy in strategies:
            techniques.update(strategy.techniques)
        return sorted(techniques)
