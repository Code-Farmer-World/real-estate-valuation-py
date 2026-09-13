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


def test_rulesets_are_complete(client):
    """三套規則集都補完了。

    改以 ruleset_id 為索引，不再假設每種 kind 只有一組。原本用 kind 當鍵，
    在區域因素只有金山一組時可行；加入樹林住宅之後兩組都是 regional，
    dict 生成式會被後者覆寫，測試會誤判成「金山有 29 項」。
    """
    r = client.get("/api/rulesets")
    assert r.status_code == 200
    rulesets = r.json()["data"]["rulesets"]
    by_id = {x["ruleset_id"]: x for x in rulesets}

    expected = {
        "jinshan-commercial-individual": ("individual", 19),
        "jinshan-commercial-regional": ("regional", 28),
        "shulin-residential-regional": ("regional", 29),
    }
    assert set(by_id) == set(expected), "規則集清單與預期不符：%s" % sorted(by_id)
    for rid, (kind, count) in expected.items():
        assert by_id[rid]["kind"] == kind, rid
        assert by_id[rid]["factor_count"] == count, rid

    # status 只有兩份區域因素規則集宣告了，個別因素那份沒有這個欄位。
    assert by_id["jinshan-commercial-regional"]["status"] == "complete"
    assert by_id["shulin-residential-regional"]["status"] == "complete"


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


def test_review_can_now_check_every_regional_factor(client, parsed):
    """第一層完整了：28 個區域因素全部能從表1 的量測值反推等級。

    這條測試守的是「查不動的項目」必須是空的。規則集一旦有細項被移除
    或改名，這裡會立刻紅，而不是安靜地少查幾項還顯示「全部通過」。
    """
    r = client.post("/api/review", json={"tables": parsed["tables"]})
    data = r.json()["data"]
    assert data["not_checkable"] == []
    assert data["verdict"] == "match"


def test_review_catches_a_wrong_grade_in_table1(client, parsed):
    """第一層：現場量到 18 米，表1 自己卻打成第 2 級（稍優）。

    這是白話說明的「錯法一」，也是三層裡最有價值的一層——錯在源頭會一路
    連鎖到賠償金，而人工最難抓的就是這層（得拿著尺與基準表一項一項核）。
    區域因素基準表寫「普通：15m以上未滿20m」，所以 18m 只能是第 3 級。
    """
    tables = copy.deepcopy(parsed["tables"])
    tables["表1"]["grades"]["regional.transport.main_road_width"]["grade"] = 2

    r = client.post("/api/review", json={"tables": tables})
    data = r.json()["data"]
    assert data["verdict"] == "mismatch"
    hits = data["layers"]["table1_internal"]
    hit = next(h for h in hits if h["factor_id"] == "regional.transport.main_road_width")
    assert hit["filed"]["grade"] == 2
    assert hit["computed"]["grade"] == 3
    assert "18" in hit["basis"]
    assert "15m以上未滿20m" in hit["basis"]


def test_review_explains_how_it_derived_each_value(client, parsed):
    """取值方式要說得出來——尤其是多設施取最近這種會影響結果的判斷。"""
    tables = copy.deepcopy(parsed["tables"])
    tables["表1"]["grades"]["regional.special.utility"]["grade"] = 1

    r = client.post("/api/review", json={"tables": tables})
    hits = r.json()["data"]["layers"]["table1_internal"]
    hit = next(h for h in hits if h["factor_id"] == "regional.special.utility")
    # 變電所 700m 與儲油槽 440m，取最近的 440m → 劣
    assert "440" in hit["basis"]
    assert "取最近" in hit["basis"]
    assert hit["computed"]["grade"] == 5


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


# ---------- 產表 ----------


def test_forms_endpoint_returns_three_downloadable_files(client):
    """官方要的最終成果：三張填好的書表 PDF。

    回傳的是檔案清單與下載連結而不是檔案本身——信封規定 body 必須是
    `{data, error}`，二進位塞不進去。形狀比照前端既有的 UploadedResponse。
    """
    with open(paths.require(paths.SAMPLE_FORMS_PDF), "rb") as f:
        r = client.post("/api/forms", files={"file": ("a.pdf", f, "application/pdf")})
    assert r.status_code == 200, r.text
    _envelope(r.json())

    data = r.json()["data"]
    assert [x["table"] for x in data["files"]] == ["表1", "表5-2", "表4"]

    for item in data["files"]:
        got = client.get(item["link"])
        assert got.status_code == 200, item["link"]
        assert got.headers["content-type"] == "application/pdf"
        assert got.content.startswith(b"%PDF")
        assert len(got.content) > 10_000


def test_forms_rejects_non_pdf(client):
    r = client.post("/api/forms", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 422
    _envelope(r.json())


def test_form_download_rejects_unknown_filename(client):
    """下載端點只認得我們自己產出的那三個檔名，擋掉路徑穿越。"""
    r = client.get("/api/forms/deadbeef/../../etc/passwd")
    assert r.status_code in (400, 404)


# ---------- CORS ----------
#
# CORS 設錯在畫面上是「沒有原因的網路錯誤」——前端攔截器對「請求已發出但
# 沒收到回應」一律記成網路錯誤，看不出是被瀏覽器擋在 preflight。
# 部署當天沒有時間從那個症狀回推原因，所以在這裡綁住。


def _preflight(c, origin):
    return c.options(
        "/api/parse",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
        },
    )


def test_cors_allows_localhost_on_any_port(client):
    """vite 遇到埠被占用會自動往上找，所以埠號不能寫死。"""
    for origin in ("http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:4173"):
        r = _preflight(client, origin)
        assert r.headers.get("access-control-allow-origin") == origin, origin


def test_cors_rejects_unlisted_origin_by_default(client):
    """沒設環境變數時只有本機來源過得去，不是全開。"""
    r = _preflight(client, "http://12.34.56.78")
    assert "access-control-allow-origin" not in r.headers


def test_cors_allows_origins_from_env(monkeypatch):
    """環境變數要真的接到 middleware 上。

    這條測的是那條線本身：`VALUATION_ALLOWED_ORIGINS` 在 import 當下讀取，
    所以得 reload 才驗得到，不能只驗字串切割。部署到 EC2 就是靠這個放行。
    """
    import importlib

    import api.main

    monkeypatch.setenv("VALUATION_ALLOWED_ORIGINS", "http://12.34.56.78, https://demo.example.com")
    try:
        reloaded = importlib.reload(api.main)
        c = TestClient(reloaded.app)

        for origin in ("http://12.34.56.78", "https://demo.example.com"):
            r = _preflight(c, origin)
            assert r.headers.get("access-control-allow-origin") == origin, origin

        # 本機那條仍然有效，兩者是並存不是取代
        assert _preflight(c, "http://localhost:5173").headers.get(
            "access-control-allow-origin"
        ) == "http://localhost:5173"

        # 沒列到的仍然擋掉
        assert "access-control-allow-origin" not in _preflight(c, "http://evil.example").headers
    finally:
        # 還原模組狀態，避免污染同一個 session 的其他測試
        monkeypatch.delenv("VALUATION_ALLOWED_ORIGINS", raising=False)
        importlib.reload(api.main)
