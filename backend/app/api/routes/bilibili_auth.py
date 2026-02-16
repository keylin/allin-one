"""Bilibili QR 登录路由 — 从 credentials.py 提取"""

import json
import logging
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
import httpx

from app.core.database import get_db
from app.core.time import utcnow
from app.models.credential import PlatformCredential

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/qrcode/generate")
async def bilibili_qrcode_generate():
    """生成B站登录二维码"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = resp.json()
        if data.get("code") != 0:
            return {"code": 1, "data": None, "message": f"B站接口错误: {data.get('message', 'unknown')}"}
        return {"code": 0, "data": data["data"], "message": "ok"}
    except Exception as e:
        logger.exception("Failed to generate bilibili qrcode")
        return {"code": 1, "data": None, "message": f"生成二维码失败: {str(e)}"}


@router.get("/qrcode/poll")
async def bilibili_qrcode_poll(
    qrcode_key: str = Query(...),
    db: Session = Depends(get_db),
):
    """轮询B站二维码扫码状态，成功时自动创建/更新凭证"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                params={"qrcode_key": qrcode_key},
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=False,
            )
            data = resp.json()

        if data.get("code") != 0:
            return {"code": 1, "data": None, "message": f"B站接口错误: {data.get('message', 'unknown')}"}

        status_code = data["data"].get("code")
        if status_code == 86101:
            return {"code": 0, "data": {"status": "waiting"}, "message": "等待扫码"}
        elif status_code == 86090:
            return {"code": 0, "data": {"status": "scanned"}, "message": "已扫码，待确认"}
        elif status_code == 86038:
            return {"code": 0, "data": {"status": "expired"}, "message": "二维码已过期"}
        elif status_code == 0:
            # 成功 — 提取凭证
            cookies = resp.cookies
            sessdata = cookies.get("SESSDATA", "")
            bili_jct = cookies.get("bili_jct", "")
            dede_user_id = cookies.get("DedeUserID", "")

            # 某些情况 cookie 在 url 参数中返回
            url_str = data["data"].get("url", "")
            if not sessdata and url_str:
                qs = parse_qs(urlparse(url_str).query)
                sessdata = qs.get("SESSDATA", [""])[0]
                bili_jct = qs.get("bili_jct", [""])[0]
                dede_user_id = dede_user_id or qs.get("DedeUserID", [""])[0]

            cookie_str = f"SESSDATA={sessdata}; bili_jct={bili_jct}"
            uid = dede_user_id or ""

            # 创建或更新 PlatformCredential
            extra = json.dumps({"uid": uid}) if uid else None

            # 查找已有同 uid 的凭证
            existing = None
            if uid:
                for cred in db.query(PlatformCredential).filter(
                    PlatformCredential.platform == "bilibili"
                ).all():
                    try:
                        info = json.loads(cred.extra_info or "{}")
                        if info.get("uid") == uid:
                            existing = cred
                            break
                    except (json.JSONDecodeError, TypeError):
                        pass

            if existing:
                existing.credential_data = cookie_str
                existing.status = "active"
                existing.extra_info = extra
                existing.updated_at = utcnow()
                credential_id = existing.id
            else:
                cred = PlatformCredential(
                    platform="bilibili",
                    credential_type="cookie",
                    credential_data=cookie_str,
                    display_name=f"B站账号 {uid}" if uid else "B站账号",
                    status="active",
                    extra_info=extra,
                )
                db.add(cred)
                db.flush()
                credential_id = cred.id

            db.commit()

            # 异步触发 RSSHub 同步（best effort）
            if uid:
                try:
                    from app.services.rsshub_sync import sync_bilibili_to_rsshub
                    sync_result = sync_bilibili_to_rsshub(uid, cookie_str)
                    logger.info(f"RSSHub sync result: {sync_result}")
                except Exception as e:
                    logger.warning(f"RSSHub sync failed (non-critical): {e}")

            return {
                "code": 0,
                "data": {"status": "success", "cookie": cookie_str, "credential_id": credential_id},
                "message": "登录成功",
            }
        else:
            return {"code": 0, "data": {"status": "unknown", "raw_code": status_code}, "message": "未知状态"}
    except Exception as e:
        logger.exception("Failed to poll bilibili qrcode")
        return {"code": 1, "data": None, "message": f"轮询失败: {str(e)}"}
