/**
 * 外部阅读源平台注册表
 *
 * 通过 source 字段（来自 raw_data.source）映射到平台配置。
 * 新增平台只需在此添加一条记录，前端自动适配。
 */

export const EXTERNAL_SOURCES = {
  apple_books: {
    label: 'Apple Books',
    deepLink: (externalId) => `ibooks://assetid/${externalId}`,
    openLabel: '在 Apple Books 中打开',
    icon: 'apple',
  },
  wechat_read: {
    label: '微信读书',
    deepLink: (externalId) => `https://weread.qq.com/web/reader/${externalId}`,
    openLabel: '在微信读书中打开',
    icon: 'wechat',
  },
  bilibili: {
    label: 'Bilibili',
    deepLink: (externalId) => `https://www.bilibili.com/video/${externalId}`,
    openLabel: '在 Bilibili 中打开',
    icon: 'bilibili',
  },
}

export function isExternalSource(source) {
  return source && source in EXTERNAL_SOURCES
}

export function getSourceConfig(source) {
  return EXTERNAL_SOURCES[source] || null
}
