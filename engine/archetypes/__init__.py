"""Archetype registry — maps archetype names to behavior classes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.archetypes.caller import CallerBehavior
from engine.archetypes.clicker import ClickerBehavior
from engine.archetypes.drone import DroneBehavior
from engine.archetypes.swarm import SwarmBehavior
from engine.archetypes.responder import ResponderBehavior

if TYPE_CHECKING:
    from engine.agent import Agent
    from engine.species import Species
    from engine.archetypes.base import Behavior

ARCHETYPES = {
    "caller": CallerBehavior,
    "clicker": ClickerBehavior,
    "drone": DroneBehavior,
    "swarm": SwarmBehavior,
    "responder": ResponderBehavior,
}


def create_behavior(agent: Agent, species: Species) -> Behavior:
    """Create a behavior instance for the given agent and species."""
    cls = ARCHETYPES[species.archetype]
    return cls(agent, species)
