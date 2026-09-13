# syntax=docker/dockerfile:1
#
# 後端服務鏡像（FastAPI + uvicorn）。
#
# 官方 PDF 與 xlsx 空白範本**刻意不進 image**：那些檔案不在版控裡（約 103MB），
# 而且比賽當天會換成官方給的新檔。用掛載帶進來，換檔不必重 build——
# 位置由 VALUATION_DOC_DIR / VALUATION_TEMPLATE_DIR 決定，見 paths.py。


# ---------- builder：只負責裝套件 ----------
FROM python:3.13-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

# 裝進獨立 venv，runtime 階段整包 COPY 過去，這樣 runtime 不必帶 pip 與快取。
# requirements.txt 裡的套件（cryptography / pdfplumber / reportlab / uvloop）
# 在 cp313 manylinux 都有 wheel，不需要編譯工具鏈；哪天某個套件沒有 wheel
# 而 build 失敗，在這一階段加 build-essential 即可，不會污染 runtime。
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 只先複製 requirements.txt：改程式碼時這層仍然命中快取。
WORKDIR /tmp/build
COPY requirements.txt ./
RUN pip install -r requirements.txt


# ---------- runtime ----------
FROM python:3.13-slim-bookworm

# 書表全是中文，產表走 reportlab。pdfform/render.py 的 FONT_PATHS 在 Linux
# 只找 /usr/share/fonts/truetype/arphic/ukai.ttc（由 fonts-arphic-ukai 提供），
# 找不到就直接 FileNotFoundError（那是刻意的，見該檔註解：寧可失敗也不要
# 靜靜產出一片空白）。所以在 build 當下就驗檔案在不在，不要等 demo 現場才發現。
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-arphic-ukai \
    && rm -rf /var/lib/apt/lists/* \
    && test -f /usr/share/fonts/truetype/arphic/ukai.ttc

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VALUATION_DOC_DIR=/data/docs \
    VALUATION_TEMPLATE_DIR=/data/templates

COPY --from=builder /opt/venv /opt/venv

# 非 root 執行。產出的書表寫在 tempfile.gettempdir()（/tmp，1777），
# 不需要額外授權；/data 是唯讀掛載點，先建好讓沒掛載時的錯誤訊息讀得懂。
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/docs /data/templates

WORKDIR /app
COPY . .

USER app

EXPOSE 8000

# 存活檢查用 /api/health（順便回報文件目錄位置）。用 python 而不是 curl，
# slim image 沒有 curl，為了健康檢查多裝一個套件不划算。
# urlopen 遇到非 2xx 會丟例外，離開碼自然是非 0。
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]

# 單一 process。這個服務的瓶頸是 pdfplumber 解析與產表（CPU-bound 且一次一件），
# 加 --workers 只是讓同時上傳的人互相搶 CPU；要橫向擴張時是加 container 而不是加 worker。
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
