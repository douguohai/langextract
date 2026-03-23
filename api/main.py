"""FastAPI entrypoint for LangExtract."""

import logging
import os
from typing import Any, Dict, List, Optional

try:
  from dotenv import load_dotenv
  load_dotenv()
except ImportError:
  pass  # python-dotenv 未安装时忽略，依赖外部传入环境变量

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

import langextract as lx
from langextract import data as lx_data
from langextract import data_lib
from langextract import factory

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("MODEL_ID", "gemini-2.5-flash")

# ---------------------------------------------------------------------------
# Token authentication
# API_TOKENS: comma-separated list of valid tokens in .env
# e.g. API_TOKENS=token-abc123,token-xyz456
# Reads from env on every request so token list can be updated via .env reload.
# ---------------------------------------------------------------------------
_bearer = HTTPBearer(auto_error=False)


def _require_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> None:
  valid_tokens = {
      t.strip() for t in os.getenv("API_TOKENS", "").split(",") if t.strip()
  }
  if not valid_tokens:
    return  # 未配置 API_TOKENS 时不启用认证
  if credentials is None or credentials.credentials not in valid_tokens:
    raise HTTPException(
        status_code=401,
        detail={"code": 1, "msg": "Unauthorized", "data": None},
    )

# ---------------------------------------------------------------------------
# Module-level model cache: keyed by (model_id, base_url, api_key)
# Avoids recreating the model object on every request.
# ---------------------------------------------------------------------------
_model_cache: Dict[tuple, Any] = {}


def _get_model(model_id: str) -> Any:
  """Return a cached model override when OpenAI-compat env vars are set."""
  base_url = os.getenv("OPENAI_BASE_URL")
  api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LANGEXTRACT_API_KEY")
  if not (base_url or os.getenv("FORCE_OPENAI")):
    return None
  key = (model_id, base_url, api_key)
  if key not in _model_cache:
    cfg = factory.ModelConfig(
        model_id=model_id,
        provider="OpenAILanguageModel",
        provider_kwargs={"api_key": api_key, "base_url": base_url},
    )
    _model_cache[key] = factory.create_model(config=cfg)
  return _model_cache[key]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class StandardResponse(BaseModel):
  code: int
  msg: str
  data: Any


class CharInterval(BaseModel):
  start_pos: Optional[int] = None
  end_pos: Optional[int] = None


class ExtractionModel(BaseModel):
  extraction_class: str
  extraction_text: str
  attributes: Dict[str, Any] = Field(default_factory=dict)
  char_interval: Optional[CharInterval] = None
  alignment_status: Optional[str] = None
  extraction_index: Optional[int] = None
  group_index: Optional[int] = None
  description: Optional[str] = None


class AnnotatedDocumentModel(BaseModel):
  text: Optional[str] = None
  document_id: Optional[str] = None
  extractions: List[ExtractionModel] = Field(default_factory=list)


class ExtractRequest(BaseModel):
  text: str = Field(..., description="Input text or URL to process.")
  prompt: str = Field(..., description="Prompt describing extraction goals.")
  examples: List[dict] = Field(
      ...,
      description=(
          "Few-shot examples as [{'text': str, 'extractions': "
          "[{'extraction_class': str, 'extraction_text': str,"
          " 'attributes': {...}}]}]."
      ),
  )
  passes: int = Field(
      1,
      ge=1,
      le=5,
      description="Extraction passes; higher may improve recall at extra cost.",
  )
  max_workers: Optional[int] = Field(
      None,
      ge=1,
      description="Optional concurrency override for chunked processing.",
  )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result_to_dict(result: Any) -> Any:
  """Convert AnnotatedDocument or list thereof to plain dict."""
  if isinstance(result, list):
    docs = [_normalize_doc(data_lib.annotated_document_to_dict(r)) for r in result]
    return {"results": docs}
  return _normalize_doc(data_lib.annotated_document_to_dict(result))


def _normalize_doc(doc: dict) -> dict:
  """Ensure attributes are dicts to satisfy response schema."""
  extractions = doc.get("extractions") or []
  for ext in extractions:
    if ext.get("attributes") is None:
      ext["attributes"] = {}
  doc["extractions"] = extractions
  return doc


def _validate_examples(examples: List[dict]) -> Optional[JSONResponse]:
  """Validate examples structure; return JSONResponse on failure, else None."""
  if not examples:
    return JSONResponse(
        status_code=400,
        content={"code": 1, "msg": "examples must not be empty", "data": None},
    )
  for idx, ex in enumerate(examples):
    if "text" not in ex or "extractions" not in ex:
      return JSONResponse(
          status_code=400,
          content={
              "code": 1,
              "msg": f"examples[{idx}] must include 'text' and 'extractions' list",
              "data": None,
          },
      )
    for jdx, ext in enumerate(ex.get("extractions", [])):
      if "extraction_class" not in ext or "extraction_text" not in ext:
        return JSONResponse(
            status_code=400,
            content={
                "code": 1,
                "msg": (
                    f"examples[{idx}].extractions[{jdx}] must include "
                    "'extraction_class' and 'extraction_text'"
                ),
                "data": None,
            },
        )
  return None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="LangExtract API", version="1.0.0")


@app.get("/health", response_model=StandardResponse, dependencies=[Depends(_require_token)])
def health() -> dict:
  return {"code": 0, "msg": "ok", "data": {"status": "ok"}}


@app.post("/extract", response_model=StandardResponse, dependencies=[Depends(_require_token)])
def extract(req: ExtractRequest) -> Any:
  err = _validate_examples(req.examples)
  if err:
    return err

  max_workers_val = req.max_workers or os.getenv("MAX_WORKERS")
  kwargs: Dict[str, Any] = {}
  if max_workers_val:
    kwargs["max_workers"] = int(max_workers_val)

  examples = []
  for ex in req.examples:
    extractions = [
        lx_data.Extraction(
            extraction_class=ext.get("extraction_class", ""),
            extraction_text=ext.get("extraction_text", ""),
            attributes=ext.get("attributes", {}) or {},
        )
        for ext in ex.get("extractions", [])
    ]
    examples.append(
        lx_data.ExampleData(text=ex.get("text", ""), extractions=extractions)
    )

  try:
    result = lx.extract(
        text_or_documents=req.text,
        prompt_description=req.prompt,
        examples=examples,
        model_id=DEFAULT_MODEL,
        model=_get_model(DEFAULT_MODEL),
        extraction_passes=req.passes,
        **kwargs,
    )
    return {"code": 0, "msg": "ok", "data": _result_to_dict(result)}
  except Exception:  # pylint: disable=broad-except
    logger.exception("Extraction failed for request: text_len=%d", len(req.text))
    return JSONResponse(
        status_code=500,
        content={"code": 1, "msg": "Internal extraction error. See server logs.", "data": None},
    )


@app.get("/", response_model=StandardResponse, dependencies=[Depends(_require_token)])
def root() -> dict:
  return {"code": 0, "msg": "ok", "data": {"message": "LangExtract FastAPI is running."}}


if __name__ == "__main__":
  import uvicorn

  uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
