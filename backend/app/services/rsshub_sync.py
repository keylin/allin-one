"""RSSHub 凭证同步服务 — 将平台凭证写入 .env 并重启 RSSHub 容器"""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# .env 文件路径: 项目根 .env (容器内 /app/.env)
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _upsert_env_var(env_path: Path, key: str, value: str) -> bool:
    """在 .env 文件中 insert 或 update 一个 key=value

    Returns:
        True if the value was changed, False if unchanged
    """
    lines = []
    found = False
    changed = False

    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"export {key}="):
            old_val = stripped.split("=", 1)[1].strip().strip('"').strip("'")
            if old_val != value:
                new_lines.append(f"{key}={value}\n")
                changed = True
            else:
                new_lines.append(line if line.endswith("\n") else line + "\n")
            found = True
        else:
            new_lines.append(line if line.endswith("\n") else line + "\n")

    if not found:
        # 确保以换行结尾后追加
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"{key}={value}\n")
        changed = True

    if changed:
        env_path.write_text("".join(new_lines), encoding="utf-8")

    return changed


def _get_compose_project_name() -> str | None:
    """从现有 rsshub 容器的标签推断 docker compose project name"""
    container_names = ["allin-dev-rsshub", "allin-rsshub"]
    for name in container_names:
        try:
            result = subprocess.run(
                ["docker", "inspect", name, "--format",
                 '{{index .Config.Labels "com.docker.compose.project"}}'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return None


def _restart_rsshub_container() -> dict:
    """重建 RSSHub 容器以加载新环境变量

    注意: docker compose restart 不会重新读取 env_file，必须用 up -d 重建容器。

    Returns:
        dict with keys: restarted (bool), method (str), error (str|None)
    """
    # 容器内: compose 文件挂载在 /project/ 下
    # 宿主机开发: 从脚本路径回溯到项目根目录
    project_root = Path(__file__).resolve().parents[3]
    compose_files = [
        Path("/project/docker-compose.remote.yml"),  # 容器内挂载路径 (remote)
        Path("/project/docker-compose.yml"),  # 容器内挂载路径 (local dev)
        project_root / "docker-compose.local.yml",
        project_root / "docker-compose.remote.yml",
    ]

    # 使用 docker compose up -d 重建容器（而非 restart），确保 env_file 变更生效
    # 需要指定 project name，否则容器内运行时会用 /project 目录名作为 project name
    for compose_file in compose_files:
        if compose_file.exists():
            try:
                # 从现有 rsshub 容器标签推断 project name
                project_name = _get_compose_project_name()
                cmd = ["docker", "compose", "-f", str(compose_file)]
                if project_name:
                    cmd.extend(["-p", project_name])
                cmd.extend(["up", "-d", "rsshub"])
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0:
                    return {"restarted": True, "method": f"docker compose up -d (project={project_name})", "error": None}
                logger.warning(f"docker compose up -d failed: {result.stderr}")
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.warning(f"docker compose failed: {e}")

    return {"restarted": False, "method": "none", "error": "未找到 compose 文件或 docker 命令不可用"}


def sync_bilibili_to_rsshub(uid: str, cookie_str: str) -> dict:
    """同步 B站 Cookie 到 .env 并重启 RSSHub

    Args:
        uid: B站用户 ID
        cookie_str: 完整 cookie 字符串，如 "SESSDATA=xxx; bili_jct=xxx"

    Returns:
        dict with sync result
    """
    env_key = f"BILIBILI_COOKIE_{uid}"

    logger.info(f"Syncing bilibili cookie to .env: {env_key}")

    env_changed = _upsert_env_var(_ENV_PATH, env_key, cookie_str)

    result = {"env_key": env_key, "env_path": str(_ENV_PATH), "env_changed": env_changed}

    if env_changed:
        restart_result = _restart_rsshub_container()
        result.update(restart_result)
        if restart_result["restarted"]:
            logger.info(f"RSSHub restarted via {restart_result['method']}")
        else:
            logger.warning(f"RSSHub restart failed: {restart_result['error']}")
    else:
        result["restarted"] = False
        result["method"] = "skipped"
        result["error"] = None
        logger.info("Cookie unchanged, skipping RSSHub restart")

    return result


def sync_twitter_to_rsshub(auth_token: str) -> dict:
    """同步 Twitter auth_token 到 .env 并重启 RSSHub

    Args:
        auth_token: Twitter auth_token cookie 值

    Returns:
        dict with sync result
    """
    env_key = "TWITTER_AUTH_TOKEN"

    logger.info(f"Syncing twitter auth_token to .env: {env_key}")

    env_changed = _upsert_env_var(_ENV_PATH, env_key, auth_token)

    result = {"env_key": env_key, "env_path": str(_ENV_PATH), "env_changed": env_changed}

    if env_changed:
        restart_result = _restart_rsshub_container()
        result.update(restart_result)
        if restart_result["restarted"]:
            logger.info(f"RSSHub restarted via {restart_result['method']}")
        else:
            logger.warning(f"RSSHub restart failed: {restart_result['error']}")
    else:
        result["restarted"] = False
        result["method"] = "skipped"
        result["error"] = None
        logger.info("Twitter auth_token unchanged, skipping RSSHub restart")

    return result
