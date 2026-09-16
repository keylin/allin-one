# 影视资料库验证脚本

`film_test.py` 对着临时 Postgres 验证 Emby 同步归一化/合并、upsert 覆盖规则（手动标记不被 Emby 覆盖、played 只填空）、
`emby:<id>` → `tmdb:*` 升级、in_library 回收、手工添加/批量标记、列表筛选/统计、MCP 三个工具。不访问 Emby/TMDb。

```bash
docker run -d --name film-test-pg -e POSTGRES_PASSWORD=x -e POSTGRES_USER=allinone -e POSTGRES_DB=allinone \
  -p 127.0.0.1:55432:5432 postgres:17-alpine
docker run --rm --network host -v "$PWD/backend:/app" \
  -v "$PWD/scripts/verify/film-library/film_test.py:/app/film_test.py:ro" \
  -e DATABASE_URL=postgresql://allinone:x@127.0.0.1:55432/allinone allin-one:home-server \
  sh -c 'alembic upgrade head && python film_test.py'
docker rm -f film-test-pg
```

期望输出末尾 `==== RESULT: ALL PASS`。
