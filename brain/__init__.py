"""Agent local Poro: llama.cpp, context structurat și acțiuni semantice."""

from .agent import BrainAgent
from .llm import LocalLLM

__all__ = ("BrainAgent", "LocalLLM")
