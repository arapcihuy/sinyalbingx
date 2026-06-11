import logging

logger = logging.getLogger(__name__)

# State Global Terkunci secara default saat startup
_PAPER_MODE = True
_USE_DEMO = True
_SYSTEM_STATUS = "INITIALIZING"

def get_trading_mode():
    """Mengambil status mode trading saat ini di memori."""
    global _PAPER_MODE, _USE_DEMO
    return {
        "paper_mode": _PAPER_MODE,
        "use_demo": _USE_DEMO,
        "system_status": _SYSTEM_STATUS
    }

def promote_to_live():
    """Mengalihkan bot secara dinamis ke perdagangan Uang Asli (Live)."""
    global _PAPER_MODE, _USE_DEMO, _SYSTEM_STATUS
    _PAPER_MODE = False
    _USE_DEMO = False
    _SYSTEM_STATUS = "LIVE"
    logger.info("🟢 SYSTEM PROMOTED: Bot resmi beralih ke perdagangan Uang Asli (Live).")

def demote_to_safe_mode(reason=""):
    """Mengunci bot secara dinamis ke mode simulasi aman (Paper/Demo VST)."""
    global _PAPER_MODE, _USE_DEMO, _SYSTEM_STATUS
    _PAPER_MODE = True
    _USE_DEMO = True
    _SYSTEM_STATUS = f"SAFE_MODE: {reason}"
    logger.warning(f"🔴 SYSTEM DEMOTED: Bot dikunci di mode simulasi aman. Alasan: {reason}")
