"""Credentials API - 平台凭证管理"""

import json
import logging
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
import httpx

from app.core.database import get_db
from app.core.time import utcnow
from app.models.credential import PlatformCredential
from app.models.content import SourceConfig
from app.schemas.credential import CredentialCreate, CredentialUpdate, CredentialResponse
from app.schemas.base import error_response

logger = logging.getLogger(__name__)
router = APIRouter()

_MASK_PATTERN = re.compile(r'^\*{3}\w{0,4}$')


async def _validate_credential(cred: PlatformCredential) -> tuple[str | None, dict]:
    """验证凭证有效性，返回 (status, extra_updates).

    status: "active" / "expired" / None (不支持的平台)
    extra_updates: 需要更新到 cred 上的附加字段 (extra_info, display_name 等)
    支持的平台验证失败时抛异常，由调用方决定处理策略。
    """
    if cred.platform == "bilibili":
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
            extra = {}
            if mid:
                try:
                    extra = json.loads(cred.extra_info or "{}")
                except (json.JSONDecodeError, TypeError):
                    extra = {}
                extra["uid"] = mid
                if uname:
                    extra["username"] = uname
            updates = {}
            if mid:
                updates["extra_info"] = json.dumps(extra, ensure_ascii=False)
                if "迁移自" in (cred.display_name or ""):
                    updates["display_name"] = f"B站 {uname}" if uname else f"B站账号 {mid}"
            return "active", updates
        else:
            return "expired", {}

    elif cred.platform == "twitter":
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
            try:
                extra = json.loads(cred.extra_info or "{}")
            except (json.JSONDecodeError, TypeError):
                extra = {}
            extra["screen_name"] = screen_name
            return "active", {"extra_info": json.dumps(extra, ensure_ascii=False)}
        else:
            return "expired", {}

    elif cred.platform == "wechat_read":
        from app.services.sync.wechat_read import WechatReadFetcher
        fetcher = WechatReadFetcher()
        valid, reason = await fetcher.validate_credential(cred.credential_data)
        status = "active" if valid else "expired"
        return status, {"_reason": reason} if reason else {}

    else:
        return None, {}


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

    # 创建后 best-effort 验证
    validation_reason = ""
    try:
        validated_status, extra_updates = await _validate_credential(cred)
        if validated_status:
            validation_reason = extra_updates.pop("_reason", "")
            cred.status = validated_status
            cred.updated_at = utcnow()
            for key, value in extra_updates.items():
                setattr(cred, key, value)
            db.commit()
            db.refresh(cred)
    except Exception as e:
        logger.warning(f"Post-create validation failed for {cred.platform} (non-critical): {e}")

    # Best-effort RSSHub sync for Twitter
    if cred.platform == "twitter":
        try:
            from app.services.rsshub_sync import sync_twitter_to_rsshub
            sync_result = sync_twitter_to_rsshub(cred.credential_data)
            logger.info(f"Twitter RSSHub sync result: {sync_result}")
        except Exception as e:
            logger.warning(f"Twitter RSSHub sync failed (non-critical): {e}")

    # 凭证已保存但验证失败时，返回具体原因
    resp_data = _credential_to_response(cred, db)
    if cred.status == "expired" and validation_reason:
        resp_data["validation_reason"] = validation_reason
        if validation_reason == "missing_fields":
            msg = "凭证已保存，但 Cookie 不完整（缺少 wr_skey/wr_vid）。请从浏览器 Network 请求头获取完整 Cookie"
        elif validation_reason == "expired":
            msg = "凭证已保存，但 Cookie 已过期（有效期约 1.5 小时），请重新获取"
        else:
            msg = "凭证已保存，但验证未通过"
        return {"code": 0, "data": resp_data, "message": msg}

    return {"code": 0, "data": resp_data, "message": "ok"}


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

    cred.updated_at = utcnow()
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
async def delete_credential(
    credential_id: str,
    force: bool = Query(False),
    db: Session = Depends(get_db),
):
    """删除凭证（检查引用，force=True 时解除关联后删除）"""
    cred = db.get(PlatformCredential, credential_id)
    if not cred:
        return error_response(404, "Credential not found")

    source_count = db.query(func.count(SourceConfig.id)).filter(
        SourceConfig.credential_id == credential_id
    ).scalar() or 0

    if source_count > 0:
        if not force:
            return {
                "code": 1,
                "data": {"source_count": source_count},
                "message": f"该凭证被 {source_count} 个数据源引用，请先解除关联",
            }
        # force=True: 解除所有引用后删除
        db.query(SourceConfig).filter(
            SourceConfig.credential_id == credential_id
        ).update({"credential_id": None})
        logger.info(f"Force delete: unlinked {source_count} sources from credential {credential_id}")

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

    try:
        validated_status, extra_updates = await _validate_credential(cred)
    except Exception as e:
        return error_response(500, f"检测失败: {str(e)}")

    if validated_status is None:
        return error_response(400, f"暂不支持 {cred.platform} 平台的凭证检测")

    # 提取内部 reason（不持久化到 DB）
    reason = extra_updates.pop("_reason", "")

    cred.status = validated_status
    cred.updated_at = utcnow()
    for key, value in extra_updates.items():
        setattr(cred, key, value)
    db.commit()

    if validated_status == "active":
        return {"code": 0, "data": {"valid": True}, "message": "凭证有效"}

    # 根据 reason 返回具体提示
    if reason == "missing_fields":
        msg = "Cookie 不完整，缺少关键字段（wr_skey/wr_vid）。请从浏览器 Network 请求头获取完整 Cookie"
    elif reason == "expired":
        msg = "Cookie 已过期（有效期约 1.5 小时），请重新登录 weread.qq.com 获取"
    else:
        msg = "凭证已失效"
    return {"code": 0, "data": {"valid": False, "reason": reason or "expired"}, "message": msg}


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
