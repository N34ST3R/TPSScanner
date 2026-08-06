from quart import Quart, render_template, request, jsonify
from quart.json.provider import DefaultJSONProvider
from src.store.database import get_db
from src.analysis.signal import generate_signal, scan_watchlist as do_scan_watchlist
from src.data.polymarket import get_active_markets
from src.data.wallet import get_wallet_portfolio
from src.data.scraper import scrape_url
from src.delivery.alerts import get_alert_history
from src.store.config import ACCOUNT_SIZE
from src.data.live.news import fetch_news
from src.data.live.social import fetch_social
from src.data.live.crypto import fetch_crypto, fetch_global_stats, fetch_mcap_history
from src.data.live.calendar import fetch_calendar
from src.data.live.options_flow import fetch_options_flow
from src.data.live.insider import fetch_insider
from src.data.live.analyst import fetch_analyst
from src.data.live.stock_list import fetch_all_stocks
from src.data.live import markets as live_markets
from src.delivery.simulation import (
    execute_buy,
    execute_sell,
    get_portfolio_summary,
    get_transactions,
    reset_portfolio,
    get_current_price,
    load_watchlist,
    save_watchlist,
)
import time
import asyncio
import numpy as np


class NumpyJSONProvider(DefaultJSONProvider):
    def default(self, o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return super().default(o)


app = Quart(__name__, template_folder="templates", static_folder="static")
app.json_provider_class = NumpyJSONProvider
app.json = NumpyJSONProvider(app)


@app.route("/")
async def index():
    return await render_template("index.html")


@app.route("/api/watchlist", methods=["GET"])
async def get_watchlist():
    db = await get_db()
    cursor = await db.execute(
        "SELECT symbol, source, added_at FROM watchlist ORDER BY added_at DESC"
    )
    rows = await cursor.fetchall()
    return jsonify([{"symbol": r[0], "source": r[1], "added_at": r[2]} for r in rows])


@app.route("/api/watchlist", methods=["POST"])
async def add_to_watchlist():
    data = await request.get_json()
    symbol = data.get("symbol", "").upper()
    source = data.get("source", "auto")
    if not symbol:
        return jsonify({"error": "Symbol required"}), 400
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO watchlist (symbol, source) VALUES (?, ?)",
        (symbol, source),
    )
    await db.commit()
    return jsonify({"status": "added", "symbol": symbol})


@app.route("/api/watchlist/<symbol>", methods=["DELETE"])
async def remove_from_watchlist(symbol):
    db = await get_db()
    await db.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),))
    await db.commit()
    return jsonify({"status": "removed", "symbol": symbol.upper()})


@app.route("/api/scan/<symbol>")
async def scan_ticker(symbol):
    timeframe = request.args.get("timeframe", "5m")
    try:
        signal = await generate_signal(symbol.upper(), timeframe)
        return jsonify(signal)
    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


_market_cache: dict = {}


@app.route("/api/market/overview")
async def market_overview():
    """Batched live quotes for the sim watchlist - one request powers the dashboard."""
    now = time.time()
    if _market_cache and now - _market_cache["_ts"] < 20:
        return jsonify(_market_cache["payload"])

    symbols = load_watchlist()[:12]
    quotes = await asyncio.gather(
        *[get_current_price(s) for s in symbols], return_exceptions=True
    )
    items = []
    for i, sym in enumerate(symbols):
        q = quotes[i]
        if isinstance(q, Exception):
            q = {"symbol": sym, "price": 0, "change": 0, "change_pct": 0}
        items.append(
            {
                "symbol": q.get("symbol", sym),
                "price": q.get("price", 0),
                "change": q.get("change", 0),
                "change_pct": q.get("change_pct", 0),
            }
        )
    payload = {"items": items, "count": len(items), "updated_at": now}
    _market_cache.update({"_ts": now, "payload": payload})
    return jsonify(payload)


@app.route("/api/history/<symbol>")
async def history(symbol):
    """OHLCV price history for charting."""
    timeframe = request.args.get("timeframe", "5m")
    period = request.args.get("period", "5d")
    try:
        from src.data.fetcher import fetch_stock

        df = await fetch_stock(symbol.upper(), period=period, interval=timeframe)
        if df.empty:
            return jsonify({"symbol": symbol.upper(), "points": []})
        points = []
        for _, row in df.iterrows():
            ts = row["date"]
            points.append(
                {
                    "t": ts.timestamp() if hasattr(ts, "timestamp") else ts,
                    "o": round(float(row["open"]), 4),
                    "h": round(float(row["high"]), 4),
                    "l": round(float(row["low"]), 4),
                    "c": round(float(row["close"]), 4),
                    "v": int(row["volume"] or 0),
                }
            )
        return jsonify({"symbol": symbol.upper(), "timeframe": timeframe, "points": points})
    except Exception as e:
        return jsonify({"symbol": symbol.upper(), "points": [], "error": str(e)}), 500


@app.route("/api/signals/recent")
async def signals_recent():
    """Most recent stored signals - one per symbol (latest), so the dashboard shows variety."""
    limit = max(1, min(request.args.get("limit", 50, type=int), 100))
    db = await get_db()
    # Latest id per symbol, then overall newest first.
    cursor = await db.execute(
        "SELECT symbol, MAX(id) AS mid FROM signals GROUP BY symbol "
        "ORDER BY mid DESC LIMIT ?",
        (min(limit * 3, 200),),
    )
    latest = [r["mid"] for r in await cursor.fetchall()][:limit]
    if not latest:
        return jsonify([])
    placeholders = ",".join("?" for _ in latest)
    cursor = await db.execute(
        "SELECT symbol, source, score, label, net_direction, patterns, indicators, timeframe, created_at "
        f"FROM signals WHERE id IN ({placeholders}) ORDER BY id DESC",
        latest,
    )
    rows = await cursor.fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "symbol": r["symbol"],
                "source": r["source"],
                "score": r["score"],
                "label": r["label"],
                "net_direction": r["net_direction"],
                "patterns": r["patterns"] or "",
                "indicators": r["indicators"] or "",
                "timeframe": r["timeframe"],
                "created_at": r["created_at"],
            }
        )
    return jsonify(out)


@app.route("/api/scan/watchlist")
async def scan_all():
    timeframe = request.args.get("timeframe", "5m")
    db = await get_db()
    cursor = await db.execute("SELECT symbol FROM watchlist")
    rows = await cursor.fetchall()
    symbols = [r[0] for r in rows]
    if not symbols:
        return jsonify([])
    # Run under the same lock as the background scanner so concurrent manual
    # scans never double-fetch Yahoo.
    from src.main import _scan_lock

    if _scan_lock.locked():
        return jsonify({"error": "A scan is already running"}), 409
    import json

    def _jdefault(o):
        try:
            return float(o)
        except (TypeError, ValueError):
            return str(o)

    async with _scan_lock:
        results = await do_scan_watchlist(symbols, timeframe)
        # Persist so the stored-signals dashboard shows variety too.
        for r in results:
            await db.execute(
                "INSERT INTO signals (symbol, source, score, label, net_direction, patterns, indicators, timeframe) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["symbol"],
                    "yahoo",
                    r["score"],
                    r["label"],
                    r["net_direction"],
                    json.dumps(r.get("patterns", []), default=_jdefault),
                    json.dumps(r.get("indicators", {}), default=_jdefault),
                    r.get("timeframe", "5m"),
                ),
            )
        await db.commit()
    return jsonify(results)


@app.route("/api/polymarket")
async def polymarket():
    markets = await get_active_markets()
    return jsonify(markets)


@app.route("/api/wallet/<address>")
async def wallet(address):
    portfolio = await get_wallet_portfolio(address)
    return jsonify(portfolio)


@app.route("/api/scrape")
async def scrape():
    url = request.args.get("url")
    selector = request.args.get("selector")
    if not url:
        return jsonify({"error": "URL required"}), 400
    result = await scrape_url(url, selector)
    return jsonify(result)


@app.route("/api/alerts")
async def alerts():
    limit = request.args.get("limit", 50, type=int)
    history = await get_alert_history(limit)
    return jsonify(history)


@app.route("/api/stats")
async def stats():
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM watchlist")
    watchlist_count = (await cursor.fetchone())[0]
    cursor = await db.execute("SELECT COUNT(*) FROM signals")
    signal_count = (await cursor.fetchone())[0]
    cursor = await db.execute("SELECT COUNT(*) FROM alerts")
    alert_count = (await cursor.fetchone())[0]
    return jsonify(
        {
            "watchlist_count": watchlist_count,
            "signal_count": signal_count,
            "alert_count": alert_count,
            "account_size": ACCOUNT_SIZE,
        }
    )


@app.route("/api/live/news")
async def live_news():
    try:
        return jsonify(await fetch_news())
    except Exception as e:
        return jsonify({"articles": [], "error": str(e)})


@app.route("/api/live/social")
async def live_social():
    try:
        return jsonify(await fetch_social())
    except Exception as e:
        return jsonify({"posts": [], "error": str(e)})


@app.route("/api/live/crypto")
async def live_crypto():
    try:
        return jsonify(await fetch_crypto())
    except Exception as e:
        return jsonify({"coins": [], "error": str(e)})


@app.route("/api/live/crypto/global")
async def live_crypto_global():
    try:
        return jsonify(await fetch_global_stats())
    except Exception as e:
        return jsonify({"total_market_cap": 0, "error": str(e)})


@app.route("/api/live/crypto/mcap")
async def live_crypto_mcap():
    days = request.args.get("days", 30, type=int)
    try:
        return jsonify(await fetch_mcap_history(days))
    except Exception as e:
        return jsonify({"points": [], "error": str(e)})


@app.route("/api/live/calendar")
async def live_calendar():
    try:
        return jsonify(await fetch_calendar())
    except Exception as e:
        return jsonify({"events": [], "error": str(e)})


@app.route("/api/live/options")
async def live_options():
    try:
        return jsonify(await fetch_options_flow())
    except Exception as e:
        return jsonify({"flow": [], "error": str(e)})


@app.route("/api/live/insider")
async def live_insider():
    try:
        return jsonify(await fetch_insider())
    except Exception as e:
        return jsonify({"trades": [], "error": str(e)})


@app.route("/api/live/analyst")
async def live_analyst():
    try:
        return jsonify(await fetch_analyst())
    except Exception as e:
        return jsonify({"ratings": [], "error": str(e)})


@app.route("/api/live/stocks")
async def live_stocks():
    try:
        return jsonify(await fetch_all_stocks())
    except Exception as e:
        return jsonify({"stocks": [], "error": str(e)})


@app.route("/api/live/indices")
async def live_indices():
    try:
        return jsonify(await live_markets.fetch_indices())
    except Exception as e:
        return jsonify({"items": [], "error": str(e)})


@app.route("/api/live/commodities")
async def live_commodities():
    try:
        return jsonify(await live_markets.fetch_commodities())
    except Exception as e:
        return jsonify({"items": [], "error": str(e)})


@app.route("/api/live/forex")
async def live_forex():
    try:
        return jsonify(await live_markets.fetch_forex())
    except Exception as e:
        return jsonify({"items": [], "error": str(e)})


@app.route("/api/live/movers")
async def live_movers():
    try:
        return jsonify(await live_markets.fetch_movers())
    except Exception as e:
        return jsonify({"gainers": [], "losers": [], "most_active": [], "error": str(e)})


@app.route("/api/live/fear-greed")
async def live_fear_greed():
    try:
        return jsonify(await live_markets.fetch_fear_greed())
    except Exception as e:
        return jsonify({"score": 0, "rating": "Unknown", "error": str(e)})


@app.route("/api/simulation/portfolio")
async def sim_portfolio():
    try:
        return jsonify(await get_portfolio_summary())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/simulation/buy", methods=["POST"])
async def sim_buy():
    data = await request.get_json()
    symbol = data.get("symbol", "").upper()
    quantity = data.get("quantity", 0)
    if not symbol or quantity <= 0:
        return jsonify({"error": "Symbol and valid quantity required"}), 400
    price_data = await get_current_price(symbol)
    if price_data["price"] <= 0:
        return jsonify({"error": f"Could not get price for {symbol}"}), 400
    result = execute_buy(symbol, quantity, price_data["price"])
    result["price"] = price_data["price"]
    return jsonify(result)


@app.route("/api/simulation/sell", methods=["POST"])
async def sim_sell():
    data = await request.get_json()
    symbol = data.get("symbol", "").upper()
    quantity = data.get("quantity", 0)
    if not symbol or quantity <= 0:
        return jsonify({"error": "Symbol and valid quantity required"}), 400
    price_data = await get_current_price(symbol)
    if price_data["price"] <= 0:
        return jsonify({"error": f"Could not get price for {symbol}"}), 400
    result = execute_sell(symbol, quantity, price_data["price"])
    result["price"] = price_data["price"]
    return jsonify(result)


@app.route("/api/simulation/transactions")
async def sim_transactions():
    limit = request.args.get("limit", 50, type=int)
    return jsonify(get_transactions(limit))


@app.route("/api/simulation/reset", methods=["POST"])
async def sim_reset():
    return jsonify(reset_portfolio())


@app.route("/api/simulation/price/<symbol>")
async def sim_price(symbol):
    return jsonify(await get_current_price(symbol.upper()))


@app.route("/api/watchlist-sim", methods=["GET"])
async def get_watchlist_sim():
    return jsonify(load_watchlist())


@app.route("/api/watchlist-sim", methods=["POST"])
async def add_watchlist_sim():
    data = await request.get_json()
    symbol = data.get("symbol", "").upper()
    if not symbol:
        return jsonify({"error": "Symbol required"}), 400
    wl = load_watchlist()
    if symbol not in wl:
        wl.append(symbol)
        save_watchlist(wl)
    return jsonify({"status": "added", "symbol": symbol, "watchlist": wl})


@app.route("/api/watchlist-sim/<symbol>", methods=["DELETE"])
async def remove_watchlist_sim(symbol):
    wl = load_watchlist()
    wl = [s for s in wl if s != symbol.upper()]
    save_watchlist(wl)
    return jsonify({"status": "removed", "symbol": symbol.upper(), "watchlist": wl})


@app.route("/api/alerts/check")
async def alerts_check():
    try:
        portfolio = await get_portfolio_summary()
        alerts = []
        for pos in portfolio.get("positions", []):
            pct = pos.get("unrealized_pnl_pct", 0)
            if pct <= -5:
                alerts.append(
                    {
                        "type": "warning",
                        "title": f"{pos['symbol']} Down {pct:.1f}%",
                        "message": f"Position in {pos['symbol']} is down {pct:.1f}% from cost basis. Consider cutting losses.",
                        "symbol": pos["symbol"],
                        "timestamp": time.time(),
                    }
                )
            elif pct >= 10:
                alerts.append(
                    {
                        "type": "success",
                        "title": f"{pos['symbol']} Up {pct:.1f}%",
                        "message": f"Position in {pos['symbol']} is up {pct:.1f}%. Consider taking profits.",
                        "symbol": pos["symbol"],
                        "timestamp": time.time(),
                    }
                )
        if portfolio.get("total_pnl_pct", 0) <= -10:
            alerts.append(
                {
                    "type": "danger",
                    "title": "Portfolio Down Significantly",
                    "message": f"Portfolio is down {portfolio['total_pnl_pct']:.1f}% overall. Review positions.",
                    "symbol": "PORTFOLIO",
                    "timestamp": time.time(),
                }
            )
        if not alerts:
            alerts.append(
                {
                    "type": "info",
                    "title": "All Clear",
                    "message": "No alerts triggered. Portfolio is within normal parameters.",
                    "symbol": "SYSTEM",
                    "timestamp": time.time(),
                }
            )
        return jsonify({"alerts": alerts, "count": len(alerts)})
    except Exception as e:
        return jsonify({"alerts": [], "count": 0, "error": str(e)})


# --- Top Traders API ---
import json as json_mod
from pathlib import Path as PathMod
from src.toptraders import store as tt_store
from src.toptraders import leaderboard as tt_leaderboard
from src.toptraders import copytrader as tt_copytrader


async def _load_leaderboard():
    if tt_leaderboard.LEADERBOARD_PATH.exists():
        try:
            return json_mod.loads(tt_leaderboard.LEADERBOARD_PATH.read_text())
        except Exception:
            pass
    return await tt_leaderboard.rebuild_leaderboard()


@app.route("/api/toptraders/accounts")
async def toptraders_accounts():
    """Every trader currently tracked by the engine (pre-eligibility)."""
    try:
        rows = await tt_store.list_accounts()
        out = []
        for a in rows:
            out.append(
                {
                    "handle": a["handle"],
                    "display_name": a["display_name"],
                    "source": a["source"],
                    "copy_enabled": bool(a["copy_enabled"]),
                }
            )
        return jsonify({"accounts": out, "count": len(out)})
    except Exception as e:
        return jsonify({"accounts": [], "count": 0, "error": str(e)})


@app.route("/api/toptraders/leaderboard")
async def toptraders_leaderboard():
    try:
        return jsonify(await _load_leaderboard())
    except Exception as e:
        return jsonify({"traders": [], "error": str(e)})


@app.route("/api/toptraders/picks")
async def toptraders_picks():
    try:
        calls = await tt_store.list_open_calls()
        wr_by_handle = {}
        try:
            for t in await tt_leaderboard.compute_win_rate(5):
                wr_by_handle[t["handle"]] = t["win_rate"]
        except Exception:
            pass
        picks = []
        for c in calls:
            price_data = {}
            try:
                from src.delivery.simulation import get_current_price

                price_data = await get_current_price(c["symbol"])
            except Exception:
                pass
            price = price_data.get("price") or 0
            entry = c["entry_price"] or 0
            unrealized = (price - entry) / entry * 100 if entry and price else 0.0
            picks.append(
                {
                    "id": c["id"],
                    "symbol": c["symbol"],
                    "direction": c["direction"],
                    "entry_price": entry,
                    "handle": c["handle"],
                    "display_name": c["display_name"],
                    "source": c["source"],
                    "win_rate": wr_by_handle.get(c["handle"]),
                    "unrealized_pct": round(unrealized, 2),
                }
            )
        return jsonify({"picks": picks})
    except Exception as e:
        return jsonify({"picks": [], "error": str(e)})


@app.route("/api/toptraders/copy")
async def toptraders_copy():
    try:
        return jsonify(await tt_copytrader.get_copy_summary())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/toptraders/copy/<int:call_id>", methods=["POST"])
async def toptraders_copy_call(call_id):
    try:
        body = await request.get_json(silent=True) or {}
        wr = float(body.get("wr", 0.75))
        return jsonify(await tt_copytrader.copy_call(call_id, wr))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/toptraders/accounts/<handle>/toggle", methods=["POST"])
async def toptraders_toggle(handle):
    try:
        acc = await tt_store.get_account(handle)
        if acc is None:
            return jsonify({"error": "Account not found"}), 404
        new_state = 0 if acc["copy_enabled"] else 1
        await tt_store.set_copy_enabled(handle, bool(new_state))
        return jsonify({"handle": handle, "copy_enabled": new_state})
    except Exception as e:
        return jsonify({"error": str(e)})


_tt_collect_state = {"running": False, "last": None, "error": None}


async def _run_collect():
    from src.toptraders import collector as tt_collector

    _tt_collect_state["running"] = True
    try:
        _tt_collect_state["last"] = await tt_collector.collect_all()
        _tt_collect_state["error"] = None
    except Exception as e:
        _tt_collect_state["error"] = str(e)
    finally:
        _tt_collect_state["running"] = False


@app.route("/api/toptraders/collect", methods=["POST"])
async def toptraders_collect_now():
    """Start a background collection from StockTwits / TradingView / Polymarket."""
    if _tt_collect_state["running"]:
        return jsonify({"running": True, "message": "Collection already in progress"})
    asyncio.create_task(_run_collect())
    return jsonify({"started": True, "message": "Collection started — takes about a minute"})


@app.route("/api/toptraders/collect/status")
async def toptraders_collect_status():
    return jsonify(_tt_collect_state)
