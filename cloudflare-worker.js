/**
 * TRADENTIX PRO → BingX Bridge V2
 * Cloudflare Worker — GRATIS, gak perlu VPS
 * 
 * FITUR:
 * ✅ Dynamic sizing — otomatis sesuaikan sama saldo futures
 * ✅ Auto leverage — aman, gak over-leverage
 * ✅ Trailing SL — SL ikut naik kalo harga udah profit
 * ✅ Paper mode — testing aman
 * 
 * Cara deploy:
 * 1. Buka https://dash.cloudflare.com → Workers & Pages
 * 2. Create Worker → copas code ini → Deploy
 * 3. Dapet URL: https://namamu.workers.dev
 * 4. Di TradingView alert: set Webhook URL ke URL itu
 * 
 * Mode PAPER: default true — aman buat testing
 * Ubah PAPER_MODE = false kalo mau real trading
 * 
 * UNTUK TRAILING SL LANJUTAN:
 * Worker ini support cron trigger. Setup Cron Triggers di Cloudflare:
 * Settings → Triggers → Cron: every 1 minute (setiap 1 menit)
 * Worker bakal auto-update trailing SL untuk posisi aktif.
 */

// ⚙️ KONFIGURASI
const CONFIG = {
  BINGX_API_KEY:        'YOUR_BINGX_API_KEY',
  BINGX_SECRET_KEY:     'YOUR_BINGX_SECRET_KEY',
  WEBHOOK_SECRET:       'YOUR_WEBHOOK_SECRET',
  PAPER_MODE:           true,          // true = testing
  RISK_PER_TRADE:       2,             // % saldo per trade (1-5%)
  MAX_LEVERAGE:         10,            // maksimal leverage
  TRAIL_ACTIVATE_PCT:   1.0,           // trail aktif setelah profit X%
  TRAIL_OFFSET_ATR:     1.5,           // jarak trailing dari harga (ATR)
};

// ====== KV Namespace binding (untuk tracking posisi) ======
// Di Cloudflare dashboard: Workers → KV → Create namespace "POSITIONS"
// Bind ke worker dengan variable name "POSITIONS"
// let POSITIONS;

export default {
  async fetch(request, env) {
    // Support Cron Trigger (Cloudflare Cron Triggers)
    const url = new URL(request.url);
    if (url.pathname === '/__cron' || request.method === 'CRON') {
      return await handleCron(env);
    }

    if (request.method === 'OPTIONS') {
      return new Response('OK', { headers: cors() });
    }

    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405, headers: cors() });
    }

    try {
      const data = await request.json();
      console.log('[INCOMING]', JSON.stringify(data));

      if (data.secret !== CONFIG.WEBHOOK_SECRET) {
        return new Response('Unauthorized', { status: 401, headers: cors() });
      }

      // Handle CLOSE signal
      if (data.action === 'CLOSE') {
        const result = await closePosition(data, env);
        return jsonResponse(result);
      }

      const result = await handleSignal(data, env);
      return jsonResponse(result);

    } catch (err) {
      console.error('[ERROR]', err);
      return jsonResponse({ error: err.message }, 500);
    }
  },
};

// ====== CRON: Update trailing SL untuk semua posisi aktif ======
async function handleCron(env) {
  if (CONFIG.PAPER_MODE) return jsonResponse({ status: 'paper_mode_skipped' });

  try {
    // Get all open positions
    const positions = await apiCall('/openApi/swap/v2/user/positions', {});
    const openPos = positions?.data?.filter(p => parseFloat(p.positionAmt) !== 0) || [];

    for (const pos of openPos) {
      const symbol = pos.symbol;
      const entryPrice = parseFloat(pos.entryPrice);
      const markPrice = parseFloat(pos.markPrice);
      const isLong = pos.positionSide === 'LONG';
      const posAmt = parseFloat(pos.positionAmt);
      const atr = pos.atr || 0;

      // Check if position is in profit enough to activate trailing
      const profitPct = isLong 
        ? ((markPrice - entryPrice) / entryPrice) * 100
        : ((entryPrice - markPrice) / entryPrice) * 100;

      if (profitPct >= CONFIG.TRAIL_ACTIVATE_PCT) {
        // Calculate trailing SL price
        const trailOffset = atr * CONFIG.TRAIL_OFFSET_ATR || entryPrice * (CONFIG.TRAIL_ACTIVATE_PCT / 100);
        const newSl = isLong ? markPrice - trailOffset : markPrice + trailOffset;

        // Only update if new SL is better than current
        const currentSl = parseFloat(pos.stopLoss || 0);
        const shouldUpdate = isLong 
          ? (newSl > currentSl)
          : (newSl < currentSl);

        if (shouldUpdate && newSl > 0) {
          console.log(`[TRAIL] ${symbol}: SL ${currentSl} → ${newSl.toFixed(4)} (profit: ${profitPct.toFixed(2)}%)`);

          await apiCall('/openApi/swap/v2/trade/order', {
            symbol,
            side: isLong ? 'SELL' : 'BUY',
            positionSide: pos.positionSide,
            type: 'STOP_MARKET',
            quantity: posAmt.toFixed(6),
            stopPrice: newSl.toFixed(4),
            price: newSl.toFixed(4),
          });
        }
      }
    }

    return jsonResponse({ status: 'trailing_updated', positions: openPos.length });
  } catch (err) {
    console.error('[CRON ERROR]', err);
    return jsonResponse({ error: err.message });
  }
}

// ====== HANDLE SIGNAL ======
async function handleSignal(data, env) {
  const symbol = cleanSymbol(data.symbol);
  const isBuy = data.action === 'BUY';
  const side = isBuy ? 'BUY' : 'SELL';
  const posSide = isBuy ? 'LONG' : 'SHORT';

  // ── Dynamic sizing: ambil saldo futures ──
  let balance = CONFIG.POSITION_SIZE_USDT; // fallback
  let leverage = CONFIG.MAX_LEVERAGE;

  if (!CONFIG.PAPER_MODE) {
    try {
      const accInfo = await apiCall('/openApi/swap/v2/user/balance', {});
      balance = parseFloat(accInfo?.data?.balance?.availableBalance || 0);

      // Auto leverage: limit by volatility
      const markPrice = parseFloat(data.price);
      const slPct = data.sl ? Math.abs(parseFloat(data.sl) - markPrice) / markPrice * 100 : 1;
      const safeLev = Math.floor(1 / (slPct / 100) * (CONFIG.RISK_PER_TRADE / 100));
      leverage = Math.min(CONFIG.MAX_LEVERAGE, Math.max(1, safeLev));
      console.log(`[BALANCE] ${balance} USDT | Auto Lev: ${leverage}x`);
    } catch (e) {
      console.warn('[BALANCE FAIL] pakai default', e.message);
    }
  }

  // ── Hitung quantity ──
  const positionSize = balance * (CONFIG.RISK_PER_TRADE / 100) * leverage;
  const qty = positionSize / parseFloat(data.price);

  if (CONFIG.PAPER_MODE) {
    console.log(`[PAPER] ${side} ${symbol} | Size: ${positionSize.toFixed(2)} USD | Lev: ${leverage}x | Qty: ${qty.toFixed(6)}`);
    return {
      status: 'paper',
      action: data.action,
      symbol,
      price: data.price,
      qty: qty.toFixed(6),
      leverage,
      positionSize: positionSize.toFixed(2),
      balance: balance.toFixed(2),
    };
  }

  // ====== REAL EXECUTION ======
  try {
    // 1. Set leverage
    await apiCall('/openApi/swap/v2/trade/leverage', {
      symbol, leverage, side: posSide,
    });

    // 2. Market order
    const order = await apiCall('/openApi/swap/v2/trade/order', {
      symbol, side, positionSide: posSide,
      type: 'MARKET', quantity: qty.toFixed(6),
    });
    const orderId = order?.data?.orderId;
    if (!orderId) throw new Error('Order failed');

    // 3. Stop Loss
    if (data.sl) {
      await apiCall('/openApi/swap/v2/trade/order', {
        symbol, side: isBuy ? 'SELL' : 'BUY', positionSide: posSide,
        type: 'STOP_MARKET', quantity: qty.toFixed(6),
        stopPrice: parseFloat(data.sl).toFixed(4),
        price: parseFloat(data.sl).toFixed(4),
      });
    }

    // 4. Take Profit (level 1)
    if (data.tp1) {
      await apiCall('/openApi/swap/v2/trade/order', {
        symbol, side: isBuy ? 'SELL' : 'BUY', positionSide: posSide,
        type: 'TAKE_PROFIT_MARKET', quantity: qty.toFixed(6),
        stopPrice: parseFloat(data.tp1).toFixed(4),
        price: parseFloat(data.tp1).toFixed(4),
      });
    }

    // 5. Simpan posisi ke KV untuk trailing cron (kalo ada)
    if (typeof env?.POSITIONS?.put !== 'undefined') {
      const posData = {
        symbol, side, posSide, entry: data.price,
        sl: data.sl, tp1: data.tp1, qty: qty.toFixed(6),
        leverage, time: Date.now(),
      };
      await env.POSITIONS.put(symbol, JSON.stringify(posData), { expirationTtl: 86400 });
    }

    return {
      status: 'executed',
      action: data.action, symbol, orderId,
      qty: qty.toFixed(6), leverage,
      entry: data.price, sl: data.sl, tp1: data.tp1,
      balanceUsed: positionSize.toFixed(2),
    };

  } catch (err) {
    console.error('[BINGX ERROR]', err);
    throw err;
  }
}

// ====== CLOSE POSITION ======
async function closePosition(data, env) {
  const symbol = cleanSymbol(data.symbol);
  if (CONFIG.PAPER_MODE) {
    return { status: 'paper_closed', symbol };
  }

  await apiCall('/openApi/swap/v2/trade/closeAllPositions', { symbol });
  if (typeof env?.POSITIONS?.delete !== 'undefined') {
    await env.POSITIONS.delete(symbol);
  }
  return { status: 'closed', symbol };
}

// ====== CORS ======
function cors() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...cors(), 'Content-Type': 'application/json' },
  });
}

function cleanSymbol(sym) {
  return sym.replace('.P', '').replace('-', '').trim();
}

// ====== BINGX API ======
async function apiCall(path, params) {
  const timestamp = Date.now();
  const queryObj = { ...params, timestamp };
  const queryStr = Object.entries(queryObj)
    .map(([k, v]) => `${k}=${v}`)
    .join('&');

  const signature = await hmacSHA256(queryStr, CONFIG.BINGX_SECRET_KEY);
  const url = `https://open-api.bingx.com${path}`;
  const body = `${queryStr}&signature=${signature}`;

  console.log(`[BINGX] ${path}`);

  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'X-BX-APIKEY': CONFIG.BINGX_API_KEY,
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body,
  });

  const result = await resp.json();
  if (result.code && result.code !== 0) {
    throw new Error(`BingX ${result.code}: ${result.msg || JSON.stringify(result)}`);
  }
  return result;
}

async function hmacSHA256(message, secret) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw', encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false, ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, encoder.encode(message));
  return [...new Uint8Array(sig)].map(b => b.toString(16).padStart(2, '0')).join('');
}
