"""Read-only research artifacts built around verified experiment bundles."""

from ai_society.research.comparison import compare_bundles
from ai_society.research.models import ResearchArtifactKind, RunMark
from ai_society.research.service import ResearchService

__all__ = [
    "ResearchArtifactKind",
    "ResearchService",
    "RunMark",
    "compare_bundles",
]
