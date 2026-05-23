#!/usr/bin/env python3
"""
PriceScout — Discovery Run (автономний скрипт).

Запускає повний перебір ВСІХ товарів по ВСІХ постачальниках і зберігає
результати в БД (таблиця supplier_entries). Після завершення кожен
наступний звичайний батч автоматично пропускатиме постачальників, де
товар не знайдено (runner.SKIP_STALE_DAYS = 30 днів).

Запуск (з директорії проєкту):
    python cli/discover.py [--limit N] [--workers N] [--suppliers sup1,sup2]

Аргументи:
    --limit N       обробити лише перші N товарів (для тесту)
    --workers N     кількість паралельних завантажень постачальників (default: 4)
    --suppliers X   список ID постачальників через кому (default: усі активні)
"""

import argparse
import os
import sys
import threading
import time
from pathlib import Path

# Run from the project root so relative paths (pricescout.db, exports/) work.
_PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(_PROJECT_ROOT)
sys.path.insert(0, str(_PROJECT_ROOT))

from core.item_db import init_db, load_items
from core.suppliers import SUPPLIERS
from core.core import state
from core import runner


def _progress_monitor(total: int, stop_event: threading.Event):
    """Print a live progress line every 10 seconds."""
    while not stop_event.is_set():
        # Access runner.item_states via module to pick up the reassigned dict.
        done = sum(1 for s in runner.item_states.values() if s.get("done"))
        found = len(state.get("results") or [])
        print(f"\r  Прогрес: {done}/{total} товарів | {found} цін знайдено", end="", flush=True)
        stop_event.wait(10)
    print()  # newline after monitor stops


def main():
    parser = argparse.ArgumentParser(description="PriceScout discovery run")
    parser.add_argument("--limit",     type=int, default=0,  help="Обробити лише перші N товарів")
    parser.add_argument("--workers",   type=int, default=4,  help="Паралельних постачальників на товар")
    parser.add_argument("--suppliers", type=str, default="", help="ID постачальників через кому")
    args = parser.parse_args()

    print("=" * 60)
    print("  PriceScout — DISCOVERY RUN")
    print("=" * 60)

    init_db()

    items = load_items()
    monitorable = [i for i in items if i.get("monitorable", True)]
    print(f"  Всього товарів у БД:    {len(items)}")
    print(f"  Моніторяться:           {len(monitorable)}")

    if args.limit > 0:
        monitorable = monitorable[:args.limit]
        print(f"  Обмеження (--limit):    {args.limit}")

    item_ids = [i["id"] for i in monitorable]

    if args.suppliers:
        active_ids = [s.strip() for s in args.suppliers.split(",") if s.strip()]
    else:
        active_ids = [s["id"] for s in SUPPLIERS if s.get("enabled", True)]

    print(f"  Постачальники ({len(active_ids)}):    {', '.join(active_ids)}")
    print(f"  runner.SKIP_STALE_DAYS:        {runner.SKIP_STALE_DAYS} (після discovery)")
    print(f"  Паралельність:          1 товар x {args.workers} постачальників")
    print()

    if not item_ids:
        print("  Немає товарів для обробки.")
        return

    # Override inner workers via env var used by runner.py
    os.environ["MAX_INNER_WORKERS_DISCOVERY"] = str(args.workers)

    start_time = time.time()

    # Start progress monitor in a background thread
    stop_monitor = threading.Event()
    monitor_thread = threading.Thread(
        target=_progress_monitor,
        args=(len(item_ids), stop_monitor),
        daemon=True,
    )
    monitor_thread.start()

    try:
        # _run_batch is synchronous (blocks until all items are done)
        runner._run_batch(
            item_ids,
            active_ids,
            parallel_items=1,      # sequential items in discovery mode
            discovery_mode=True,
        )
    except KeyboardInterrupt:
        print("\n  Зупинено користувачем.")
        state["stop_requested"] = True
    finally:
        stop_monitor.set()
        monitor_thread.join(timeout=2)

    elapsed = time.time() - start_time
    results = state.get("results") or []
    found = len([r for r in results if r.get("price")])

    print()
    print("=" * 60)
    print(f"  ГОТОВО за {elapsed/60:.1f} хвилин")
    print(f"  Товарів оброблено:  {len(item_ids)}")
    print(f"  Цін знайдено:       {found}")
    print()
    print("  Матриця доступності збережена в БД.")
    print("  Наступні запити автоматично пропускатимуть")
    print(f"  постачальників, де товар не знайдено (на {runner.SKIP_STALE_DAYS} днів).")
    print("=" * 60)


if __name__ == "__main__":
    main()
