"""全局配置：全部从环境变量读取，见 .env.example。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 先按标准方式加载（cwd），再显式加载项目根目录的 .env（已设置的环境变量优先，不被覆盖）
load_dotenv()
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass
class Settings:
    # 任意 OpenAI 兼容接口均可；默认为智谱开放平台
    api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    base_url: str = field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
    )
    model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "glm-4.6"))
    embedding_model: str = field(
        default_factory=lambda: os.getenv("LLM_EMBEDDING_MODEL", "embedding-3")
    )
    # 嵌入后端：auto（装了 fastembed 用本地，否则走 API）| api | local
    embedding_backend: str = field(
        default_factory=lambda: os.getenv("LLM_EMBEDDING_BACKEND", "auto")
    )
    local_embedding_model: str = field(
        default_factory=lambda: os.getenv("LLM_LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    )
    # 智谱 GLM 默认开启思考模式：更慢更贵且长思考会挤占输出预算；结构化抽取场景建议关闭
    thinking: str = field(default_factory=lambda: os.getenv("LLM_THINKING", "disabled"))

    @property
    def extra_body(self) -> dict | None:
        """智谱专属参数；其他 OpenAI 兼容服务商传未知参数会被拒，故按服务商判断。"""
        if "bigmodel" in self.base_url:
            return {"thinking": {"type": self.thinking}}
        return None

    # 检索参数
    retrieve_k: int = 8
    dense_weight: float = 0.7  # 混合排序中语义分的权重（原始余弦）
    # 报表口径加权幅度：0 为关闭（实测在 106 题评测中无可测收益，详见 docs/评测报告.md）
    scope_adjust: float = field(default_factory=lambda: float(os.getenv("LLM_SCOPE_ADJUST", "0")))

    # 目录约定
    data_dir: Path = field(default_factory=lambda: Path("data"))

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def parsed_dir(self) -> Path:
        return self.data_dir / "parsed"

    @property
    def eval_dir(self) -> Path:
        return self.data_dir / "eval"


settings = Settings()
