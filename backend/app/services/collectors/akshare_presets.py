"""AkShare 金融数据指标预设库

按分类组织常用金融指标，供前端预设选择器和后端采集器使用。
每个预设定义了 akshare 接口名称、参数、字段映射和采集策略。

字段说明:
  key           — 预设唯一标识
  label         — 前端展示名称
  indicator     — akshare 函数名
  params        — 默认参数
  title_field   — 用于生成 ContentItem.title 的字段名
  id_fields     — 用于去重的字段列表
  date_field    — 日期字段名
  value_field   — 主要数值字段（宏观指标用）
  ohlcv_fields  — OHLCV 字段映射（股票/ETF 用）
  nav_fields    — 净值字段映射（基金用）
  schedule_interval — 建议采集间隔（秒）
  max_history   — 首次采集最大行数
  user_params   — 需要用户填写的参数列表
"""

FINANCE_PRESETS = {
    "macro": {
        "label": "宏观经济",
        "indicators": [
            {
                "key": "cpi",
                "label": "CPI 居民消费价格指数",
                "indicator": "macro_china_cpi_monthly",
                "params": {},
                "title_field": "日期",
                "id_fields": ["日期"],
                "value_field": "全国居民消费价格指数",
                "date_field": "日期",
                "schedule_interval": 86400,
                "max_history": 120,
            },
            {
                "key": "ppi",
                "label": "PPI 工业品出厂价格指数",
                "indicator": "macro_china_ppi",
                "params": {},
                "title_field": "日期",
                "id_fields": ["日期"],
                "value_field": "当月",
                "date_field": "日期",
                "schedule_interval": 86400,
                "max_history": 120,
            },
            {
                "key": "pmi",
                "label": "PMI 采购经理指数",
                "indicator": "macro_china_pmi",
                "params": {},
                "title_field": "日期",
                "id_fields": ["日期"],
                "value_field": "制造业-Loss",
                "date_field": "日期",
                "schedule_interval": 86400,
                "max_history": 120,
            },
            {
                "key": "gdp",
                "label": "GDP 国内生产总值",
                "indicator": "macro_china_gdp",
                "params": {},
                "title_field": "季度",
                "id_fields": ["季度"],
                "value_field": "国内生产总值-绝对值",
                "date_field": "季度",
                "schedule_interval": 86400,
                "max_history": 60,
            },
            {
                "key": "m2",
                "label": "M2 货币供应量",
                "indicator": "macro_china_money_supply",
                "params": {},
                "title_field": "月份",
                "id_fields": ["月份"],
                "value_field": "M2-数量",
                "date_field": "月份",
                "schedule_interval": 86400,
                "max_history": 120,
            },
            {
                "key": "new_loan",
                "label": "新增信贷数据",
                "indicator": "macro_china_new_financial_credit",
                "params": {},
                "title_field": "月份",
                "id_fields": ["月份"],
                "value_field": "当月",
                "date_field": "月份",
                "schedule_interval": 86400,
                "max_history": 120,
            },
            {
                "key": "fx_reserve",
                "label": "外汇储备",
                "indicator": "macro_china_fx_reserves_yearly",
                "params": {},
                "title_field": "日期",
                "id_fields": ["日期"],
                "value_field": "国家外汇储备",
                "date_field": "日期",
                "schedule_interval": 86400,
                "max_history": 60,
            },
            {
                "key": "shibor",
                "label": "Shibor 利率",
                "indicator": "rate_interbank",
                "params": {"market": "上海银行同业拆借市场", "symbol": "Shibor人民币", "indicator": "隔夜"},
                "title_field": "报告日",
                "id_fields": ["报告日"],
                "value_field": "利率",
                "date_field": "报告日",
                "schedule_interval": 21600,
                "max_history": 250,
            },
        ],
    },
    "stock": {
        "label": "A股行情",
        "indicators": [
            {
                "key": "stock_hist",
                "label": "个股日线",
                "indicator": "stock_zh_a_hist",
                "params": {"symbol": "", "period": "daily", "start_date": "", "adjust": "qfq"},
                "title_field": "日期",
                "id_fields": ["日期"],
                "date_field": "日期",
                "ohlcv_fields": {
                    "open": "开盘", "high": "最高", "low": "最低",
                    "close": "收盘", "volume": "成交量",
                },
                "schedule_interval": 21600,
                "max_history": 250,
                "user_params": ["symbol"],
            },
            {
                "key": "stock_board_industry",
                "label": "行业板块行情",
                "indicator": "stock_board_industry_hist_em",
                "params": {"symbol": "", "period": "日k", "start_date": "", "adjust": ""},
                "title_field": "日期",
                "id_fields": ["日期"],
                "date_field": "日期",
                "ohlcv_fields": {
                    "open": "开盘", "high": "最高", "low": "最低",
                    "close": "收盘", "volume": "成交量",
                },
                "schedule_interval": 21600,
                "max_history": 250,
                "user_params": ["symbol"],
            },
            {
                "key": "index_hist",
                "label": "指数日线 (上证/深证等)",
                "indicator": "stock_zh_index_daily_em",
                "params": {"symbol": "", "start_date": ""},
                "title_field": "date",
                "id_fields": ["date"],
                "date_field": "date",
                "ohlcv_fields": {
                    "open": "open", "high": "high", "low": "low",
                    "close": "close", "volume": "volume",
                },
                "schedule_interval": 21600,
                "max_history": 250,
                "user_params": ["symbol"],
            },
        ],
    },
    "fund": {
        "label": "基金/ETF",
        "indicators": [
            {
                "key": "etf_hist",
                "label": "ETF 历史行情",
                "indicator": "fund_etf_hist_em",
                "params": {"symbol": "", "period": "daily", "start_date": "", "adjust": "qfq"},
                "title_field": "日期",
                "id_fields": ["日期"],
                "date_field": "日期",
                "ohlcv_fields": {
                    "open": "开盘", "high": "最高", "low": "最低",
                    "close": "收盘", "volume": "成交量",
                },
                "schedule_interval": 21600,
                "max_history": 250,
                "user_params": ["symbol"],
            },
            {
                "key": "fund_nav",
                "label": "开放式基金净值",
                "indicator": "fund_open_fund_info_em",
                "params": {"symbol": ""},
                "title_field": "净值日期",
                "id_fields": ["净值日期"],
                "date_field": "净值日期",
                "nav_fields": {"unit_nav": "单位净值", "cumulative_nav": "累计净值"},
                "schedule_interval": 21600,
                "max_history": 250,
                "user_params": ["symbol"],
            },
        ],
    },
}


def get_preset_by_key(key: str) -> dict | None:
    """按 key 查找预设配置"""
    for category_data in FINANCE_PRESETS.values():
        for indicator in category_data["indicators"]:
            if indicator["key"] == key:
                return indicator
    return None


def get_category_for_indicator(indicator_name: str) -> str | None:
    """根据 akshare 函数名查找所属分类"""
    for category, category_data in FINANCE_PRESETS.items():
        for ind in category_data["indicators"]:
            if ind["indicator"] == indicator_name:
                return category
    return None
