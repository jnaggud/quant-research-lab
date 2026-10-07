#!/usr/bin/env node
import CDP from '../tradingview-mcp/node_modules/chrome-remote-interface/index.js';
import { writeFileSync } from 'fs';

const args = parseArgs(process.argv.slice(2));
const host = args.host || process.env.TRADINGVIEW_CDP_HOST || '127.0.0.1';
const port = Number(args.port || process.env.TRADINGVIEW_CDP_PORT || 9223);
const targetId = args['target-id'] || '087vOT';
const targetName = args['target-name'] || '';
const outPath = args.out || `reports/tv_strategy_robust_${Date.now()}.json`;
const maxTrades = Number(args['max-trades'] || 600);
const tradeChunk = Number(args['trade-chunk'] || 100);
const maxOrders = Number(args['max-orders'] || 80);
const orderChunk = Number(args['order-chunk'] || 40);
const retries = Number(args.retries || 6);
const timeoutMs = Number(args.timeout || 7000);

const checkpoint = {
  success: false,
  generated_at: new Date().toISOString(),
  cdp: { host, port, target_id: targetId, target_name: targetName },
  phases: [],
};

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) out[key] = true;
    else out[key] = argv[++i];
  }
  return out;
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function save() {
  writeFileSync(outPath, `${JSON.stringify(checkpoint, null, 2)}\n`);
}

async function fetchJson(path) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`http://${host}:${port}${path}`, { signal: controller.signal });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

async function findTarget() {
  const targets = await fetchJson('/json/list');
  return targets.find(t => t.type === 'page' && /tradingview\.com\/chart/i.test(t.url))
    || targets.find(t => t.type === 'page' && /tradingview/i.test(t.url))
    || null;
}

async function withClient(label, fn) {
  let lastError;
  for (let attempt = 1; attempt <= retries; attempt++) {
    let client;
    try {
      const target = await findTarget();
      if (!target) throw new Error('No TradingView chart target found');
      client = await CDP({ host, port, target: target.id });
      await client.Runtime.enable();
      const result = await fn(client, target);
      checkpoint.phases.push({ label, attempt, success: true });
      save();
      return result;
    } catch (error) {
      lastError = error;
      checkpoint.phases.push({ label, attempt, success: false, error: String(error.message || error) });
      save();
      await sleep(Math.min(1000 * attempt, 5000));
    } finally {
      if (client) {
        try { await client.close(); } catch {}
      }
    }
  }
  throw new Error(`${label} failed after ${retries} attempts: ${lastError?.message || lastError}`);
}

async function evaluate(client, expression, awaitPromise = false) {
  const result = await client.Runtime.evaluate({
    expression,
    returnByValue: true,
    awaitPromise,
    timeout: timeoutMs,
  });
  if (result.exceptionDetails) {
    const msg = result.exceptionDetails.exception?.description
      || result.exceptionDetails.text
      || 'Unknown JS evaluation error';
    throw new Error(msg);
  }
  return result.result?.value;
}

function strategyPrelude(extra = '') {
  return `
    (function() {
      function safe(fn, fallback) { try { return fn(); } catch(e) { return fallback; } }
      function resolve(v) {
        if (typeof v === 'function') v = v();
        if (v && typeof v.value === 'function') v = v.value();
        return v;
      }
      function primitiveObject(obj, maxKeys) {
        var out = {};
        if (!obj || typeof obj !== 'object') return out;
        Object.keys(obj).slice(0, maxKeys || 200).forEach(function(k) {
          var v = obj[k];
          if (v === null || v === undefined || typeof v === 'function') return;
          if (typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean') out[k] = v;
          else if (Array.isArray(v)) out[k] = {type: 'array', length: v.length};
          else if (typeof v === 'object') {
            var child = {};
            Object.keys(v).slice(0, 60).forEach(function(ck) {
              var cv = v[ck];
              if (cv === null || cv === undefined || typeof cv === 'function') return;
              if (typeof cv === 'number' || typeof cv === 'string' || typeof cv === 'boolean') child[ck] = cv;
              else if (Array.isArray(cv)) child[ck] = {type: 'array', length: cv.length};
            });
            out[k] = child;
          }
        });
        return out;
      }
      function sourceName(s) {
        var meta = safe(function(){ return s.metaInfo ? s.metaInfo() : null; }, null);
        return {
          id: safe(function(){ return s.id ? String(s.id()) : String(s._id || ''); }, ''),
          name: meta ? (meta.description || meta.shortDescription || '') : safe(function(){ return s.name ? String(s.name()) : ''; }, ''),
          title: safe(function(){ return s.title ? String(s.title()) : ''; }, ''),
          is_price_study: meta ? meta.is_price_study : null
        };
      }
      var chart = window.TradingViewApi._activeChartWidgetWV.value()._chartWidget;
      var model = chart.model().model();
      var sources = model.dataSources();
      var wantedId = ${JSON.stringify(targetId)};
      var wantedName = ${JSON.stringify(targetName)};
      var candidates = [];
      for (var i = 0; i < sources.length; i++) {
        var s = sources[i];
        var info = sourceName(s);
        if (info.id === wantedId || (wantedName && (info.name.indexOf(wantedName) !== -1 || info.title.indexOf(wantedName) !== -1))) {
          candidates.push({index: i, source: s, info: info});
        }
      }
      if (!candidates.length) {
        for (var j = 0; j < sources.length; j++) {
          var ss = sources[j];
          var ii = sourceName(ss);
          if (ii.is_price_study === false && (ss.reportData || ss.performance || ss.ordersData)) {
            candidates.push({index: j, source: ss, info: ii});
            break;
          }
        }
      }
      if (!candidates.length) return {success: false, error: 'Strategy source not found', source_count: sources.length};
      var c = candidates[0];
      var strat = c.source;
      ${extra}
    })()
  `;
}

async function main() {
  save();

  checkpoint.health = await withClient('health', async client => {
    return evaluate(client, '({href: location.href, title: document.title, readyState: document.readyState})');
  });

  checkpoint.source = await withClient('source', async client => {
    return evaluate(client, strategyPrelude(`
      return {
        success: true,
        index: c.index,
        source: c.info,
        has_reportData: !!strat.reportData,
        has_performance: !!strat.performance,
        has_ordersData: !!strat.ordersData,
        has_equityData: !!strat.equityData
      };
    `));
  });

  checkpoint.metrics = await withClient('metrics', async client => {
    return evaluate(client, strategyPrelude(`
      var report = null;
      if (strat.reportData) report = resolve(strat.reportData.bind(strat));
      var perf = null;
      if (strat.performance) perf = resolve(strat.performance.bind(strat));
      return {
        success: true,
        reportData: primitiveObject(report, 260),
        performance: primitiveObject(perf, 260),
        report_keys: report && typeof report === 'object' ? Object.keys(report).slice(0, 260) : [],
        performance_keys: perf && typeof perf === 'object' ? Object.keys(perf).slice(0, 260) : []
      };
    `));
  });

  checkpoint.closed_trades_summary = await withClient('closed-trades-summary', async client => {
    return evaluate(client, strategyPrelude(`
      var report = null;
      if (strat.reportData) report = resolve(strat.reportData.bind(strat));
      var trades = report && Array.isArray(report.trades) ? report.trades : null;
      if (!trades) return {success: false, error: 'reportData.trades returned non-array'};
      function row(o) { return primitiveObject(o, 180); }
      return {
        success: true,
        count: trades.length,
        first: trades.slice(0, 5).map(row),
        last: trades.slice(Math.max(0, trades.length - 5)).map(row)
      };
    `));
  });

  const totalClosedTrades = Math.min(maxTrades, checkpoint.closed_trades_summary?.count || 0);
  checkpoint.closed_trades = [];
  for (let offset = 0; offset < totalClosedTrades; offset += tradeChunk) {
    const limit = Math.min(tradeChunk, totalClosedTrades - offset);
    const page = await withClient(`closed-trades-${offset}-${offset + limit}`, async client => {
      return evaluate(client, strategyPrelude(`
        var report = null;
        if (strat.reportData) report = resolve(strat.reportData.bind(strat));
        var trades = report && Array.isArray(report.trades) ? report.trades : null;
        if (!trades) return {success: false, error: 'reportData.trades returned non-array'};
        var offset = ${offset};
        var limit = ${limit};
        return {
          success: true,
          offset: offset,
          limit: limit,
          total: trades.length,
          rows: trades.slice(offset, offset + limit).map(function(o) { return primitiveObject(o, 180); })
        };
      `));
    });
    checkpoint.closed_trades.push(page);
    save();
  }

  checkpoint.orders_summary = await withClient('orders-summary', async client => {
    return evaluate(client, strategyPrelude(`
      var orders = null;
      if (strat.ordersData) orders = resolve(strat.ordersData.bind(strat));
      if (!orders && strat.tradesData) orders = resolve(strat.tradesData.bind(strat));
      if (!orders && strat._orders) orders = strat._orders;
      if (!Array.isArray(orders)) return {success: false, error: 'ordersData returned non-array', type: typeof orders};
      function row(o) { return primitiveObject(o, 120); }
      return {
        success: true,
        count: orders.length,
        first: orders.slice(0, 5).map(row),
        last: orders.slice(Math.max(0, orders.length - 5)).map(row)
      };
    `));
  });

  const totalOrders = Math.min(maxOrders, checkpoint.orders_summary?.count || 0);
  checkpoint.orders = [];
  for (let offset = 0; offset < totalOrders; offset += orderChunk) {
    const limit = Math.min(orderChunk, totalOrders - offset);
    const page = await withClient(`orders-${offset}-${offset + limit}`, async client => {
      return evaluate(client, strategyPrelude(`
        var orders = null;
        if (strat.ordersData) orders = resolve(strat.ordersData.bind(strat));
        if (!orders && strat.tradesData) orders = resolve(strat.tradesData.bind(strat));
        if (!orders && strat._orders) orders = strat._orders;
        if (!Array.isArray(orders)) return {success: false, error: 'ordersData returned non-array', type: typeof orders};
        var offset = ${offset};
        var limit = ${limit};
        return {
          success: true,
          offset: offset,
          limit: limit,
          total: orders.length,
          rows: orders.slice(offset, offset + limit).map(function(o) { return primitiveObject(o, 140); })
        };
      `));
    });
    checkpoint.orders.push(page);
    save();
  }

  checkpoint.success = true;
  save();
  console.log(JSON.stringify(checkpoint, null, 2));
}

main().catch(error => {
  checkpoint.success = false;
  checkpoint.error = String(error.message || error);
  save();
  console.error(checkpoint.error);
  process.exit(1);
});
