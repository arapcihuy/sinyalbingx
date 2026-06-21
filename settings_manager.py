import json
import os
import logging

logger = logging.getLogger(__name__)

SETTINGS_FILE = "bot_settings.json"

def load_settings():
    """Load settings from JSON file."""
    default_settings = {
        "auto_entry": os.getenv("AUTO_ENTRY", "false").lower() == "true",
        "tp_mode": "tp1_only",  # Default aman buat scalping / small account
        "paper_mode": os.getenv("PAPER_MODE", "true").lower() == "true",
        "min_rr_ratio": 1.5,  # Minimal Risk:Reward ratio
        "max_slots": 0,  # 0 = tanpa batas posisi bersamaan
        "brain_enabled": True,  # 🧠 Brain engine aktif
        "trailing_enabled": True,  # Trailing SL aktif
        "liquidation_buffer_pct": 0.10,  # buffer aman dari liq
        "liquidation_mmr_fallback": 0.005,  # fallback maintenance margin rate
    }
    
    if not os.path.exists(SETTINGS_FILE):
        try:
            import order_manager
            order_manager._atomic_write_json(SETTINGS_FILE, default_settings)
        except Exception:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(default_settings, f, indent=4)
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
    """Save settings to JSON file atomicly."""
    try:
        import order_manager
        order_manager._atomic_write_json(SETTINGS_FILE, settings)
        return True
    except Exception as e:
        logger.error(f"Gagal save settings atomic: {e}")
        # Fallback
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(settings, f, indent=4)
            return True
        except:
            return False
