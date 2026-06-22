"""Source configuration loader - URLs and types stored as data, not code."""
import os
from pathlib import Path
from typing import Optional
import yaml
from observability.logger import get_logger

logger = get_logger(__name__)

CONFIG_DIR = Path(__file__).parent


def load_sources(config_path: Optional[str] = None) -> list[dict]:
    """Load source configurations from YAML file.
    
    Args:
        config_path: Optional path to sources.yaml. Defaults to config/sources.yaml
        
    Returns:
        List of source configuration dictionaries
    """
    path = Path(config_path) if config_path else CONFIG_DIR / "sources.yaml"
    
    if not path.exists():
        logger.error("sources_config_not_found", path=str(path))
        raise FileNotFoundError(f"Source config not found: {path}")
    
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    
    sources = data.get("sources", [])
    logger.info("sources_loaded", count=len(sources), path=str(path))
    return sources


def load_scheme_master(config_path: Optional[str] = None) -> dict:
    """Load known scheme names for fuzzy matching during classification.
    
    Args:
        config_path: Optional path to scheme_master.yaml
        
    Returns:
        Dictionary mapping AMC keys to their known schemes
    """
    path = Path(config_path) if config_path else CONFIG_DIR / "scheme_master.yaml"
    
    if not path.exists():
        logger.warning("scheme_master_not_found", path=str(path))
        return {}
    
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    
    logger.info("scheme_master_loaded", amc_count=len(data.get("amcs", {})))
    return data
