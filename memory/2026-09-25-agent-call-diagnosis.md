# Agent 调用参数排查（2026-09-25）

## 结论

- “中山陵到夫子庙”路线失败不是 LLM 输出字段名或城市值不符合参数模型。Agent 选择了 `transit_route`，传入 `origin=中山陵`、`destination=夫子庙`、`city=南京`。
- 路线工具先请求高德 `/v3/geocode/geo` 解析起点，实际业务参数为 `address=中山陵`、`city=南京`、`output=json`。高德返回 `status=0`、`info=ENGINE_RESPONSE_DATA_ERROR`、`infocode=30001`。因此请求没有到 `/v3/direction/transit/integrated`。
- 同一请求里，`keyword_search(keywords=中山陵, city=南京)` 成功。现有代码在提供 `city` 时优先走地理编码；地理编码异常发生在路线请求的错误回退逻辑之外，因此没有转用成功的 POI 坐标。这是本地调用路径的缺口；应进一步修复并为“地理编码报错后转 POI 搜索坐标”增加回归测试。
- 三日游 504 是另一条链路。`keyword_search(keywords=南京, city=南京)` 和内部历史查询均成功；随后第 3 轮 `ReActDecision` 的 LLM 调用在 43.2 秒超时，请求总耗时约 65 秒后返回 504。该请求没有进入行程生成器，也没有因高德路线参数而失败。

## 参数文档核对

- 高德地理编码文档接受中文城市名作为 `city`，也声明支持地标性名胜景区；因此 `city=南京` 本身符合文档，不能仅凭 30001 断言字段写错。
- 300** 错误码是通用引擎响应失败。高德建议先核对输入参数，仍无法解决时提交详细复现信息；日志码本身不能指出具体字段原因。
- 对本次请求，最明确的工程问题是地理编码失败后没有 POI 搜索回退。路线接口实际收到的起终点坐标在这次请求中不存在，因为路线接口没有被调用。

## 证据请求

- 规划：`37bc84e1c515f4c521aef9fee43b62cc`
- 驾车路线：`77d909f7ffbc6c18b5fdcf95872c0b2c`
- 公交路线：`cb6b1f8ddd4a783edca13aef078bdff4`

## 参考

- 高德地理/逆地理编码：https://lbs.amap.com/api/webservice/guide/api/georegeo
- 高德 POI 搜索：https://lbs.amap.com/api/webservice/guide/api/search/
- 高德错误码说明：https://lbs.amap.com/api/webservice/guide/tools/info
