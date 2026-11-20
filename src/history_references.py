"""Obtain the compact named-hub series and effective membership independently of all-node retrieval."""
from common import *
from oasis import query
import argparse

def windows():
    day=date.fromisoformat(C["start"])
    limit=date.fromisoformat(C["end_exclusive"])
    while day<limit:
        month_end=(day.replace(day=28)+timedelta(days=4)).replace(day=1)
        # At most 28 calendar days including one fall-back hour.
        end=min(month_end,day+28*DAY,limit)
        yield day,end
        day=end

def run():
    p=argparse.ArgumentParser()
    p.add_argument("stage",choices=["hubs","mapping"])
    args=p.parse_args()
    failed=[]
    for day,end in windows():
        try:
            if args.stage=="hubs":
                query(day,C["report"],list(C["basis_hubs"].values()),end=end)
            else:query(day,"ATL_PNODE_MAP",end=end)
        except Exception as exc:
            failed.append([str(day),str(end),str(exc)])
    return 1 if failed else 0
if __name__=="__main__":raise SystemExit(run())
