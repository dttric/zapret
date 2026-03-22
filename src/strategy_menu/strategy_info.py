"""
Unified strategy information dataclass for BAT and JSON strategies.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_menu.search_query import SearchQuery


@dataclass
class StrategyInfo:
    """
    Unified structure for all strategy types (BAT and JSON).

    Provides a common interface for strategy metadata regardless of source format.
    """

    # Required fields
    id: str
    name: str
    source: str  # "bat" | "json_tcp" | "json_quic" | "json_udp" etc.

    # Optional metadata
    description: str = ""
    author: str = ""
    version: str = ""
    label: str = ""  # "recommended", "experimental", "deprecated", "game"
    comment: str = ""
    args: str = ""  # Command line arguments
    file_path: str = ""  # Path to source file

    # Technical details
    protocols: List[str] = field(default_factory=list)  # ["TCP", "UDP"]
    ports: List[int] = field(default_factory=list)  # [80, 443]
    techniques: List[str] = field(default_factory=list)  # ["fake", "split", "disorder"]

    # Flags
    uses_hostlist: bool = False
    uses_ipset: bool = False

    # User data
    rating: int = 0  # Rating 0-5
    is_favorite: bool = False
    last_used: Optional[datetime] = None

    def matches_text(self, text: str) -> bool:
        """
        Check if strategy matches search text.

        Searches in: name, description, args, author, comment.

        Args:
            text: Search text (case-insensitive)

        Returns:
            True if any field contains the search text
        """
        if not text:
            return True

        text_lower = text.lower()

        searchable_fields = [
            self.name,
            self.description,
            self.args,
            self.author,
            self.comment,
        ]

        return any(
            text_lower in field_value.lower()
            for field_value in searchable_fields
            if field_value
        )

    def matches_query(self, query: 'SearchQuery') -> bool:
        """
        Check if strategy matches a full search query.

        Args:
            query: SearchQuery object with filter criteria

        Returns:
            True if strategy matches all query criteria
        """
        # Text search
        if query.text and not self.matches_text(query.text):
            return False

        # Source filter
        if query.sources and self.source not in query.sources:
            return False

        # Label filter (case-insensitive)
        if query.labels:
            self_label = self.label.lower() if self.label else ""
            query_labels = [l.lower() for l in query.labels]
            if self_label not in query_labels:
                return False

        # Protocol filter
        if query.protocols:
            if not self.protocols:
                return False
            if not any(p in self.protocols for p in query.protocols):
                return False

        # Port filter
        if query.ports:
            if not self.ports:
                return False
            if not any(p in self.ports for p in query.ports):
                return False

        # Technique filter (case-insensitive)
        if query.techniques:
            if not self.techniques:
                return False
            self_techniques = [t.lower() for t in self.techniques]
            query_techniques = [t.lower() for t in query.techniques]
            if not any(t in self_techniques for t in query_techniques):
                return False

        # Rating filter
        if query.min_rating is not None and self.rating < query.min_rating:
            return False

        # Favorites filter
        if query.favorites_only and not self.is_favorite:
            return False

        # Hostlist filter
        if query.uses_hostlist is not None and self.uses_hostlist != query.uses_hostlist:
            return False

        # Ipset filter
        if query.uses_ipset is not None and self.uses_ipset != query.uses_ipset:
            return False

        return True

    @classmethod
    def from_bat_metadata(cls, metadata: dict) -> 'StrategyInfo':
        """
        Create StrategyInfo from BAT file metadata.

        Expected metadata keys (from REM comments):
            - NAME: Strategy name
            - VERSION: Version string
            - DESCRIPTION: Description text
            - LABEL: recommended|deprecated|experimental|game
            - AUTHOR: Author name
            - file_path: Path to BAT file
            - args: Command line arguments (extracted from BAT)

        Args:
            metadata: Dictionary with BAT metadata

        Returns:
            StrategyInfo instance
        """
        name = metadata.get('NAME', metadata.get('name', 'Unknown'))
        file_path = metadata.get('file_path', '')

        # Generate ID from filename or name
        strategy_id = metadata.get('id', '')
        if not strategy_id and file_path:
            import os
            strategy_id = os.path.splitext(os.path.basename(file_path))[0]
        if not strategy_id:
            strategy_id = name.lower().replace(' ', '_')

        # Extract args from BAT content if available
        args = metadata.get('args', '')

        # Detect protocols and ports from args
        protocols = []
        ports = []
        techniques = []
        uses_hostlist = False
        uses_ipset = False

        if args:
            args_lower = args.lower()

            # Detect protocols
            if '--wf-tcp' in args_lower or 'tcp' in args_lower:
                protocols.append('TCP')
            if '--wf-udp' in args_lower or 'udp' in args_lower:
                protocols.append('UDP')

            # Detect common ports
            if '80' in args:
                ports.append(80)
            if '443' in args:
                ports.append(443)

            # Detect techniques
            if 'fake' in args_lower:
                techniques.append('fake')
            if 'split' in args_lower:
                techniques.append('split')
            if 'disorder' in args_lower:
                techniques.append('disorder')
            if 'oob' in args_lower:
                techniques.append('oob')
            if 'tamper' in args_lower:
                techniques.append('tamper')

            # Detect hostlist/ipset usage
            uses_hostlist = '--hostlist' in args_lower or 'hostlist' in args_lower
            uses_ipset = '--ipset' in args_lower or 'ipset' in args_lower

        return cls(
            id=strategy_id,
            name=name,
            source='bat',
            description=metadata.get('DESCRIPTION', metadata.get('description', '')),
            author=metadata.get('AUTHOR', metadata.get('author', '')),
            version=metadata.get('VERSION', metadata.get('version', '')),
            label=metadata.get('LABEL', metadata.get('label', '')).lower(),
            comment=metadata.get('COMMENT', metadata.get('comment', '')),
            args=args,
            file_path=file_path,
            protocols=protocols,
            ports=ports,
            techniques=techniques,
            uses_hostlist=uses_hostlist,
            uses_ipset=uses_ipset,
            rating=metadata.get('rating', 0),
            is_favorite=metadata.get('is_favorite', False),
            last_used=metadata.get('last_used'),
        )

    @classmethod
    def from_json_strategy(cls, data: dict, category_key: str) -> 'StrategyInfo':
        """
        Create StrategyInfo from JSON strategy data.

        Args:
            data: Dictionary with JSON strategy data
            category_key: Category key (e.g., "tcp", "quic", "udp")

        Returns:
            StrategyInfo instance
        """
        name = data.get('name', data.get('id', 'Unknown'))
        strategy_id = data.get('id', name.lower().replace(' ', '_'))

        # Determine source from category
        source = f"json_{category_key}" if category_key else "json"

        # Extract protocols from category or data
        protocols = data.get('protocols', [])
        if not protocols:
            category_lower = category_key.lower() if category_key else ''
            if 'tcp' in category_lower:
                protocols = ['TCP']
            elif 'quic' in category_lower or 'udp' in category_lower:
                protocols = ['UDP']

        # Extract ports
        ports = data.get('ports', [])
        if not ports:
            # Try to infer from other fields
            if 'quic' in category_key.lower() if category_key else False:
                ports = [443]

        # Extract techniques from args or dedicated field
        techniques = data.get('techniques', [])
        args = data.get('args', '')

        if not techniques and args:
            args_lower = args.lower()
            if 'fake' in args_lower:
                techniques.append('fake')
            if 'split' in args_lower:
                techniques.append('split')
            if 'disorder' in args_lower:
                techniques.append('disorder')
            if 'oob' in args_lower:
                techniques.append('oob')
            if 'tamper' in args_lower:
                techniques.append('tamper')

        # Detect hostlist/ipset
        uses_hostlist = data.get('uses_hostlist', False)
        uses_ipset = data.get('uses_ipset', False)

        if not uses_hostlist and args:
            uses_hostlist = '--hostlist' in args.lower() or 'hostlist' in args.lower()
        if not uses_ipset and args:
            uses_ipset = '--ipset' in args.lower() or 'ipset' in args.lower()

        return cls(
            id=strategy_id,
            name=name,
            source=source,
            description=data.get('description', ''),
            author=data.get('author', ''),
            version=data.get('version', ''),
            label=data.get('label', '').lower(),
            comment=data.get('comment', ''),
            args=args,
            file_path=data.get('file_path', ''),
            protocols=protocols if isinstance(protocols, list) else [protocols],
            ports=ports if isinstance(ports, list) else [ports],
            techniques=techniques,
            uses_hostlist=uses_hostlist,
            uses_ipset=uses_ipset,
            rating=data.get('rating', 0),
            is_favorite=data.get('is_favorite', False),
            last_used=data.get('last_used'),
        )

    def to_dict(self) -> dict:
        """
        Convert StrategyInfo to dictionary.

        Returns:
            Dictionary representation of the strategy
        """
        return {
            'id': self.id,
            'name': self.name,
            'source': self.source,
            'description': self.description,
            'author': self.author,
            'version': self.version,
            'label': self.label,
            'comment': self.comment,
            'args': self.args,
            'file_path': self.file_path,
            'protocols': self.protocols,
            'ports': self.ports,
            'techniques': self.techniques,
            'uses_hostlist': self.uses_hostlist,
            'uses_ipset': self.uses_ipset,
            'rating': self.rating,
            'is_favorite': self.is_favorite,
            'last_used': self.last_used.isoformat() if self.last_used else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'StrategyInfo':
        """
        Create StrategyInfo from dictionary.

        Args:
            data: Dictionary with strategy data

        Returns:
            StrategyInfo instance
        """
        last_used = data.get('last_used')
        if isinstance(last_used, str):
            last_used = datetime.fromisoformat(last_used)

        return cls(
            id=data.get('id', ''),
            name=data.get('name', ''),
            source=data.get('source', ''),
            description=data.get('description', ''),
            author=data.get('author', ''),
            version=data.get('version', ''),
            label=data.get('label', ''),
            comment=data.get('comment', ''),
            args=data.get('args', ''),
            file_path=data.get('file_path', ''),
            protocols=data.get('protocols', []),
            ports=data.get('ports', []),
            techniques=data.get('techniques', []),
            uses_hostlist=data.get('uses_hostlist', False),
            uses_ipset=data.get('uses_ipset', False),
            rating=data.get('rating', 0),
            is_favorite=data.get('is_favorite', False),
            last_used=last_used,
        )

    def __str__(self) -> str:
        """String representation."""
        return f"StrategyInfo(id={self.id!r}, name={self.name!r}, source={self.source!r})"

    def __repr__(self) -> str:
        """Detailed representation."""
        return (
            f"StrategyInfo(id={self.id!r}, name={self.name!r}, source={self.source!r}, "
            f"label={self.label!r}, protocols={self.protocols}, ports={self.ports})"
        )
