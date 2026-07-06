const http = require('http');
const https = require('https');
const url = require('url');

const PORT = process.env.PORT || 5001;
const TG_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '';
const TG_CHAT_ID = process.env.TELEGRAM_CHAT_ID || '';

function tgSend(text) {
  if (!TG_TOKEN) return;
  const data = JSON.stringify({ chat_id: TG_CHAT_ID, text, parse_mode: 'Markdown' });
  const opts = {
    hostname: 'api.telegram.org',
    path: `/bot${TG_TOKEN}/sendMessage`,
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
    timeout: 5000
  };
  const req = https.request(opts, (res) => { res.resume(); });
  req.on('error', () => {});
  req.write(data);
  req.end();
}

function parseJSON(body) {
  try { return JSON.parse(body); } catch { return {}; }
}

const server = http.createServer((req, res) => {
  const parsedUrl = url.parse(req.url, true);
  const pathname = (parsedUrl.pathname || '').replace(/\/+$/, '') || '/';

  // Health check
  if (req.method === 'GET' && (pathname === '/health' || pathname === '/')) {
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('OK');
    return;
  }

  // TradingView webhook
  if (req.method === 'POST' && pathname === '/tradingview') {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      const data = parseJSON(body);
      const isZignaly = data.key && data.exchange;

      let signal, pair, price, sl, tp1, tp2;

      if (isZignaly) {
        pair = (data.pair || '').toUpperCase().replace('.P', '');
        if (pair.includes('USDT') && !pair.endsWith('-USDT')) pair = pair.replace('USDT', '-USDT');
        const entrySide = (data.entrySide || '').toUpperCase();
        signal = entrySide === 'LONG' ? 'BUY' : 'SELL';
        price = parseFloat(data.entryLimitPrice) || 0;
        sl = parseFloat(data.stopLossPrice) || 0;
        tp1 = parseFloat(data.takeProfitPrice1) || 0;
        tp2 = parseFloat(data.takeProfitPrice2) || 0;
      } else {
        signal = (data.signal || data.action || '').toUpperCase();
        pair = (data.symbol || '').toUpperCase().replace('.P', '');
        if (!pair.includes('-USDT')) pair += '-USDT';
        price = parseFloat(data.price) || 0;
        sl = parseFloat(data.sl) || 0;
        tp1 = parseFloat(data.tp1) || 0;
        tp2 = parseFloat(data.tp2) || 0;
      }

      if (!['BUY', 'SELL', 'LONG', 'SHORT'].includes(signal)) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'invalid signal' }));
        return;
      }

      if (!['BTC-USDT', 'ETH-USDT'].includes(pair)) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'ignored', reason: 'symbol not allowed' }));
        return;
      }

      tgSend(`⚡ SINYAL DITERIMA\n${signal} ${pair} @ ${price}`);

      // Respond immediately to prevent TradingView timeout
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'accepted', message: 'Signal received and processing asynchronously' }));

      // Lazy import order_manager (Python child process) executed in background
      const { exec } = require('child_process');
      const payload = JSON.stringify({ symbol: pair, action: signal, price, sl, tp1, tp2, tp3: 0, tp4: 0 });
      exec(`python3 -c "import sys,json; sys.path.insert(0,'.'); import order_manager; r=order_manager.execute_signal(json.loads('${payload}')); print(json.dumps(r))"`,
        { timeout: 30000 },
        (err, stdout) => {
          let result = {};
          try { result = JSON.parse(stdout); } catch {}
          const status = result.status || (err ? 'error' : 'unknown');
          tgSend(`✅ DIEKSEKUSI\n${pair} ${signal}\nSL: ${sl}\nTP1: ${tp1}\nResult: ${status}`);
        }
      );
    });
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Listening on :${PORT}`);
});
