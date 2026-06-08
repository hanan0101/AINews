"""
Clean public entrypoint for the AI update pipeline.

The server imports from this package. The implementation is split into small
modules while reusing the proven legacy functions during the migration.
"""

from .pipeline import run_pipeline, run_single_supporting_pipeline, run_single_update_pipeline, start_background_daemon

__all__ = ["run_pipeline", "run_single_update_pipeline", "run_single_supporting_pipeline", "start_background_daemon"]
