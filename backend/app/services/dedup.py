"""内容相似度去重服务

基于 SimHash 算法的标题指纹，用于跨数据源检测相似/重复内容。

原理:
  1. 标题归一化（去标点、lowercase、strip 常见前缀）
  2. 字符 n-gram 分词 → SimHash 64 位指纹
  3. 两条内容的 Hamming 距离 ≤ 阈值 → 判定为相似

性能:
  - 采集时一次性计算并存入 title_hash，后续比较只需位运算
  - 候选范围限定为最近 30 天 + 不同数据源，避免全表扫描
"""

import hashlib
import logging
import re
import struct
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.time import utcnow

logger = logging.getLogger(__name__)

# Hamming 距离阈值: ≤3 表示约 95% 相似 (64 位中最多 3 位不同)
DEFAULT_THRESHOLD = 3


def normalize_title(title: str) -> str:
    """归一化标题，用于相似度计算

    - 全小写
    - 去掉方括号/中括号标签 (如 [视频]、【快讯】)
    - 去掉常见转发/分享前缀
    - 去掉新闻源日期前缀 (如 "格隆汇2月24日｜"、"财联社12月1日电")
    - 去掉快讯前缀 (如 "每经AI快讯，")
    - 去掉括号来源后缀 (如 "（央视新闻）")
    - 去掉破折号来源后缀 (如 "——新华社")
    - 去除标点，只保留 CJK + 字母数字
    """
    if not title:
        return ""
    text = title.lower().strip()
    # 去掉方括号/中括号标签
    text = re.sub(r'[\[【].*?[\]】]', '', text)
    # 去掉常见转发前缀
    text = re.sub(r'^(转发|转载|分享|fwd)[：:\s]+', '', text)
    # 去掉新闻源日期前缀: "XX社/汇/网X月X日[电｜丨| ]"
    text = re.sub(r'^[\w\u4e00-\u9fff]{2,6}\d{1,2}月\d{1,2}日[电｜丨|\s]*', '', text)
    # 去掉快讯前缀: "XX快讯[，：: ]"
    text = re.sub(r'^[\w\u4e00-\u9fff]*?快讯[，：:\s]*', '', text)
    # 去掉括号来源后缀: （央视新闻）(新华社) 等
    text = re.sub(r'[（(][^）)]{1,10}[）)]\s*$', '', text)
    # 去掉破折号来源后缀: ——新华社 等
    text = re.sub(r'[—\-]{1,2}[\w\u4e00-\u9fff]{2,8}\s*$', '', text)
    # 去除标点，保留 CJK 和字母数字
    text = re.sub(r'[^\w\u4e00-\u9fff\u3400-\u4dbf]', '', text)
    return text


def _token_hash(token: str) -> int:
    """将 token 哈希为 64 位有符号整数"""
    h = hashlib.md5(token.encode('utf-8')).digest()
    return struct.unpack('<q', h[:8])[0]


def simhash(text: str, ngram_size: int = 3) -> int | None:
    """计算文本的 64 位 SimHash 指纹

    Args:
        text: 已归一化的文本
        ngram_size: 字符 n-gram 大小

    Returns:
        64 位有符号整数 (适合 PostgreSQL BIGINT)，文本为空时返回 None
    """
    if not text:
        return None

    # 生成字符 n-grams
    if len(text) < ngram_size:
        tokens = [text]
    else:
        tokens = [text[i:i + ngram_size] for i in range(len(text) - ngram_size + 1)]

    # 加权累加
    v = [0] * 64
    for token in tokens:
        h = _token_hash(token)
        for i in range(64):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1

    # 构建指纹 (无符号)
    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= (1 << i)

    # 转为有符号 64 位 (PostgreSQL BIGINT 范围)
    if fingerprint >= (1 << 63):
        fingerprint -= (1 << 64)

    return fingerprint


def hamming_distance(h1: int, h2: int) -> int:
    """计算两个 64 位哈希的 Hamming 距离 (不同位数)"""
    # 转为无符号进行异或
    x = (h1 & 0xFFFFFFFFFFFFFFFF) ^ (h2 & 0xFFFFFFFFFFFFFFFF)
    count = 0
    while x:
        count += 1
        x &= x - 1
    return count


def compute_title_hash(title: str) -> int | None:
    """计算标题的 SimHash 指纹"""
    normalized = normalize_title(title)
    return simhash(normalized)


def find_similar_content(
    db: Session,
    title: str,
    exclude_source_id: str | None = None,
    threshold: int = DEFAULT_THRESHOLD,
    days_lookback: int = 30,
):
    """在已有内容中查找与给定标题相似的条目 (跨数据源)

    Args:
        db: 数据库会话
        title: 待检查的标题
        exclude_source_id: 排除此数据源的内容 (避免同源误判)
        threshold: Hamming 距离阈值，默认 3
        days_lookback: 回溯天数，默认 30 天

    Returns:
        最相似的 ContentItem，未找到返回 None
    """
    from app.models.content import ContentItem

    target_hash = compute_title_hash(title)
    if target_hash is None:
        return None

    # 查询候选: 有 title_hash、不同数据源、最近 N 天
    query = db.query(ContentItem).filter(
        ContentItem.title_hash.isnot(None),
        ContentItem.duplicate_of_id.is_(None),  # 只和"原件"比较
    )
    if exclude_source_id:
        query = query.filter(ContentItem.source_id != exclude_source_id)

    cutoff = utcnow() - timedelta(days=days_lookback)
    candidates = (
        query
        .filter(ContentItem.collected_at >= cutoff)
        .order_by(ContentItem.collected_at.desc())
        .limit(5000)
        .all()
    )

    best_match = None
    best_distance = threshold + 1

    for item in candidates:
        dist = hamming_distance(target_hash, item.title_hash)
        if dist <= threshold and dist < best_distance:
            best_match = item
            best_distance = dist
            if dist == 0:
                break  # 完全匹配，无需继续

    return best_match


def check_and_mark_duplicates(
    db: Session,
    new_items,
    source_id: str | None = None,
    threshold: int = DEFAULT_THRESHOLD,
) -> int:
    """批量检查新内容的标题相似度，标记跨源重复

    在采集任务完成后调用，为每条新内容:
    1. 计算并保存 title_hash
    2. 跨源查找相似内容
    3. 找到时设置 duplicate_of_id

    Args:
        db: 数据库会话
        new_items: 新采集的 ContentItem 列表
        source_id: 当前数据源 ID (用于排除同源)
        threshold: Hamming 距离阈值

    Returns:
        标记为重复的条目数
    """
    if not new_items:
        return 0

    duplicates_found = 0

    for item in new_items:
        # 1. 计算标题哈希
        item.title_hash = compute_title_hash(item.title)

        if item.title_hash is None:
            continue

        # 2. 查找跨源相似内容
        similar = find_similar_content(
            db, item.title,
            exclude_source_id=source_id,
            threshold=threshold,
        )

        if similar:
            item.duplicate_of_id = similar.id
            duplicates_found += 1
            logger.info(
                f"[dedup] 发现相似内容: '{item.title[:40]}' ↔ '{similar.title[:40]}' "
                f"(distance={hamming_distance(item.title_hash, similar.title_hash)})"
            )

    if duplicates_found > 0:
        db.flush()
        logger.info(f"[dedup] 本批次 {len(new_items)} 条中标记 {duplicates_found} 条为重复")

    return duplicates_found
