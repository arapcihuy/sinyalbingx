import json
import os
import logging

logger = logging.getLogger(__name__)

SETTINGS_FILE = "bot_settings.json"

def load_settings():
    """Load settings from JSON file."""
    default_settings = {
        "auto_entry": os.getenv("AUTO_ENTRY", "false").lower() == "true",
        "tp_mode": "tp1_only" # Pilihan: tp1_only, multi_tp
    }
    
    if not os.path.exists(SETTINGS_FILE):
        return default_settings
        
    try:
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
            # Merge with defaults to ensure all keys exist
            return {**default_settings, **data}
    except Exception as e:
        logger.error(f"Gagal load settings: {e}")
        return default_settings

def save_settings(settings):
    """Save settings to JSON file."""
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Gagal save settings: {e}")
        return False
