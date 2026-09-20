"""系统运行健康度 —— 「有东西悄悄挂了吗」的只读查询

仪表盘（REST）与 MCP 共用同一份判定，避免两边各写一套口径。本模块只读：
不回收僵死任务、不改调度状态，僵死的同步任务只在结果里标出来。

三类运行记录各管一段，互不替代：
  collection_records    采集型数据源每次采集的结果（也是调度算法的输入）
  sync_task_progress    内置同步 / 外部推送的运行记录
  procrastinate_jobs    后台任务本身（日报、清理、调度心跳……）。前两张表只记「数据源」的运行，
                        不挂在任何数据源上的定时任务失败了只有这里看得到——
                        日报连续失败 20 天无人察觉即此（2026-09 审计 §84）。
                        注意：队列里不存异常文本，失败原因要到 worker 日志里找；
                        已结束的作业 7 天后被 cleanup_job_queue 清掉，所以这里最多回看 7 天。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, text
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.content import CollectionRecord, ContentItem, SourceConfig
from app.models.credential import PlatformCredential
from app.models.source_types import Runner, get_spec, is_schedulable
from app.models.sync_progress import SyncTaskProgress
from app.services.sync.runner import STALE_AFTER

# 数据源健康的失败率统计窗口
SOURCE_HEALTH_WINDOW_DAYS = 7

# 后台作业在 doing 状态超过这么久视为卡住（与 cleanup_job_queue 的僵死回收阈值一致）
_STUCK_JOB_AFTER = timedelta(hours=1)

# 每分钟 / 每 10 分钟触发的调度心跳：偶发失败下一轮自愈，不值得单独报警，
# 但连续失败说明调度器本身坏了，所以仍然统计、只是不靠单次失败定级
_HEARTBEAT_TASKS = {
    "app.tasks.scheduled_tasks.check_and_collect_sources",
    "app.tasks.scheduled_tasks.auto_sync_sources",
}

# 已从代码里下线、但队列里可能还留着历史失败的任务。不能再算「仍在失败」——
# 否则停用一个坏任务反而让总评连报 7 天 error。这里不去问 proc_app.tasks：导入
# app.tasks.procrastinate_app 会执行 setup_logging("worker")，让 API / MCP 进程去写 worker.log。
# 停用 / 恢复定时任务时同步改这里（scheduled_tasks.py 里被注释的定义处有对应说明）；
# 条目在下线满 7 天、历史作业被 cleanup_job_queue 清掉之后即可删除。
_RETIRED_TASKS = {
    "app.tasks.scheduled_tasks.trigger_daily_report",    # 2026-09-20 停用
    "app.tasks.scheduled_tasks.trigger_weekly_report",   # 2026-09-20 停用
}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# 应用自己的表用 naive UTC（app.core.time.utcnow）；procrastinate 的表是 timestamptz，
# 驱动按会话时区返回带偏移的时间。进出队列表时在这两个函数里换算，别处一律 naive UTC。
def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc)


def _naive_utc(dt: datetime | None) -> datetime | None:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt else None


def is_non_collecting(source_type: str | None) -> bool:
    """不进定时调度的数据源（同步类、用户提交、纯归属容器、手动目录扫描）没有持续的采集记录，
    不参与健康判定。判定依据是源类型注册表，不再自维护名单（旧名单漏了 user.film）。"""
    if not source_type:
        return False
    return not is_schedulable(source_type)


def source_health(db: Session) -> dict:
    """数据源健康概览

    只对"启用且需要采集"的源做健康判定，分三档：
      error    连续失败 >= 3 或近 7 天失败率 >= 50%
      warning  连续失败 >= 1 或近 7 天失败率 >= 20%
      healthy  其余
    已禁用（disabled）和外部同步型（sync）只计数、不判定。

    每个源附带判定依据（reasons）、近 7 天采集/失败/新增数、最近采集与最近有新内容的时间。
    """
    now = utcnow()
    window_start = now - timedelta(days=SOURCE_HEALTH_WINDOW_DAYS)

    window_rows = (
        db.query(
            CollectionRecord.source_id,
            func.count(CollectionRecord.id).label("total"),
            func.sum(case((CollectionRecord.status == "failed", 1), else_=0)).label("failed"),
            func.sum(func.coalesce(CollectionRecord.items_new, 0)).label("items_new"),
        )
        .filter(CollectionRecord.started_at >= window_start)
        .group_by(CollectionRecord.source_id)
        .all()
    )
    window_map = {r.source_id: (r.total, r.failed or 0, r.items_new or 0) for r in window_rows}

    last_item_rows = (
        db.query(ContentItem.source_id, func.max(ContentItem.collected_at).label("last_item"))
        .filter(ContentItem.source_id.isnot(None))
        .group_by(ContentItem.source_id)
        .all()
    )
    last_item_map = {r.source_id: r.last_item for r in last_item_rows}

    sources = db.query(SourceConfig).order_by(SourceConfig.name).all()

    summary = {"healthy": 0, "warning": 0, "error": 0, "disabled": 0, "sync": 0}
    data = []
    for s in sources:
        total, failed, items_new = window_map.get(s.id, (0, 0, 0))
        failure_rate = round(failed / total * 100, 1) if total > 0 else 0.0
        last_item = last_item_map.get(s.id)
        reasons: list[str] = []

        if not s.is_active:
            health = "disabled"
        elif is_non_collecting(s.source_type):
            health = "sync"
        else:
            if s.consecutive_failures >= 3 or failure_rate >= 50:
                health = "error"
            elif s.consecutive_failures >= 1 or failure_rate >= 20:
                health = "warning"
            else:
                health = "healthy"
            if s.consecutive_failures > 0:
                reasons.append(f"连续失败 {s.consecutive_failures} 次")
            if failed > 0:
                reasons.append(f"近 {SOURCE_HEALTH_WINDOW_DAYS} 天失败 {failed}/{total}（{failure_rate:g}%）")
            if total > 0 and items_new == 0:
                if last_item:
                    idle_days = (now - last_item).days
                    reasons.append(f"{idle_days} 天无新内容" if idle_days >= 1 else "今日暂无新内容")
                else:
                    reasons.append("从未采到内容")
            if total == 0:
                reasons.append(f"近 {SOURCE_HEALTH_WINDOW_DAYS} 天无采集记录")

        summary[health] += 1
        data.append({
            "id": s.id,
            "name": s.name,
            "source_type": s.source_type,
            "health": health,
            "reasons": reasons,
            "consecutive_failures": s.consecutive_failures,
            "window_total": total,
            "window_failed": failed,
            "failure_rate": failure_rate,
            "items_new_window": items_new,
            "last_collected_at": _iso(s.last_collected_at),
            "last_item_at": _iso(last_item),
            "is_active": s.is_active,
        })

    return {
        "window_days": SOURCE_HEALTH_WINDOW_DAYS,
        "summary": summary,
        "sources": data,
    }


def source_runs(db: Session, source: SourceConfig, limit: int = 10) -> dict:
    """单个数据源最近的运行记录 —— 采集型看 collection_records，同步 / 推送型看 sync_task_progress"""
    spec = get_spec(source.source_type)
    runner = spec.runner.value if spec else None

    if spec and spec.runner in (Runner.SYNCER, Runner.PUSH):
        rows = (
            db.query(SyncTaskProgress)
            .filter(SyncTaskProgress.source_id == source.id)
            .order_by(SyncTaskProgress.created_at.desc())
            .limit(limit)
            .all()
        )
        runs = [{
            "at": _iso(r.started_at or r.created_at),
            "status": r.status,
            "trigger": (r.options_json or {}).get("_trigger"),
            "result": r.result_data,
            "error": r.error_message,
        } for r in rows]
        record_table = "sync_task_progress"
    else:
        rows = (
            db.query(CollectionRecord)
            .filter(CollectionRecord.source_id == source.id)
            .order_by(CollectionRecord.started_at.desc())
            .limit(limit)
            .all()
        )
        runs = [{
            "at": _iso(r.started_at),
            "status": r.status,
            "items_found": r.items_found,
            "items_new": r.items_new,
            "error": r.error_message,
        } for r in rows]
        record_table = "collection_records"

    return {"runner": runner, "record_table": record_table, "runs": runs}


def sync_overview(db: Session) -> list[dict]:
    """同步 / 推送型数据源的现状：最近一次成功、最近一次失败、是否在跑、凭证状态

    「最后同步」取 sync_task_progress 里最近一次成功，而不是 source.last_collected_at
    （后者曾被采集任务写过假值，见 routes/sync.py 同名说明）。
    """
    now = utcnow()
    sources = [
        s for s in db.query(SourceConfig).order_by(SourceConfig.name).all()
        if (spec := get_spec(s.source_type)) and spec.runner in (Runner.SYNCER, Runner.PUSH)
    ]
    if not sources:
        return []
    ids = [s.id for s in sources]

    last_ok = dict(
        db.query(
            SyncTaskProgress.source_id,
            func.max(func.coalesce(SyncTaskProgress.completed_at, SyncTaskProgress.created_at)),
        )
        .filter(SyncTaskProgress.source_id.in_(ids), SyncTaskProgress.status == "completed")
        .group_by(SyncTaskProgress.source_id)
        .all()
    )

    latest: dict[str, SyncTaskProgress] = {}
    for row in (
        db.query(SyncTaskProgress)
        .filter(SyncTaskProgress.source_id.in_(ids))
        .order_by(SyncTaskProgress.created_at.desc())
        .limit(500)
    ):
        latest.setdefault(row.source_id, row)

    cred_ids = [s.credential_id for s in sources if s.credential_id]
    creds = (
        {c.id: c for c in db.query(PlatformCredential).filter(PlatformCredential.id.in_(cred_ids)).all()}
        if cred_ids else {}
    )

    out = []
    for s in sources:
        spec = get_spec(s.source_type)
        row = latest.get(s.id)
        ok_at = last_ok.get(s.id)
        cred = creds.get(s.credential_id) if s.credential_id else None
        problems: list[str] = []

        running = bool(row and row.status in ("pending", "running"))
        if running and (row.updated_at or row.created_at) < now - STALE_AFTER:
            running = False
            problems.append("同步任务已僵死（worker 重启或退出），下次查看同步面板或发起同步时会被回收")
        if row and row.status == "failed":
            problems.append(f"最近一次同步失败: {row.error_message or '无错误信息'}")
        if s.is_active and spec.credential_required and not s.credential_id:
            problems.append("需要凭证但未绑定")
        if cred and cred.status != "active":
            problems.append(f"凭证状态异常: {cred.status}")
        if s.is_active and spec.auto_sync_minutes and spec.runner == Runner.SYNCER:
            # 自动同步的源：超过 3 个周期没成功过就算落后
            overdue = timedelta(minutes=spec.auto_sync_minutes * 3)
            if ok_at is None:
                problems.append("开启了自动同步但从未成功过")
            elif now - ok_at > overdue:
                problems.append(f"自动同步每 {spec.auto_sync_minutes} 分钟一次，但已 {int((now - ok_at).total_seconds() // 60)} 分钟没有成功")

        out.append({
            "id": s.id,
            "name": s.name,
            "source_type": s.source_type,
            "runner": spec.runner.value,
            "is_active": s.is_active,
            "auto_sync_minutes": spec.auto_sync_minutes,
            "last_success_at": _iso(ok_at),
            "last_run_at": _iso(row.created_at) if row else None,
            "last_run_status": row.status if row else None,
            "is_syncing": running,
            "credential_status": cred.status if cred else None,
            "problems": problems,
        })
    return out


def background_jobs(db: Session, since: datetime) -> dict:
    """后台任务队列里的失败与卡住的作业（按任务名聚合）"""
    now = utcnow()
    failed_rows = db.execute(text("""
        SELECT j.task_name,
               count(*)                                        AS failed,
               max(e.at)                                       AS last_failed_at
        FROM procrastinate_jobs j
        JOIN procrastinate_events e ON e.job_id = j.id AND e.type = 'failed'
        WHERE j.status = 'failed' AND e.at >= :since
        GROUP BY j.task_name
    """), {"since": _aware(since)}).all()

    # 同一窗口内成功过几次、最近一次成功在什么时候 —— 用来区分「偶发」与「一直在失败」
    names = [r.task_name for r in failed_rows]
    ok_map: dict[str, tuple[int, datetime | None]] = {}
    if names:
        for r in db.execute(text("""
            SELECT j.task_name, count(*) AS succeeded, max(e.at) AS last_ok_at
            FROM procrastinate_jobs j
            JOIN procrastinate_events e ON e.job_id = j.id AND e.type = 'succeeded'
            WHERE j.status = 'succeeded' AND e.at >= :since AND j.task_name = ANY(:names)
            GROUP BY j.task_name
        """), {"since": _aware(since), "names": names}):
            ok_map[r.task_name] = (r.succeeded, r.last_ok_at)

    failed = []
    for r in failed_rows:
        succeeded, last_ok_at = ok_map.get(r.task_name, (0, None))
        last_failed_at = _naive_utc(r.last_failed_at)
        last_ok_naive = _naive_utc(last_ok_at)
        # 窗口内一次都没成功过、或最近一次结果是失败 → 仍在失败
        retired = r.task_name in _RETIRED_TASKS
        still_failing = not retired and (
            last_ok_naive is None or (last_failed_at is not None and last_failed_at > last_ok_naive)
        )
        failed.append({
            "task": r.task_name.rsplit(".", 1)[-1],
            "task_name": r.task_name,
            "failed": r.failed,
            "succeeded": succeeded,
            "last_failed_at": _iso(last_failed_at),
            "last_succeeded_at": _iso(last_ok_naive),
            "still_failing": still_failing,
            "retired": retired,
            "heartbeat": r.task_name in _HEARTBEAT_TASKS,
        })
    failed.sort(key=lambda x: (not x["still_failing"], -x["failed"]))

    stuck_rows = db.execute(text("""
        SELECT j.id, j.task_name, max(e.at) AS started_at
        FROM procrastinate_jobs j
        JOIN procrastinate_events e ON e.job_id = j.id AND e.type = 'started'
        WHERE j.status = 'doing'
        GROUP BY j.id, j.task_name
        HAVING max(e.at) < :cutoff
        ORDER BY max(e.at)
        LIMIT 20
    """), {"cutoff": _aware(now - _STUCK_JOB_AFTER)}).all()
    stuck = [{
        "job_id": r.id,
        "task": r.task_name.rsplit(".", 1)[-1],
        "started_at": _iso(_naive_utc(r.started_at)),
    } for r in stuck_rows]

    return {"failed": failed, "stuck": stuck}


def recent_failures(db: Session, since: datetime, limit: int = 30,
                    source_id: str | None = None) -> list[dict]:
    """按时间倒序的失败事件流，合并三类运行记录。source_id 给定时只看该数据源（不含后台任务）"""
    events: list[dict] = []

    q = (
        db.query(CollectionRecord, SourceConfig.name)
        .join(SourceConfig, SourceConfig.id == CollectionRecord.source_id)
        .filter(CollectionRecord.status == "failed", CollectionRecord.started_at >= since)
    )
    if source_id:
        q = q.filter(CollectionRecord.source_id == source_id)
    for rec, name in q.order_by(CollectionRecord.started_at.desc()).limit(limit):
        events.append({
            "at": _iso(rec.started_at),
            "type": "collection",
            "source_id": rec.source_id,
            "source_name": name,
            "error": rec.error_message,
        })

    q = (
        db.query(SyncTaskProgress, SourceConfig.name)
        .join(SourceConfig, SourceConfig.id == SyncTaskProgress.source_id)
        .filter(SyncTaskProgress.status == "failed", SyncTaskProgress.created_at >= since)
    )
    if source_id:
        q = q.filter(SyncTaskProgress.source_id == source_id)
    for row, name in q.order_by(SyncTaskProgress.created_at.desc()).limit(limit):
        events.append({
            "at": _iso(row.completed_at or row.created_at),
            "type": "sync",
            "source_id": row.source_id,
            "source_name": name,
            "trigger": (row.options_json or {}).get("_trigger"),
            "error": row.error_message,
        })

    if not source_id:
        for r in db.execute(text("""
            SELECT j.id, j.task_name, e.at
            FROM procrastinate_jobs j
            JOIN procrastinate_events e ON e.job_id = j.id AND e.type = 'failed'
            WHERE j.status = 'failed' AND e.at >= :since
            ORDER BY e.at DESC
            LIMIT :limit
        """), {"since": _aware(since), "limit": limit}):
            events.append({
                "at": _iso(_naive_utc(r.at)),
                "type": "background_job",
                "job_id": r.id,
                "task": r.task_name.rsplit(".", 1)[-1],
                "error": None,
                "note": "任务队列不保存异常文本，原因见 allin-worker-scheduled / allin-worker-pipeline 容器日志",
            })

    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return events[:limit]


def system_health(db: Session, since: datetime) -> dict:
    """一次调用回答「现在有什么坏了」：只列出有问题的部分，健康的只给计数"""
    sh = source_health(db)
    problem_sources = [s for s in sh["sources"] if s["health"] in ("error", "warning")]
    problem_sources.sort(key=lambda s: (s["health"] != "error", -s["consecutive_failures"], -s["failure_rate"]))

    syncs = sync_overview(db)
    problem_syncs = [s for s in syncs if s["problems"]]

    jobs = background_jobs(db, since)
    failing_jobs = [j for j in jobs["failed"] if j["still_failing"]]

    if any(s["health"] == "error" for s in problem_sources) or failing_jobs or jobs["stuck"] or problem_syncs:
        overall = "error"
    elif problem_sources or any(not j["retired"] for j in jobs["failed"]):
        overall = "warning"
    else:
        overall = "healthy"

    return {
        "overall": overall,
        "checked_at": _iso(utcnow()),
        "sources": {
            "window_days": sh["window_days"],
            "summary": sh["summary"],
            "problems": [{
                "id": s["id"], "name": s["name"], "health": s["health"], "reasons": s["reasons"],
                "last_collected_at": s["last_collected_at"], "last_item_at": s["last_item_at"],
            } for s in problem_sources],
        },
        "sync": {
            "total": len(syncs),
            "problems": problem_syncs,
        },
        "background_jobs": jobs,
    }
