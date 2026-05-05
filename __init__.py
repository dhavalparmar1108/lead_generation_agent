"""
SalesBot - Modularized sales chatbot with LangGraph & MCP
"""

__version__ = "1.0.0"
__author__ = "SalesBot Team"

from models import LeadData, AgentState
from agent import process_message, get_agent

__all__ = [
    "LeadData",
    "AgentState",
    "process_message",
    "get_agent",
]
