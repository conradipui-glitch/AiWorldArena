"""AI Society Simulation Platform headless kernel."""

from ai_society.simulation.engine import SimulationEngine
from ai_society.simulation.generation import generate_world

__all__ = ["SimulationEngine", "generate_world"]
__version__ = "0.1.0"
