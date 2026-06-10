import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_ssl")

token = "8610835184:AAFHpzr3OH0UGh8NvlVwl64RBsfgn_8Fu7Y"
chat_id = "7809584261"
url = f"https://api.telegram.org/bot{token}/getMe"

logger.info("Test 1: Standard requests")
try:
    import requests
    r = requests.get(url, timeout=10)
    logger.info(f"Test 1 Success! status={r.status_code}, json={r.json()}")
except Exception as e:
    logger.error(f"Test 1 Failed: {e}", exc_info=True)

logger.info("Test 2: urllib3 forcing TLSv1.2")
try:
    import urllib3
    import ssl
    
    class TLSv1_2Adapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            context = ssl.create_default_context()
            context.options |= ssl.OP_NO_TLSv1_3  # Disable TLS 1.3
            kwargs['ssl_context'] = context
            return super().init_poolmanager(*args, **kwargs)
            
    s = requests.Session()
    s.mount('https://', TLSv1_2Adapter())
    r = s.get(url, timeout=10)
    logger.info(f"Test 2 Success! status={r.status_code}, json={r.json()}")
except Exception as e:
    logger.error(f"Test 2 Failed: {e}", exc_info=True)

logger.info("Test 3: curl_cffi requests")
try:
    from curl_cffi import requests as crequests
    r = crequests.get(url, timeout=10)
    logger.info(f"Test 3 Success! status={r.status_code}, json={r.json()}")
except Exception as e:
    logger.error(f"Test 3 Failed: {e}", exc_info=True)
