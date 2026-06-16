import os
import sys
import json
import logging
import requests
import time
from datetime import datetime, timezone
from typing import Tuple, List, Optional
from dotenv import load_dotenv

try:
    from ai_trading.decision_logger import log_decision
except Exception:
    log_decision = None

try:
    from ai_trading.utils.news_fetcher import get_news_summary
except Exception:
    get_news_summary = None

try:
    from ai_trading.utils.volatility_helper import calculate_atr
except Exception:
    calculate_atr = None

# Konfigurasi Logging untuk gemini_filter
logger = logging.getLogger("gemini_filter")
if not logger.handlers:
    # Handler default jika modul ini dijalankan secara mandiri
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] (%(name)s) %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Setup path proyek agar bisa mengimpor bingx_client secara relatif
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
load_dotenv(os.path.join(project_root, ".env"))

if project_root not in sys.path:
    sys.path.append(project_root)

try:
    import bingx_client
except ImportError as e:
    logger.error(f"Gagal mengimpor bingx_client: {e}")
    bingx_client = None


def _audit_decision(
    pair: str,
    action: str,
    price: float,
    sl: float,
    tp1: float,
    tp2: float,
    source: str,
    approved: bool,
    reason: str,
    latency_ms: Optional[int] = None,
    raw_error: Optional[str] = None,
) -> None:
    if not log_decision:
        return
    try:
        log_decision(
            pair=pair,
            action=action,
            price=price,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            source=source,
            approved=approved,
            reason=reason,
            latency_ms=latency_ms,
            raw_error=raw_error,
        )
    except Exception as audit_err:
        logger.warning(f"Gagal menulis audit log AI: {audit_err}")


def validate_signal(
    pair: str,
    action: str,
    price: float,
    sl: float,
    tp1: float,
    tp2: float,
    mock_klines: Optional[List[dict]] = None
) -> Tuple[bool, str, dict]:
    """
    Memvalidasi sinyal perdagangan menggunakan Google Gemini 1.5/2.5/3.5 Flash REST API berdasarkan tren chart 15-menit terakhir.
    
    Args:
        pair (str): Nama pair dagang (contoh: BTC-USDT).
        action (str): Aksi trading (BUY/LONG atau SELL/SHORT).
        price (float): Harga entri.
        sl (float): Harga Stop Loss.
        tp1 (float): Harga Take Profit 1.
        tp2 (float): Harga Take Profit 2.
        mock_klines (Optional[List[dict]]): Data K-Line tiruan untuk pengujian. Jika tidak disediakan, 
                                            data akan diambil langsung dari BingX API.
        
    Returns:
        Tuple[bool, str, dict]: (approved, reason, suggested_params)
            - approved: True jika disetujui oleh AI atau jika terjadi kegagalan API/ketiadaan kunci (fallback), 
                        False jika ditolak.
            - reason: Alasan penolakan atau persetujuan secara teknis.
            - suggested_params: Kamus berisi saran TP/SL dan leverage dinamis dari AI.
    """
    # 1. Periksa ketersediaan 9Router atau GEMINI_API_KEY langsung
    ninerouter_url = os.getenv("NINEROUTER_URL", "http://127.0.0.1:20128/v1")
    ninerouter_key = os.getenv("NINEROUTER_KEY", "")
    api_key = os.getenv("GEMINI_API_KEY")
    
    # Deteksi apakah 9Router aktif dengan ping ringan jika URL bernilai localhost
    use_ninerouter = False
    if "127.0.0.1" in ninerouter_url or "localhost" in ninerouter_url:
        try:
            res = requests.get(f"{ninerouter_url.rstrip('/')}/models", timeout=2)
            if res.status_code == 200:
                use_ninerouter = True
                logger.info("📡 Menggunakan local 9Router sebagai AI gateway.")
        except Exception:
            pass
    elif ninerouter_url and not api_key:
        # Jika dideploy ke cloud dengan NINEROUTER_URL eksternal
        use_ninerouter = True
        logger.info(f"📡 Menggunakan remote 9Router gateway: {ninerouter_url}")

    # 2. Tentukan atau ambil data K-Line
    klines = mock_klines
    if klines is None:
        real_api_failed = False
        if bingx_client:
            try:
                logger.info(f"Mengambil 10 K-Line 15-menit terakhir untuk {pair} dari BingX...")
                res = bingx_client._request(
                    'GET',
                    '/openApi/swap/v3/quote/klines',
                    {'symbol': pair, 'interval': '15m', 'limit': 10}
                )
                if isinstance(res, dict) and res.get("code") == 0:
                    klines = res.get("data", [])
                    logger.info(f"Berhasil mengambil {len(klines)} K-Line dari BingX.")
                else:
                    logger.warning(f"⚠️ API BingX mengembalikan respon error atau tidak sukses: {res}.")
                    real_api_failed = True
            except Exception as e:
                logger.warning(f"⚠️ Gagal mengambil K-Line dari BingX API: {e}.")
                real_api_failed = True
        else:
            logger.warning("⚠️ bingx_client tidak tersedia atau gagal dimuat.")
            real_api_failed = True

        # Jika API K-Line bursa offline/gagal, kembalikan fallback auto-approved langsung
        if real_api_failed or not klines:
            reason = "BingX K-Line API down, skipping AI filter validation"
            logger.warning("⚠️ BingX K-Line API offline atau gagal didapatkan. Mengaktifkan fallback auto-approved langsung.")
            _audit_decision(pair, action, price, sl, tp1, tp2, "fallback_klines", True, reason)
            return True, reason, {}

    # 3. Fallback jika data K-Line kosong atau gagal didapatkan (untuk mock klines)
    if not klines:
        logger.info("Membuat data K-Line mock netral sebagai fallback karena data real tidak tersedia.")
        now_ms = int(time.time() * 1000)
        klines = []
        for i in range(10):
            klines.append({
                "open": str(price),
                "close": str(price),
                "high": str(price),
                "low": str(price),
                "volume": "0.0",
                "time": now_ms - (9 - i) * 15 * 60 * 1000
            })

    # Urutkan klines berdasarkan waktu terlama ke terbaru (kronologis)
    try:
        klines = sorted(klines, key=lambda x: int(x.get("time", 0)))
    except Exception as e:
        logger.warning(f"Gagal mengurutkan K-Line secara kronologis: {e}. Menggunakan urutan default.")

    # Format data K-Line untuk prompt
    formatted_klines_list = []
    for idx, k in enumerate(klines):
        try:
            k_time = int(k.get("time", 0))
            utc_time = datetime.fromtimestamp(k_time / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        except Exception:
            utc_time = f"Candle {idx + 1}"
        
        formatted_klines_list.append(
            f"- {utc_time} | Open: {k.get('open')} | High: {k.get('high')} | Low: {k.get('low')} | Close: {k.get('close')} | Vol: {k.get('volume')}"
        )
    klines_formatted = "\n".join(formatted_klines_list)
    
    # Hitung ATR (Backlog #3)
    atr_value = 0.0
    if calculate_atr:
        atr_value = calculate_atr(klines)

    # Ambil sentimen berita (Backlog #1)
    news_context = ""
    if get_news_summary:
        news_context = get_news_summary()

    # 4. Konstruksi prompt untuk Gemini
    prompt = f"""
Anda adalah sistem filter AI perdagangan kuantitatif yang bertugas mengevaluasi kelayakan sinyal perdagangan.
Analisis data pasar, sentimen berita, dan volatilitas berikut untuk menentukan apakah tren saat ini mendukung aksi yang diajukan.

Detail Sinyal Perdagangan:
- Pair (Aset): {pair}
- Aksi (Tindakan): {action} (BUY/LONG atau SELL/SHORT)
- Harga Entry (Masuk): {price}
- Stop Loss (SL): {sl}
- Take Profit 1 (TP1): {tp1}
- Take Profit 2 (TP2): {tp2}

Statistik Volatilitas:
- ATR (14): {atr_value:.4f}

Data K-Line 15-Menit Terakhir (urut kronologis):
{klines_formatted}

Sentimen Berita Pasar Terbaru:
{news_context}

Tugas Anda:
1. Evaluasi aksi {action} berdasarkan tren harga, sentimen berita, dan ATR.
2. Jika ada berita FUD besar yang bertentangan dengan aksi, pertimbangkan untuk menolak (`approved`: false).
3. Berdasarkan nilai ATR, sarankan apakah SL/TP saat ini sudah optimal atau berikan saran level harga baru yang lebih dinamis.
4. Sarankan nilai Leverage aman (1x - 20x) berdasarkan volatilitas (ATR tinggi = Leverage rendah).
5. Tentukan keputusan akhir: setuju (`approved`: true) atau tolak (`approved`: false).
6. Berikan alasan teknis + fundamental ringkas dalam bahasa Indonesia (`reason`).
7. Sertakan saran parameter dinamis dalam objek JSON Anda.

Kembalikan respon dalam format JSON mentah dengan kunci:
- 'approved': boolean
- 'reason': string
- 'suggested_tp1': float (opsional)
- 'suggested_tp2': float (opsional)
- 'suggested_sl': float (opsional)
- 'suggested_leverage': int (opsional, range 1-20)
"""

    # 5. Eksekusi permintaan ke AI (9Router / Gemini Direct)
    if use_ninerouter:
        url = f"{ninerouter_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if ninerouter_key:
            headers["Authorization"] = f"Bearer {ninerouter_key}"
            
        model_name = os.getenv("GEMINI_MODEL", "gemini")
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "response_format": {"type": "json_object"},
            "stream": False
        }
        
        try:
            logger.info(f"Mengirim permintaan validasi sinyal {action} {pair} ke 9Router API (model: {model_name})...")
            ai_t0 = time.time()
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            latency_ms = int((time.time() - ai_t0) * 1000)
            res_json = response.json()
            
            if "choices" not in res_json:
                logger.warning(f"Respon 9Router tidak mengandung 'choices': {res_json}")
                raise ValueError("Format respon 9Router tidak valid (missing choices).")
                
            content = res_json["choices"][0]["message"]["content"].strip()
            
            # Bersihkan markdown code block jika ada
            cleaned_content = content
            if cleaned_content.startswith("```"):
                cleaned_content = cleaned_content.strip("`").strip()
                if cleaned_content.startswith("json"):
                    cleaned_content = cleaned_content[4:].strip()
            
            try:
                decision = json.loads(cleaned_content)
            except json.JSONDecodeError as json_err:
                logger.warning(f"Content bukan JSON valid bahkan setelah dibersihkan: {content}")
                approved = False
                if '"approved": true' in content.lower() or '"approved":true' in content.lower():
                    approved = True
                reason = content[:200]
                decision = {"approved": approved, "reason": reason}
                
            approved = bool(decision.get("approved", True))
            reason = str(decision.get("reason", "Approved by 9Router"))
            
            suggested = {
                "suggested_tp1": decision.get("suggested_tp1"),
                "suggested_tp2": decision.get("suggested_tp2"),
                "suggested_sl": decision.get("suggested_sl"),
                "suggested_leverage": decision.get("suggested_leverage")
            }
            
            logger.info(f"Keputusan AI (9Router): Approved={approved} | Reason={reason} | Suggested={suggested}")
            _audit_decision(pair, action, price, sl, tp1, tp2, "9router", approved, reason, latency_ms)
            return approved, reason, suggested
        except Exception as e:
            logger.warning(f"⚠️ Gagal memproses via 9Router: {e}. Mencoba direct fallback...")
            
    # Fallback ke direct Gemini API jika API Key tersedia
    if api_key:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "approved": {"type": "BOOLEAN"},
                        "reason": {"type": "STRING"},
                        "suggested_tp1": {"type": "NUMBER"},
                        "suggested_tp2": {"type": "NUMBER"},
                        "suggested_sl": {"type": "NUMBER"},
                        "suggested_leverage": {"type": "INTEGER"}
                    },
                    "required": ["approved", "reason"]
                }
            }
        }
        
        try:
            logger.info(f"Mengirim permintaan validasi sinyal {action} {pair} ke Gemini API langsung...")
            ai_t0 = time.time()
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            latency_ms = int((time.time() - ai_t0) * 1000)
            response_json = response.json()
            
            candidates = response_json.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    text_data = parts[0].get("text", "").strip()
                    decision = json.loads(text_data)
                    approved = bool(decision.get("approved", True))
                    reason = str(decision.get("reason", "Approved by direct Gemini"))
                    
                    suggested = {
                        "suggested_tp1": decision.get("suggested_tp1"),
                        "suggested_tp2": decision.get("suggested_tp2"),
                        "suggested_sl": decision.get("suggested_sl"),
                        "suggested_leverage": decision.get("suggested_leverage")
                    }
                    
                    logger.info(f"Keputusan AI (Direct): Approved={approved} | Reason={reason} | Suggested={suggested}")
                    _audit_decision(pair, action, price, sl, tp1, tp2, "gemini_direct", approved, reason, latency_ms)
                    return approved, reason, suggested
        except Exception as e:
            logger.warning(f"⚠️ Gagal menghubungi Gemini API langsung: {e}")

    logger.warning("⚠️ Semua jalur AI (9Router & Direct) gagal atau tidak memiliki credentials. Mengaktifkan fallback persetujuan otomatis.")
    reason = "API Key missing or API failed, approved as fallback"
    _audit_decision(pair, action, price, sl, tp1, tp2, "fallback_all_failed", True, reason)
    return True, reason, {}
