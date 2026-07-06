"""Expose tool discovery and sector-learning helpers for the news pipeline."""

from backend.pipeline.fetching.sources import flag_weak_sectors, update_sector_terms
from backend.pipeline.tool_discovery.queries import search_url
from backend.pipeline.tool_discovery.tools_aware import build_tool_queries, load_monthly_tool_records

__all__ = ["build_tool_queries", "flag_weak_sectors", "load_monthly_tool_records", "search_url", "update_sector_terms"]


