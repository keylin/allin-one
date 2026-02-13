import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import utc from 'dayjs/plugin/utc'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.extend(utc)
dayjs.locale('zh-cn')

/**
 * 列表/卡片场景：24h 内显示相对时间，超过则显示短格式
 */
export function formatTimeShort(t) {
  if (!t) return '-'
  const local = dayjs.utc(t).local()
  const diffHours = dayjs().diff(local, 'hour')
  if (diffHours < 24) return local.fromNow()
  return local.format('MM-DD HH:mm')
}

/**
 * 详情/弹窗场景：完整时间（无秒）
 */
export function formatTimeFull(t) {
  if (!t) return '-'
  return dayjs.utc(t).local().format('YYYY-MM-DD HH:mm')
}
