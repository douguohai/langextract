# LangExtract FastAPI 部署指南

本指南介绍如何在国内环境下把 LangExtract 封装为 FastAPI 服务，并用 Docker 部署。

## 环境准备

- Python ≥ 3.10，已安装 `langextract` 源码目录。
- 必要环境变量（任选所需）：
  - `API_TOKENS`：逗号分隔的合法 token 列表，例如 `token-abc,token-xyz`；**不配置则不启用认证**
  - `MODEL_ID`（默认 `gemini-2.5-flash`）
  - `MAX_WORKERS`（并发分片数，可选）
  - `GEMINI_API_KEY` / `OPENAI_API_KEY` / `LANGEXTRACT_API_KEY`
  - `OPENAI_BASE_URL`：OpenAI 兼容接口地址，例如 `https://dashscope.aliyuncs.com/compatible-mode/v1`
  - `FORCE_OPENAI`：设为任意非空值时，即使未配置 `OPENAI_BASE_URL` 也强制使用 OpenAI 兼容 provider
  - `HTTP_PROXY` / `HTTPS_PROXY`：如需走本地代理
  - 示例文件：`.env.example`

> **提示**：服务启动时会自动加载项目根目录下的 `.env` 文件（依赖 `python-dotenv`）。若未安装则忽略，需手动通过环境变量或 `--env-file` 传入配置。

## 本地运行

```bash
pip install -e ".[openai]" fastapi uvicorn python-dotenv
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 健康检查

```bash
curl http://localhost:8000/health
# 返回: {"code":0,"msg":"ok","data":{"status":"ok"}}
```

### 调用示例

```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{
        "text": "Lady Juliet gazed at the stars.",
        "prompt": "Extract characters and emotions.",
        "examples": [
          {
            "text": "Hi, I am Romeo.",
            "extractions": [
              {"extraction_class": "character", "extraction_text": "Romeo"}
            ]
          }
        ],
        "passes": 1
      }'
```

返回格式：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "extractions": [...],
    "text": "...",
    "document_id": "doc_xxx"
  }
}
```

### 知识图谱提取示例

```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{
        "text": "阿里巴巴由马云于1999年在杭州创立，旗下拥有淘宝、天猫、支付宝。",
        "prompt": "提取实体（人物、公司、产品、地点、时间）以及它们之间的关系，构建知识图谱三元组（subject、predicate、object）。",
        "passes": 1,
        "examples": [
          {
            "text": "腾讯由马化腾于1998年在深圳创立，旗下拥有微信和QQ。",
            "extractions": [
              {"extraction_class": "entity", "extraction_text": "腾讯", "attributes": {"type": "company"}},
              {"extraction_class": "entity", "extraction_text": "马化腾", "attributes": {"type": "person"}},
              {"extraction_class": "relationship", "extraction_text": "马化腾 创立 腾讯",
               "attributes": {"subject": "马化腾", "predicate": "founded", "object": "腾讯"}},
              {"extraction_class": "relationship", "extraction_text": "腾讯 拥有 微信",
               "attributes": {"subject": "腾讯", "predicate": "owns", "object": "微信"}}
            ]
          }
        ]
      }'
```

## Docker 构建与运行

使用专用 `Dockerfile.api`（保留原有基础镜像 Dockerfile）。

```bash
docker build -f Dockerfile.api -t langextract-api . \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

docker run -p 8000:8000 --env-file .env langextract-api
```

如需代理，可在 `.env` 中设置 `HTTP_PROXY`、`HTTPS_PROXY` 或指定 `OPENAI_BASE_URL`。

## API 说明

- `GET /`：服务存活检查（简要信息）。
- `GET /health`：健康检查，返回 `{"code":0,"msg":"ok","data":{"status":"ok"}}`。
- `POST /extract`：执行抽取。
  - 请求体：
    - `text` (str，必填)：待处理的文本或可访问的 URL。
    - `prompt` (str，必填)：抽取任务描述。
    - `examples` (list，必填)：至少一个示例，结构为 `{"text": str, "extractions": [{"extraction_class": str, "extraction_text": str, "attributes": {...}}]}`。
    - `passes` (int，可选，1-5，默认 1)：抽取轮数，提升召回。
    - `max_workers` (int，可选，≥1)：并行 worker 数，未传则使用环境变量或内部默认。
  - 返回：统一包装格式 `{"code": 0, "msg": "ok", "data": {...}}`。

## 认证

所有接口均通过 `Authorization: Bearer <token>` 头进行认证。

```bash
curl -H "Authorization: Bearer your-token" http://localhost:8000/health
```

- 配置了 `API_TOKENS` 时，token 不在列表内或未提供均返回 `401`。
- 未配置 `API_TOKENS` 时，认证关闭，所有请求均可访问（适用于内网部署）。

## 请求校验

| 场景 | HTTP 状态码 | 响应示例 |
|------|-------------|---------|
| token 缺失或无效 | 401 | `{"detail":{"code":1,"msg":"Unauthorized","data":null}}` |
| 缺少 `text` / `prompt` / `examples` | 422 | FastAPI 自动返回字段校验错误 |
| `examples` 为空数组 | 400 | `{"code":1,"msg":"examples must not be empty","data":null}` |
| `examples[i]` 缺少 `text` 或 `extractions` | 400 | `{"code":1,"msg":"examples[i] must include ...","data":null}` |
| `extractions[j]` 缺少 `extraction_class` 或 `extraction_text` | 400 | `{"code":1,"msg":"examples[i].extractions[j] must include ...","data":null}` |
| `max_workers` < 1 | 422 | FastAPI 自动返回字段校验错误 |
| `passes` 超出 1-5 范围 | 422 | FastAPI 自动返回字段校验错误 |
| 抽取过程内部错误 | 500 | `{"code":1,"msg":"Internal extraction error. See server logs.","data":null}` |

## 最佳实践

- 优先通过 `.env` 管理密钥；避免写入镜像或代码。
- 在国内环境构建时使用 `--build-arg PIP_INDEX_URL` 指定镜像源。
- 需要高并发可在运行时追加 `--workers N` 参数：
  `uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4`
- `passes` 值越高召回越好，但会成倍增加 API 调用次数，建议先用 `passes=1` 评估效果。
- 若启用 `live_api` 测试，请提前设置相应 API keys，并使用标记运行：
  `pytest -m live_api tests/test_live_api.py -v`

## 目录位置

- FastAPI 入口：`api/main.py`
- 示例环境变量：`.env.example`
- Docker 构建文件：`Dockerfile.api`
