"""`/api/survey/xlsx`（產出模式）的測試。

這一支與 `/api/review` 方向相反。審查那條路是「已經有填好的表，重算去比對」，
這條路是「表是空的，算出每一格該填什麼」。正式題目的表5-1 與表4 空白待填，
而勘查表沒有優劣等級這一欄，所以審查那條在那個案子沒有對照對象。

需要兩樣不在版控裡的東西：官方 xlsx 空白範本（被 .gitignore 的 *.xlsx 排除），
以及一份填好的表3。後者由 `xlsxform` 自己產出，所以只要範本在就能跑，
找不到範本時整份 skip。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import paths
from api.main import app
from xlsxform.pipeline import find_template, write_table3

ROOT = Path(__file__).resolve().parent.parent.parent
FACTS = json.loads(
    (ROOT / "kernel" / "fixtures" / "shulin_survey_facts.json").read_text(encoding="utf-8")
)
EXPECTED = FACTS["expected"]
COMPS = list(FACTS["comparables"])


def _template_dir() -> Path | None:
    env = os.environ.get("SHULIN_TEMPLATE_DIR")
    for c in ([Path(env)] if env else []) + [paths.TEMPLATE_DIR, ROOT.parent / "正式題目"]:
        try:
            find_template(c, "table3")
        except (FileNotFoundError, OSError):
            continue
        return c
    return None


TEMPLATES = _template_dir()
pytestmark = pytest.mark.skipif(TEMPLATES is None, reason="找不到官方 xlsx 範本（不在版控裡）")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def survey_xlsx(tmp_path_factory) -> Path:
    """用 fixtures 的事實產一份填好的表3，當成使用者要上傳的檔案。"""
    out = tmp_path_factory.mktemp("upload")
    return write_table3(FACTS, find_template(TEMPLATES, "table3"), out / "表3.xlsx")


@pytest.fixture(scope="module")
def result(client, survey_xlsx):
    with open(survey_xlsx, "rb") as fh:
        r = client.post("/api/survey/xlsx", files={"file": ("表3.xlsx", fh)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    return body["data"]


# ---------- 回應形狀 ----------


def test_envelope_shape(client, survey_xlsx):
    """每一個回應都必須是 {data, error}，前端攔截器靠這個判斷。"""
    with open(survey_xlsx, "rb") as fh:
        r = client.post("/api/survey/xlsx", files={"file": ("表3.xlsx", fh)})
    body = r.json()
    assert set(body) == {"data", "error"}
    assert body["error"] is None


def test_rejects_non_xlsx(client):
    r = client.post("/api/survey/xlsx", files={"file": ("表3.pdf", b"%PDF-1.4")})
    assert r.status_code == 422
    body = r.json()
    assert body["data"] is None
    assert "xlsx" in body["error"]["message"]


def test_rejects_garbage_xlsx(client):
    """不是 Excel 的檔案要明確報錯，不能算下去。"""
    r = client.post("/api/survey/xlsx", files={"file": ("壞檔.xlsx", b"not a real xlsx")})
    assert r.status_code in (400, 500)
    assert r.json()["data"] is None


# ---------- 計算結果 ----------


def test_cell_counts(result):
    assert result["cell_counts"] == {
        "grades": 116,
        "corrections": 87,
        "subtotals": 24,
        "totals": 3,
    }


def test_totals_match_verified_values(result):
    for seg in COMPS:
        assert float(result["table5_1"]["totals"][seg]) == float(
            EXPECTED["total_correction_pct"][seg]
        )


def test_table4_chain(result):
    t4 = result["table4"]
    for seg in COMPS:
        assert t4["trial_price"][seg] == EXPECTED["trial_price"][seg]
        assert float(t4["weight_pct"][seg]) == float(EXPECTED["weights"][seg]["weight_pct"])
        assert t4["similarity"][seg] == EXPECTED["weights"][seg]["similarity"]
    assert t4["benchmark_comparison_price"] == EXPECTED["benchmark_comparison_price"]
    assert t4["benchmark_land_price"] == EXPECTED["benchmark_land_price"]


def test_grades_cover_every_segment_and_factor(result):
    grades = result["table5_1"]["grades"]
    assert set(grades) == {result["benchmark"], *COMPS}
    assert len(result["table5_1"]["factor_ids"]) == 29
    for seg, per in grades.items():
        assert len(per) == 29, seg
        assert all(v not in (None, "") for v in per.values()), seg


def test_premise_is_stated(result):
    """個別因素以 0 計這件事必須寫在回應裡，否則試算價格會被當成完整答案。"""
    assert "個別因素" in result["premise"]
    assert "地價查估單位" in result["premise"]


# ---------- 依據鏈 ----------


def test_evidence_covers_every_factor_of_every_comparable(result):
    assert len(result["evidence"]) == len(COMPS)
    assert sum(len(s["factors"]) for s in result["evidence"]) == 87


def test_evidence_has_narrative_and_page(result):
    for seg_ev in result["evidence"]:
        assert seg_ev["narrative"]
        assert len(seg_ev["groups"]) == 8
        for fe in seg_ev["factors"]:
            assert fe["narrative"], fe["factor_id"]


def test_evidence_of_main_road_shows_the_whole_chain(result):
    seg_ev = next(s for s in result["evidence"] if s["segment"] == "P002-00")
    fe = next(f for f in seg_ev["factors"] if f["label"] == "主要道路寬度")
    assert fe["source_page"] == 2
    assert fe["benchmark"]["value"] == 28
    assert fe["benchmark"]["grade"] == 1
    assert fe["comparable"]["value"] == 7
    assert fe["comparable"]["grade"] == 5
    assert fe["correction_pct"] == "15.00"
    assert "28m以上" in fe["benchmark"]["reason"]
    assert "未滿8m" in fe["comparable"]["reason"]


def test_evidence_explains_override(result):
    """容積率的依據要講出勘查表原載 260%、依局處指示以 200% 計算。"""
    seg_ev = next(s for s in result["evidence"] if s["segment"] == "P002-00")
    fe = next(f for f in seg_ev["factors"] if f["label"] == "容積率")
    assert "原載 260%" in fe["narrative"]
    assert fe["counted"] is False


# ---------- 自我驗證與檔案 ----------


def test_verification_passes(result):
    v = result["verification"]
    assert v["passed"] is True, [c for c in v["checks"] if not c["passed"]]
    assert v["failed"] == 0
    assert v["total"] >= 10


def test_files_include_all_forms_and_report(result):
    names = [f["filename"] for f in result["files"]]
    assert len(names) == 6
    assert any("表3" in n for n in names)
    assert sum(1 for n in names if "表5" in n) == 2  # live + final
    assert sum(1 for n in names if "表4" in n) == 2
    assert "verification-report.json" in names
    for f in result["files"]:
        assert f["size"] > 0
        assert f["link"].startswith("/api/survey/")


def test_files_are_downloadable(client, result):
    for f in result["files"]:
        r = client.get(f["link"])
        assert r.status_code == 200, f["filename"]
        assert len(r.content) == f["size"]


def test_download_rejects_unknown_filename(client, result):
    r = client.get("/api/survey/%s/亂猜的檔名.xlsx" % result["id"])
    assert r.status_code == 404


def test_download_rejects_path_traversal(client, result):
    r = client.get("/api/survey/%s/..%%2Fetc%%2Fpasswd" % result["id"])
    assert r.status_code in (400, 404)


def test_report_json_is_downloadable_and_states_premise(client, result):
    link = next(f["link"] for f in result["files"] if f["filename"].endswith(".json"))
    r = client.get(link)
    assert r.status_code == 200
    payload = json.loads(r.content)
    assert payload["passed"] is True
    assert "個別因素" in payload["premise"]
    assert payload["ruleset_id"] == "shulin-residential-regional"
