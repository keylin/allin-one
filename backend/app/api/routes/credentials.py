"""Credentials API - 平台凭证管理"""

import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
import httpx

from app.core.database import get_db
from app.models.credential import PlatformCredential
from app.models.content import SourceConfig
from app.schemas.credential import CredentialCreate, CredentialUpdate, CredentialResponse
from app.schemas.base import error_response

logger = logging.getLogger(__name__)
router = APIRouter()

_MASK_PATTERN = re.compile(r'^\*{3}\w{0,4}$')


def _mask_value(value: str) -> str:
    """掩码敏感值，只显示末 4 位"""
    if not value or len(value) <= 4:
        return "***"
    return f"***{value[-4:]}"


def _credential_to_response(cred: PlatformCredential, db: Session) -> dict:
    """转换 ORM 对象为响应 dict，掩码 credential_data"""
    source_count = db.query(func.count(SourceConfig.id)).filter(
        SourceConfig.credential_id == cred.id
    ).scalar() or 0

    data = CredentialResponse.model_validate(cred).model_dump()
    data["credential_data"] = _mask_value(cred.credential_data)
    data["source_count"] = source_count
    return data


# ---- Options (轻量下拉列表，放在 /{id} 路由之前) ----

@router.get("/options")
async def list_credential_options(
    platform: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """轻量级凭证列表，供下拉框使用"""
    query = db.query(
        PlatformCredential.id,
        PlatformCredential.display_name,
        PlatformCredential.platform,
        PlatformCredential.status,
    )
    if platform:
        query = query.filter(PlatformCredential.platform == platform)
    rows = query.order_by(PlatformCredential.display_name).all()
    return {
        "code": 0,
        "data": [{"id": r.id, "display_name": r.display_name, "platform": r.platform, "status": r.status} for r in rows],
        "message": "ok",
    }


# ---- B站 QR 登录 (字面路径，必须在 /{id} 之前) ----

@router.post("/bilibili/qrcode/generate")
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


@router.get("/bilibili/qrcode/poll")
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
                existing.updated_at = datetime.now(timezone.utc)
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


# ---- CRUD ----

@router.get("")
async def list_credentials(
    platform: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """获取凭证列表"""
    query = db.query(PlatformCredential)
    if platform:
        query = query.filter(PlatformCredential.platform == platform)
    creds = query.order_by(PlatformCredential.created_at.desc()).all()
    return {
        "code": 0,
        "data": [_credential_to_response(c, db) for c in creds],
        "message": "ok",
    }


@router.post("")
async def create_credential(body: CredentialCreate, db: Session = Depends(get_db)):
    """手动创建凭证"""
    cred = PlatformCredential(**body.model_dump())
    db.add(cred)
    db.commit()
    db.refresh(cred)
    logger.info(f"Credential created: {cred.id} ({cred.display_name}, platform={cred.platform})")

    # Best-effort RSSHub sync for Twitter
    if cred.platform == "twitter":
        try:
            from app.services.rsshub_sync import sync_twitter_to_rsshub
            sync_result = sync_twitter_to_rsshub(cred.credential_data)
            logger.info(f"Twitter RSSHub sync result: {sync_result}")
        except Exception as e:
            logger.warning(f"Twitter RSSHub sync failed (non-critical): {e}")

    return {"code": 0, "data": _credential_to_response(cred, db), "message": "ok"}


@router.get("/{credential_id}")
async def get_credential(credential_id: str, db: Session = Depends(get_db)):
    """获取单条凭证详情"""
    cred = db.get(PlatformCredential, credential_id)
    if not cred:
        return error_response(404, "Credential not found")
    return {"code": 0, "data": _credential_to_response(cred, db), "message": "ok"}


@router.put("/{credential_id}")
async def update_credential(credential_id: str, body: CredentialUpdate, db: Session = Depends(get_db)):
    """更新凭证"""
    cred = db.get(PlatformCredential, credential_id)
    if not cred:
        return error_response(404, "Credential not found")

    update_data = body.model_dump(exclude_unset=True)

    # 跳过掩码值
    if "credential_data" in update_data:
        val = update_data["credential_data"]
        if val and _MASK_PATTERN.match(val):
            del update_data["credential_data"]

    for key, value in update_data.items():
        setattr(cred, key, value)

    cred.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cred)

    logger.info(f"Credential updated: {credential_id} (fields={list(update_data.keys())})")

    # Best-effort RSSHub sync for Twitter when credential_data changed
    if cred.platform == "twitter" and "credential_data" in update_data:
        try:
            from app.services.rsshub_sync import sync_twitter_to_rsshub
            sync_result = sync_twitter_to_rsshub(cred.credential_data)
            logger.info(f"Twitter RSSHub sync result: {sync_result}")
        except Exception as e:
            logger.warning(f"Twitter RSSHub sync failed (non-critical): {e}")

    return {"code": 0, "data": _credential_to_response(cred, db), "message": "ok"}


@router.delete("/{credential_id}")
async def delete_credential(credential_id: str, db: Session = Depends(get_db)):
    """删除凭证（检查引用）"""
    cred = db.get(PlatformCredential, credential_id)
    if not cred:
        return error_response(404, "Credential not found")

    source_count = db.query(func.count(SourceConfig.id)).filter(
        SourceConfig.credential_id == credential_id
    ).scalar() or 0

    if source_count > 0:
        return {
            "code": 1,
            "data": {"source_count": source_count},
            "message": f"该凭证被 {source_count} 个数据源引用，请先解除关联",
        }

    db.delete(cred)
    db.commit()
    logger.info(f"Credential deleted: {credential_id}")
    return {"code": 0, "data": None, "message": "ok"}


# ---- 凭证操作 ----

@router.post("/{credential_id}/check")
async def check_credential(credential_id: str, db: Session = Depends(get_db)):
    """验证凭证是否有效"""
    cred = db.get(PlatformCredential, credential_id)
    if not cred:
        return error_response(404, "Credential not found")

    if cred.platform == "bilibili":
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.bilibili.com/x/web-interface/nav",
                    headers={
                        "Cookie": cred.credential_data,
                        "User-Agent": "Mozilla/5.0",
                    },
                )
                data = resp.json()

            if data.get("code") == 0 and data.get("data", {}).get("isLogin"):
                uname = data["data"].get("uname", "")
                mid = str(data["data"].get("mid", ""))
                cred.status = "active"
                cred.updated_at = datetime.now(timezone.utc)
                # 自动补写 extra_info（uid/uname）
                if mid:
                    try:
                        extra = json.loads(cred.extra_info or "{}")
                    except (json.JSONDecodeError, TypeError):
                        extra = {}
                    extra["uid"] = mid
                    if uname:
                        extra["username"] = uname
                    cred.extra_info = json.dumps(extra, ensure_ascii=False)
                    # 更新 display_name（如果还是迁移默认名）
                    if "迁移自" in (cred.display_name or ""):
                        cred.display_name = f"B站 {uname}" if uname else f"B站账号 {mid}"
                db.commit()
                return {"code": 0, "data": {"valid": True, "username": uname, "uid": mid}, "message": f"凭证有效 ({uname})"}
            else:
                cred.status = "expired"
                cred.updated_at = datetime.now(timezone.utc)
                db.commit()
                return {"code": 0, "data": {"valid": False}, "message": "凭证已失效"}
        except Exception as e:
            return error_response(500, f"检测失败: {str(e)}")
    elif cred.platform == "twitter":
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.x.com/1.1/account/verify_credentials.json",
                    headers={
                        "Authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
                        "Cookie": f"auth_token={cred.credential_data}",
                        "User-Agent": "Mozilla/5.0",
                    },
                )
                data = resp.json()

            if resp.status_code == 200 and data.get("screen_name"):
                screen_name = data["screen_name"]
                cred.status = "active"
                cred.updated_at = datetime.now(timezone.utc)
                try:
                    extra = json.loads(cred.extra_info or "{}")
                except (json.JSONDecodeError, TypeError):
                    extra = {}
                extra["screen_name"] = screen_name
                cred.extra_info = json.dumps(extra, ensure_ascii=False)
                db.commit()
                return {"code": 0, "data": {"valid": True, "username": f"@{screen_name}"}, "message": f"凭证有效 (@{screen_name})"}
            else:
                cred.status = "expired"
                cred.updated_at = datetime.now(timezone.utc)
                db.commit()
                return {"code": 0, "data": {"valid": False}, "message": "凭证已失效"}
        except Exception as e:
            return error_response(500, f"检测失败: {str(e)}")
    else:
        return error_response(400, f"暂不支持 {cred.platform} 平台的凭证检测")


@router.post("/{credential_id}/sync-rsshub")
async def sync_rsshub(credential_id: str, db: Session = Depends(get_db)):
    """手动触发 RSSHub 同步"""
    cred = db.get(PlatformCredential, credential_id)
    if not cred:
        return error_response(404, "Credential not found")

    if cred.platform == "bilibili":
        try:
            extra = json.loads(cred.extra_info or "{}")
        except (json.JSONDecodeError, TypeError):
            extra = {}

        uid = extra.get("uid", "")
        if not uid:
            return error_response(400, "凭证缺少 uid 信息，无法同步 RSSHub")

        try:
            from app.services.rsshub_sync import sync_bilibili_to_rsshub
            result = sync_bilibili_to_rsshub(uid, cred.credential_data)
            return {"code": 0, "data": result, "message": "同步完成"}
        except Exception as e:
            logger.exception(f"RSSHub sync failed for credential {credential_id}")
            return error_response(500, f"同步失败: {str(e)}")
    elif cred.platform == "twitter":
        try:
            from app.services.rsshub_sync import sync_twitter_to_rsshub
            result = sync_twitter_to_rsshub(cred.credential_data)
            return {"code": 0, "data": result, "message": "同步完成"}
        except Exception as e:
            logger.exception(f"RSSHub sync failed for credential {credential_id}")
            return error_response(500, f"同步失败: {str(e)}")
    else:
        return error_response(400, f"暂不支持 {cred.platform} 平台同步 RSSHub")
