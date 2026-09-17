"""影视资料库功能验证 — 在一次性容器里对着临时 Postgres 跑，不碰网络（Emby/TMDb 都用构造数据）"""
import json
import sys

sys.path.insert(0, "/app")
import app.models  # noqa: F401

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.api.routes import films as films_routes
from app.api.routes import sync as sync_routes
from app.models.content import ContentItem, SourceType
from app.models.film import WatchLog, WatchRecord
from app.services.film_library import (
    get_or_create_film_source, upsert_films, mark_missing_from_emby, serialize_film,
)
from app.services.sync.emby import _normalize_item, _merge_duplicates

test_app = FastAPI()
test_app.include_router(films_routes.router, prefix="/api/films")
test_app.include_router(sync_routes.router, prefix="/api/sync")
client = TestClient(test_app)

failures = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def emby_item(id_, name, year, kind="Movie", tmdb=None, played=False, play_count=0, pos=0, runtime_min=100,
              last_played=None, genres=None, overview="x", director="Someone"):
    ticks = runtime_min * 60 * 10_000_000
    item = {
        "Id": id_, "Name": name, "Type": kind, "ProductionYear": year, "PremiereDate": f"{year}-05-01T00:00:00.0000000Z",
        "Overview": overview, "Genres": genres or ["剧情"], "RunTimeTicks": ticks, "CommunityRating": 7.5,
        "People": [{"Name": director, "Type": "Director"}, {"Name": "Actor A", "Type": "Actor"}],
        "ProviderIds": ({"Tmdb": tmdb} if tmdb else {}), "ImageTags": {"Primary": "abc"},
        "DateCreated": "2026-04-05T10:00:00.0000000Z", "ProductionLocations": ["US"],
        "UserData": {"Played": played, "PlayCount": play_count, "PlaybackPositionTicks": pos,
                     "LastPlayedDate": last_played, "IsFavorite": False},
    }
    return item


with SessionLocal() as db:
    emby_src = get_or_create_film_source(db, SourceType.SYNC_EMBY.value)

    # ── 第一次同步：含重复副本、已播完、未刮到 TMDb ID、剧集 ──
    items = [
        emby_item("6188", "银翼杀手2049", 2017, tmdb="335984", play_count=6, pos=int(0.22 * 164 * 60 * 1e7), runtime_min=164, last_played="2026-09-14T04:42:37.0000000Z"),
        emby_item("9229", "银翼杀手2049", 2017, tmdb="335984", play_count=0, runtime_min=164, overview=""),
        emby_item("6158", "伊豆的舞女", 1974, tmdb="41255", played=True, play_count=1, last_played="2026-04-06T00:00:00.0000000Z"),
        emby_item("9230", "破事儿", 2007, tmdb=None),
        emby_item("2766", "汉武大帝", 2005, kind="Series", tmdb="70000"),
        emby_item("6157", "奥本海默", 2023, tmdb="872585"),
    ]
    films = _merge_duplicates([_normalize_item(it, "2026-09-16T00:00:00") for it in items])
    check(len(films) == 5, f"重复副本合并后 5 条 (got {len(films)})")
    br = next(f for f in films if f["external_id"] == "tmdb:movie:335984")
    check(sorted(br["emby"]["item_ids"]) == ["6188", "9229"] and br["emby"]["play_count"] == 6 and br["emby"]["progress"] == 0.22,
          f"合并取 play_count 和/进度最大: {br['emby']}")
    check(next(f for f in films if f["title"] == "破事儿")["external_id"] == "emby:9230", "无 TMDb ID 兜底 emby:<id>")
    check(next(f for f in films if f["title"] == "汉武大帝")["kind"] == "series", "Series → kind=series")

    stats = upsert_films(db, emby_src, films)
    check(stats["new_films"] == 5 and stats["autofilled"] == 1, f"首轮 upsert: {stats}")

    def rec(title):
        c = db.query(ContentItem).filter(ContentItem.title == title).first()
        r = db.query(WatchRecord).filter(WatchRecord.content_id == c.id).first()
        return c, r

    c, r = rec("伊豆的舞女")
    check(r.status == "watched" and r.status_source == "emby_autofill" and str(r.watched_at) == "2026-04-06", f"played=true 自动填看过: {r.status}/{r.status_source}/{r.watched_at}")
    check(len(r.logs) == 1 and str(r.logs[0].watched_at) == "2026-04-06" and r.logs[0].watched_precision == "day", "自动填看过建一条观看记录（真实播放日期）")
    c, r = rec("银翼杀手2049")
    check(r.status == "unmarked", "0%~22% 播放不自动填")
    check(c.url == "https://www.themoviedb.org/movie/335984" and c.author == "Someone", f"url/author 冗余: {c.url} {c.author}")

    # ── 用户手动标记，后续同步不覆盖 ──
    resp = client.put(f"/api/films/{c.id}/record", json={"status": "dropped", "my_rating": 6, "comment": "看不下去"}).json()
    check(resp["code"] == 0 and resp["data"]["record"]["status"] == "dropped" and resp["data"]["record"]["status_source"] == "manual", f"PUT record: {resp['message']}")
    check(resp["data"]["record"]["comment"] == "看不下去" and resp["data"]["record"]["log_count"] == 1 and resp["data"]["record"]["logs"][0]["my_rating"] == 6, "评分/短评落到观看记录，请求显式带 status 时不改状态")
    bad = client.put(f"/api/films/{c.id}/record", json={"my_rating": 11})
    check(bad.status_code == 422 or bad.json().get("code") == 400, f"评分越界被拒: http={bad.status_code}")

    # 待看（backlog）：没看过、排在想看之后；Emby played 也不自动填
    c, r = rec("破事儿")
    resp = client.put(f"/api/films/{c.id}/record", json={"status": "backlog"}).json()
    check(resp["code"] == 0 and resp["data"]["record"]["status"] == "backlog" and resp["data"]["record"]["log_count"] == 0, f"标记待看: {resp['message']}")

    # 第二轮：银翼杀手 played=true，破事儿补上 TMDb ID（且 played=true），奥本海默从库里消失
    items2 = [
        emby_item("6188", "银翼杀手2049", 2017, tmdb="335984", played=True, play_count=7, runtime_min=164, last_played="2026-09-17T00:00:00.0000000Z"),
        emby_item("6158", "伊豆的舞女", 1974, tmdb="41255", played=True, play_count=1, last_played="2026-04-06T00:00:00.0000000Z"),
        emby_item("9230", "破事儿", 2007, tmdb="26039", played=True, play_count=1),
        emby_item("2766", "汉武大帝", 2005, kind="Series", tmdb="70000"),
    ]
    films2 = _merge_duplicates([_normalize_item(it, "2026-09-17T00:00:00") for it in items2])
    db.expire_all()  # PUT 走的是另一个 session，刷新本 session 的缓存
    stats2 = upsert_films(db, emby_src, films2)
    removed = mark_missing_from_emby(db, stats2["content_ids"])
    check(stats2["new_films"] == 0 and stats2["updated_films"] == 4 and stats2["autofilled"] == 0, f"第二轮全部命中既有记录且无自动填充: {stats2}")
    db.expire_all()
    c, r = rec("银翼杀手2049")
    check(r.status == "dropped" and r.status_source == "manual" and c.raw_data["emby"]["played"] is True, "手动标记不被 Emby played 覆盖，但 emby 事实已更新")
    c, r = rec("破事儿")
    check(c.external_id == "tmdb:movie:26039" and db.query(ContentItem).filter(ContentItem.title == "破事儿").count() == 1, f"emby:<id> 升级为 tmdb 且不重复: {c.external_id}")
    check(r.status == "backlog" and r.status_source == "manual", f"待看不被 Emby played 自动填成看过: {r.status}")
    c, r = rec("奥本海默")
    check(removed == 1 and c.raw_data["emby"]["in_library"] is False, f"消失的片标 in_library=false (removed={removed})")

    # ── 手工添加 / 批量标记（无 TMDb key → 骨架） ──
    resp = client.post("/api/films", json={"title": "一一", "year": 2000, "status": "watched", "my_rating": 10}).json()
    check(resp["code"] == 0 and resp["data"]["record"]["status"] == "watched" and resp["data"]["external_id"].startswith("manual:"), f"手工添加骨架: {resp['message']}")
    yiyi_id = resp["data"]["content_id"]
    dup = client.post("/api/films", json={"title": "一一", "year": 2000}).json()
    check(dup["data"]["content_id"] == yiyi_id, "同片名+年份不重复创建")

    resp = client.post("/api/films/records/batch", json={"items": [
        {"tmdb_id": "603", "kind": "movie", "title": "黑客帝国", "year": 1999, "status": "watched", "my_rating": 9},
        {"content_id": yiyi_id, "status": "watched", "comment": "杨德昌"},
        {"title": "牯岭街少年杀人事件", "year": 1991, "status": "want"},
        {"status": "watched"},
    ]}).json()
    oks = [x["ok"] for x in resp["data"]]
    check(oks == [True, True, True, False], f"批量标记 3 成 1 败: {oks}")
    c, r = rec("黑客帝国")
    check(c.external_id == "tmdb:movie:603" and r.my_rating == 9 and r.status_source == "manual", "tmdb_id 骨架 + 评分")

    # 之后 Emby 同步到黑客帝国（同 TMDb ID）→ 合并进同一条，手动标记保留
    films3 = [_normalize_item(emby_item("6174", "黑客帝国", 1999, tmdb="603", played=True, play_count=1), "2026-09-18T00:00:00")]
    db.expire_all()
    s3 = upsert_films(db, emby_src, films3)
    db.expire_all()
    c, r = rec("黑客帝国")
    check(s3["new_films"] == 0 and c.raw_data["emby"]["in_library"] is True and r.status_source == "manual" and "emby" in c.raw_data["sources"],
          f"手工记录被 Emby 同步命中并合并: sources={c.raw_data['sources']}")

    # ── 列表 / 筛选 / 统计 ──
    lst = client.get("/api/films", params={"status": "watched"}).json()
    titles = sorted(f["title"] for f in lst["data"])
    check(titles == ["一一", "伊豆的舞女", "黑客帝国"], f"status=watched 列表: {titles}")
    lst = client.get("/api/films", params={"in_emby": "false"}).json()
    titles = sorted(f["title"] for f in lst["data"])
    check(titles == ["一一", "奥本海默", "牯岭街少年杀人事件"], f"in_emby=false 列表: {titles}")
    lst = client.get("/api/films", params={"status": "backlog"}).json()
    check([f["title"] for f in lst["data"]] == ["破事儿"], "status=backlog 列表")
    lst = client.get("/api/films", params={"status": "unmarked"}).json()
    check("破事儿" not in [f["title"] for f in lst["data"]], "status=unmarked 不含待看")
    lst = client.get("/api/films", params={"kind": "series"}).json()
    check([f["title"] for f in lst["data"]] == ["汉武大帝"], "kind=series")
    lst = client.get("/api/films", params={"q": "someone"}).json()
    check(lst["total"] >= 5, f"按导演模糊搜索: {lst['total']}")
    lst = client.get("/api/films", params={"year_from": 2000, "year_to": 2010, "sort": "year", "order": "asc"}).json()
    check([f["year"] for f in lst["data"]] == [2000, 2005, 2007], f"年份区间+排序: {[f['year'] for f in lst['data']]}")
    st = client.get("/api/films/stats").json()["data"]
    check(st["total"] == 8 and st["by_status"]["watched"] == 3 and st["by_status"].get("backlog") == 1 and st["in_emby"] == 5 and st["by_kind"]["series"] == 1, f"stats: {st}")
    lst = client.get("/api/films").json()["data"]
    check(lst[-1]["title"] == "银翼杀手2049", f"默认排序弃了沉底: {[f['title'] for f in lst]}")
    lst = client.get("/api/films", params={"sort": "my_rating"}).json()["data"]
    check(lst[0]["title"] == "一一" and lst[-1]["title"] == "银翼杀手2049", f"按评分排序弃了（有评分）仍沉底: {[(f['title'], f['record']['my_rating']) for f in lst]}")
    check(client.get("/api/films/search", params={"q": "x"}).json()["code"] == 400, "未配置 TMDb key → search 400")
    det = client.get(f"/api/films/{yiyi_id}").json()["data"]
    check(det["record"]["comment"] == "杨德昌" and det["poster_url"] is None, "详情含最近一次感想；骨架无海报")
    check(det["record"]["log_count"] == 1 and det["record"]["logs"][0]["note"] == "杨德昌" and det["record"]["logs"][0]["my_rating"] == 10, f"手工添加时的评分与批量短评合并进同一条观看记录: {det['record']['logs']}")

    # ── 多次观看：再记一次 → 最近一次在前，片级缓存取最近一次 ──
    first_log = det["record"]["logs"][0]["id"]
    resp = client.post(f"/api/films/{yiyi_id}/logs", json={"watched_at": "2026-09", "my_rating": 8, "note": "十年后重看，更懂 NJ 了"}).json()
    r2 = resp["data"]["record"]
    check(resp["code"] == 0 and r2["log_count"] == 2 and r2["logs"][0]["note"].startswith("十年后") and r2["logs"][0]["watched_label"] == "2026-09", f"再记一次: {resp['message']} {r2['watched_label']}")
    check(r2["my_rating"] == 8 and r2["watched_at"] == "2026-09-01" and r2["watched_precision"] == "month" and r2["comment"].startswith("十年后"), f"片级缓存=最近一次: rating={r2['my_rating']} at={r2['watched_at']}")
    lst = client.get("/api/films", params={"q": "一一"}).json()["data"][0]["record"]
    check(lst["log_count"] == 2 and lst["my_rating"] == 8 and "logs" not in lst, "列表精简输出带 log_count 与最近一次缓存")
    # 修改旧的那次：改日期到 2015，最近一次仍是 2026-09
    resp = client.put(f"/api/films/{yiyi_id}/logs/{first_log}", json={"watched_at": "2015", "my_rating": 10}).json()
    r3 = resp["data"]["record"]
    check(resp["code"] == 0 and r3["logs"][1]["id"] == first_log and r3["logs"][1]["watched_label"] == "2015" and r3["my_rating"] == 8, "改旧记录不影响最近一次缓存")
    # 重看但没打分：评分沿用最近一次打过分的
    resp = client.put(f"/api/films/{yiyi_id}/record", json={"rewatch": True, "comment": "第三次"}).json()
    r4 = resp["data"]["record"]
    from datetime import date as _date
    check(r4["log_count"] == 3 and r4["comment"] == "第三次" and r4["my_rating"] == 8 and r4["watched_label"] == _date.today().isoformat() and r4["watched_precision"] == "day",
          f"rewatch 默认日期=今天、未打分沿用上次评分: {r4['my_rating']} {r4['watched_label']}")
    resp = client.post(f"/api/films/{yiyi_id}/logs", json={}).json()["data"]["record"]
    check(resp["log_count"] == 4 and resp["logs"][0]["watched_label"] == _date.today().isoformat(), "POST /logs 不带日期默认今天")
    client.delete(f"/api/films/{yiyi_id}/logs/{resp['logs'][0]['id']}")
    bad = client.put(f"/api/films/{yiyi_id}/logs/{first_log}", json={"watched_at": "abc"}).json()
    check(bad["code"] == 400, "观看记录日期格式错误 400")
    # 删掉第三次 → 回到 2 条，缓存回到 2026-09 那次
    third = next(l["id"] for l in r4["logs"] if l["note"] == "第三次")
    resp = client.delete(f"/api/films/{yiyi_id}/logs/{third}").json()
    check(resp["code"] == 0 and resp["data"]["record"]["log_count"] == 2 and resp["data"]["record"]["watched_label"] == "2026-09", "删一次观看后缓存回退")
    check(client.delete(f"/api/films/{yiyi_id}/logs/{third}").json()["code"] == 404, "重复删除 404")
    # 打分即看过：想看 + 打分 → 看过、建观看记录、日期空
    c, r = rec("牯岭街少年杀人事件")
    resp = client.put(f"/api/films/{c.id}/record", json={"my_rating": 9}).json()["data"]["record"]
    check(resp["status"] == "watched" and resp["log_count"] == 1 and resp["watched_at"] is None and resp["watched_label"] == "时间不详", f"想看+打分→看过且日期空: {resp['status']} {resp['watched_label']}")
    # 待看 + 打分 → 看过；再改回待看
    c, r = rec("破事儿")
    resp = client.put(f"/api/films/{c.id}/record", json={"my_rating": 6}).json()["data"]["record"]
    check(resp["status"] == "watched", f"待看+打分→看过: {resp['status']}")
    resp = client.put(f"/api/films/{c.id}/record", json={"status": "backlog"}).json()["data"]["record"]
    check(resp["status"] == "backlog", "改回待看")
    # 点看过不带日期 → 建一条空观看记录
    c, r = rec("汉武大帝")
    resp = client.put(f"/api/films/{c.id}/record", json={"status": "watched"}).json()["data"]["record"]
    check(resp["log_count"] == 1 and resp["watched_label"] == "时间不详" and resp["my_rating"] is None, "点看过→一条空观看记录")
    resp = client.put(f"/api/films/{c.id}/record", json={"watched_at": "release"}).json()["data"]["record"]
    check(resp["watched_precision"] == "release" and resp["watched_label"] == "≈2005（上映）", f"主动选不记得→按上映: {resp['watched_label']}")
    poster = client.get(f"/api/films/{c.id}/poster")
    check(poster.status_code == 404, f"未配 Emby 凭证时海报 404 (got {poster.status_code})")

    # 同步页状态含 emby 插件
    sync_status = client.get("/api/sync/status").json()["data"]["plugins"]
    emby_plugin = next(p for p in sync_status if p["source_type"] == "sync.emby")
    check(emby_plugin["configured"] and emby_plugin["stats"]["in_emby"] == 5 and emby_plugin["stats"]["total_items"] == 5 and emby_plugin["category"] == "film", f"sync/status emby 插件: {emby_plugin['stats']}")
    run = client.post("/api/sync/run/sync.emby", json={}).json()
    check(run["code"] == 400, f"未绑凭证触发同步被拒: {run['message']}")

    # 删除
    rid = db.query(WatchRecord).filter(WatchRecord.content_id == yiyi_id).first().id
    d = client.delete(f"/api/films/{yiyi_id}").json()
    db.expire_all()
    check(d["code"] == 0 and db.query(WatchRecord).filter(WatchRecord.content_id == yiyi_id).count() == 0
          and db.query(WatchLog).filter(WatchLog.record_id == rid).count() == 0, "删除级联 watch_records 与 watch_logs")

# ── MCP 工具 ──
try:
    import mcp_server
    out = json.loads(mcp_server.list_films(status="watched"))
    check(out["total_count"] == 4 and all("record" in i and "log_count" in i["record"] for i in out["items"]), f"MCP list_films: {out['total_count']}")
    out = json.loads(mcp_server.mark_films([{"title": "海上钢琴师", "year": 1998, "status": "watched", "my_rating": 8}, {"tmdb_id": "603", "status": "watched"}]))
    check(out["ok"] == 2, f"MCP mark_films: {out}")
    out = json.loads(mcp_server.list_films(keyword="海上"))
    check(out["items"][0]["record"]["my_rating"] == 8, "MCP 写入后可读")
    out = json.loads(mcp_server.mark_films([{"title": "海上钢琴师", "year": 1998, "rewatch": True, "watched_at": "2026-09-17", "my_rating": 10, "comment": "重看"}]))
    out = json.loads(mcp_server.list_films(keyword="海上"))
    check(out["items"][0]["record"]["log_count"] == 2 and out["items"][0]["record"]["my_rating"] == 10 and out["items"][0]["record"]["comment"] == "重看", f"MCP rewatch: {out['items'][0]['record']}")
    out = json.loads(mcp_server.list_films(status="backlog"))
    check(out["total_count"] == 1, f"MCP list_films backlog: {out['total_count']}")
    out = json.loads(mcp_server.search_film("x"))
    check("error" in out, "MCP search_film 无 key 报错")
except Exception as e:  # noqa: BLE001
    check(False, f"MCP 工具异常: {e!r}")

print("\n==== RESULT:", "ALL PASS" if not failures else f"{len(failures)} FAILED")
for f in failures:
    print("  -", f)
sys.exit(1 if failures else 0)
