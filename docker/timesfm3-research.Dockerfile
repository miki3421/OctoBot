FROM python:3.12-slim-bookworm

ARG TORCH_VERSION=2.14.0+cpu
ARG TIMESFM_VERSION=3.0.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      "torch==${TORCH_VERSION}" \
    && python -m pip install --no-cache-dir "timesfm==${TIMESFM_VERSION}" \
    && python -c "import timesfm3, torch; assert torch.__version__ == '${TORCH_VERSION}'"

WORKDIR /workspace
ENTRYPOINT ["python", "-m", "octobot.ai_strategy_lab.timesfm3_research_v1"]
