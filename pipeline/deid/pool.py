"""Process pool that survives a crashed worker (OOM kill, native-library segfault): the unfinished items are retried;
an item batch that keeps killing the pool is reported through on_crash and skipped, never silently dropped."""
from __future__ import annotations
import multiprocessing as mp, os, sys, time


def run_pool(func, items, procs, initializer, on_result, on_crash, chunksize=4, max_tasks=400):
    pending = list(items)
    crashes = 0
    while pending:
        done = set()
        try:
            with mp.Pool(procs, initializer=initializer, maxtasksperchild=max_tasks) as pool:
                for res in pool.imap_unordered(func, pending, chunksize=chunksize):
                    done.add(res[0])
                    on_result(res)
            return
        except Exception as e:  # BrokenPipeError, worker died, ...
            crashes += 1
            pending = [p for p in pending if p not in done]
            print(f"pool crashed ({type(e).__name__}); {len(pending)} left, crash #{crashes}", file=sys.stderr, flush=True)
            time.sleep(3)
            if crashes % 3 == 0 and pending:      # suspect the first items of the remainder
                for p in pending[:chunksize * procs]:
                    on_crash(p)
                pending = pending[chunksize * procs:]
            chunksize = 1
