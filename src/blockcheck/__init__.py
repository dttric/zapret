"""BlockCheck — network blocking analysis and DPI detection.

Public API:
    BlockcheckRunner  — orchestrator (sync, call from QThread)
    RunMode           — run modes: QUICK, FULL, DPI_ONLY
    BlockcheckReport  — result container
    TargetResult      — per-target results
    SingleTestResult  — individual test result
    TestStatus        — OK, FAIL, TIMEOUT, UNSUPPORTED, ERROR
    DPIClassification — detected DPI type

    StrategyScanner       — brute-force strategy prober
    StrategyScanReport    — scan result container
    StrategyProbeResult   — per-strategy probe result
    StrategyScanCallback  — callback protocol for scan progress
"""

from blockcheck.models import (
    BlockcheckReport,
    DPIClassification,
    DNSIntegrityResult,
    SingleTestResult,
    TargetResult,
    TestStatus,
    TestType,
)
from blockcheck.runner import BlockcheckCallback, BlockcheckRunner, RunMode
from blockcheck.scan_models import StrategyProbeResult, StrategyScanReport
from blockcheck.strategy_scanner import StrategyScanCallback, StrategyScanner

__all__ = [
    "BlockcheckCallback",
    "BlockcheckReport",
    "BlockcheckRunner",
    "DPIClassification",
    "DNSIntegrityResult",
    "RunMode",
    "SingleTestResult",
    "StrategyProbeResult",
    "StrategyScanCallback",
    "StrategyScanReport",
    "StrategyScanner",
    "TargetResult",
    "TestStatus",
    "TestType",
]
