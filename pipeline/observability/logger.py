"""Structured logging configuration using structlog."""
import logging
import sys
import structlog
from typing import Any


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structlog for structured JSON logging throughout the pipeline.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str, **initial_context: Any) -> structlog.stdlib.BoundLogger:
    """Get a structured logger with initial context bindings.
    
    Args:
        name: Logger name (typically module name)
        **initial_context: Key-value pairs to bind to all log messages
        
    Returns:
        Configured structlog bound logger
    """
    return structlog.get_logger(name, **initial_context)


def bind_pipeline_context(run_id: str, source_key: str) -> None:
    """Bind pipeline run context to all subsequent log messages in this context.
    
    Args:
        run_id: Unique pipeline run identifier
        source_key: Source configuration key (e.g., 'sbi_mf')
    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        pipeline_run_id=run_id,
        source_key=source_key,
    )
