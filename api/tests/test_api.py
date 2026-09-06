"""API 測試。

兩件事要一起顧：

1. **回應信封**。前端攔截器靠 `'data' in body && 'error' in body` 判斷格式，
   所以錯誤回應也必須是這個形狀。FastAPI 預設的 `{"detail": ...}` 會讓
   後端寫的錯誤說明整段被前端吃掉，這裡有專門的測試盯著。

2. **端到端數字**。上傳官方範本 PDF → 辨識 → 計算，必須得到官方答案
   212,958 / 213,000。這條測試把「辨識 → 引擎」整條鏈綁在官方答案上。
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

import paths
from api.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def parsed(client):
    with open(paths.require(paths.SAMPLE_FORMS_PDF), "rb") as f:
        r = client.post(
            "/api/parse",
            files={"file": ("查估書表範本.pdf", f, "application/pdf")},
        )
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ---------- 信封 ----------


def _envelope(body: dict) -> None:
    assert set(body) == {"data", "error"}
    assert (body["data"] is None) != (body["error"] is None), "data 與 error 必須二擇一"


def test_success_envelope(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    _envelope(r.json())


def test_error_envelope_is_not_fastapi_detail(client):
    """非 PDF 要回 422，而且 body 必須是信封格式而不是 {"detail": ...}。"""
    r = client.post("/api/parse", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 422
    body = r.json()
    assert "detail" not in body
    _envelope(body)
    assert body["error"]["code"] == 422
    assert "PDF" in body["error"]["message"]


def test_unknown_ruleset_returns_404_with_available_list(client, parsed):
    r = client.post(
        "/api/compute",
        json={"tables": parsed["tables"], "ruleset_individual": "does_not_exist"},
    )
    assert r.status_code == 404
    body = r.json()
    _envelope(body)
    assert "jinshan_commercial_individual" in body["error"]["message"]


def test_missing_tables_returns_422(client):
    r = client.post("/api/compute", json={})
    assert r.status_code == 422
    _envelope(r.json())


# ---------- 規則集 ----------


def test_rulesets_report_partial_honestly(client):
    r = client.get("/api/rulesets")
    assert r.status_code == 200
    by_kind = {x["kind"]: x for x in r.json()["data"]["rulesets"]}
    assert by_kind["individual"]["factor_count"] == 19
    # 區域因素只補到 5/28，前端要看得到這件事，不能顯示成「全部查過」。
    assert by_kind["regional"]["status"] == "partial"
    assert by_kind["regional"]["factor_count"] == 5


# ---------- 辨識 ----------


def test_parse_finds_three_tables_and_three_maps(parsed):
    assert parsed["case_id"] == "1140901-99-001"
    assert [p["table"] for p in parsed["pages"]] == [
        "表1",
        "表5-2",
        "表4",
        None,
        None,
        None,
    ]
    assert set(parsed["tables"]) == {"表1", "表5-2", "表4"}


def test_parse_returns_provenance_for_every_fact(parsed):
    prov = parsed["provenance"]
    facts = parsed["tables"]["表4"]["benchmark"]["facts"]
    for factor_id in facts:
        key = "表4.benchmark.facts.%s" % factor_id
        assert key in prov
        assert prov[key]["page"] == 3
        assert prov[key]["backend"] == "text_layer"


def test_parse_has_no_warnings_on_the_official_sample(parsed):
    assert parsed["warnings"] == []


# ---------- 計算 ----------


def test_compute_reproduces_official_answer(client, parsed):
    """整條鏈的驗收：上傳 PDF → 辨識 → 計算 → 官方答案。"""
    r = client.post("/api/compute", json={"tables": parsed["tables"]})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["benchmark_comparison_price"] == 212958
    assert data["benchmark_land_price_rounded"] == 213000

    c = data["comparables"][0]
    assert c["individual_total_pct"] == 13
    assert c["abs_sum_pct"] == 15
    assert c["similarity_label"] == "普通"
    assert c["weight_pct"] == 100


def test_compute_corrections_carry_their_basis(client, parsed):
    """每個非零修正都要說得出「量測值 → 級距 → 矩陣 → 來源頁」。"""
    r = client.post("/api/compute", json={"tables": parsed["tables"]})
    corrections = r.json()["data"]["comparables"][0]["corrections"]
    nonzero = {c["factor_id"]: c for c in corrections if c["correction_pct"] != 0}
    assert set(nonzero) == {
        "individual.parcel.depth",
        "individual.road.road_type",
        "individual.road.frontage_road_width",
        "individual.surroundings.nuisance",
        "individual.surroundings.parking",
    }

    width = nonzero["individual.road.frontage_road_width"]
    assert width["correction_pct"] == 5
    assert width["benchmark"]["value"] == 18
    assert width["benchmark"]["label"] == "稍優"
    assert width["comparable"]["value"] == 6
    assert width["comparable"]["label"] == "稍劣"
    assert "15m以上未滿20m" in width["benchmark"]["reason"]
    assert width["source_page"]


# ---------- 審查 ----------


def test_review_of_the_official_sample_is_clean(client, parsed):
    """官方範本是正確件，三層檢核都不該有 finding。"""
    r = client.post("/api/review", json={"tables": parsed["tables"]})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["verdict"] == "match", data["layers"]
    assert data["finding_count"] == 0


def test_review_reports_what_it_cannot_check(client, parsed):
    """區域因素只補到 5/28，查不動的 23 項要列出來說明原因，不能靜靜跳過。"""
    r = client.post("/api/review", json={"tables": parsed["tables"]})
    skipped = r.json()["data"]["not_checkable"]
    assert len(skipped) == 23
    assert all(s["layer"] == "table1_internal" for s in skipped)
    assert "5/28" in skipped[0]["reason"]


def test_review_catches_a_wrong_grade_in_table5_2(client, parsed):
    """白話說明的「錯法一」：18 米量到了，等級卻填成稍優。

    表1 寫 3（普通），表5-2 被改成 2（稍優）→ 第二層必須抓到
    （審查重點第 vi 項：兩表等級須一致）。
    """
    tables = copy.deepcopy(parsed["tables"])
    tables["表5-2"]["benchmark_grades"]["regional.transport.main_road_width"] = {
        "grade": 2,
        "label": "稍優",
    }

    r = client.post("/api/review", json={"tables": tables})
    data = r.json()["data"]
    assert data["verdict"] == "mismatch"
    hits = data["layers"]["table1_to_table5_2"]
    assert len(hits) == 1
    assert hits[0]["factor_id"] == "regional.transport.main_road_width"
    assert hits[0]["filed"]["grade"] == 2
    assert hits[0]["computed"]["grade"] == 3


def test_review_catches_a_wrong_correction_in_table4(client, parsed):
    """白話說明的「錯法三」：算出來是 5.00%，抄到表4 卻寫成 0.00%。

    第三層用引擎重算逐格比對，而且要算得出賠償金差多少。
    """
    tables = copy.deepcopy(parsed["tables"])
    tables["表4"]["comparables"][0]["filed_corrections"][
        "individual.road.frontage_road_width"
    ] = 0.0

    r = client.post("/api/review", json={"tables": tables})
    data = r.json()["data"]
    assert data["verdict"] == "mismatch"
    hits = data["layers"]["table5_2_to_table4"]
    hit = next(
        h for h in hits if h["factor_id"] == "individual.road.frontage_road_width"
    )
    assert hit["filed"] == 0
    assert hit["computed"] == 5
    assert "15m以上未滿20m" in hit["basis"]


def test_review_reports_price_impact(client, parsed):
    r = client.post("/api/review", json={"tables": parsed["tables"]})
    impact = r.json()["data"]["price_impact"]
    assert impact["filed"] == 212958
    assert impact["computed"] == 212958
    assert impact["diff_per_sqm"] == 0
    assert impact["benchmark_land_price"] == 213000
