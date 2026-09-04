/**
 * config_json 兼容解析
 *
 * 后端 config_json 已迁移为 JSONB（API 返回对象），历史代码按 JSON 字符串处理。
 * 统一通过此函数读取：对象直接返回，字符串尝试解析，其余情况返回空对象。
 */
export function asConfigObject(cfg) {
  if (cfg == null) return {}
  if (typeof cfg === 'object') return cfg
  if (typeof cfg === 'string') {
    try {
      const parsed = JSON.parse(cfg)
      return parsed && typeof parsed === 'object' ? parsed : {}
    } catch {
      return {}
    }
  }
  return {}
}
