"""采集器共享工具单元测试

回归测试 coerce_config：保证 config_json 即使被二次编码成 JSON 字符串
（历史脏数据），collector 取值也不会抛 AttributeError。
"""

from app.services.collectors.utils import coerce_config


class TestCoerceConfig:
    """coerce_config 应始终返回 dict"""

    def test_dict_passthrough(self):
        cfg = {"indicator": "macro_china_money_supply", "max_history": 120}
        assert coerce_config(cfg) is cfg

    def test_json_string_recovered_to_dict(self):
        """JSONB 列里被二次编码成字符串标量的脏数据应被还原（M2 货币供应量 线上 Bug）"""
        raw = '{"indicator": "macro_china_money_supply", "value_field": "M2-数量"}'
        assert coerce_config(raw) == {
            "indicator": "macro_china_money_supply",
            "value_field": "M2-数量",
        }

    def test_none_returns_empty_dict(self):
        assert coerce_config(None) == {}

    def test_invalid_json_string_returns_empty_dict(self):
        assert coerce_config("not json at all") == {}

    def test_json_non_dict_returns_empty_dict(self):
        assert coerce_config("[1, 2, 3]") == {}

    def test_other_type_returns_empty_dict(self):
        assert coerce_config(123) == {}
