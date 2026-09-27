"""Repository validation, against a mock transport: no test here touches the network."""

import json

import httpx
import pytest

from app.agent.accession_validator import (
    NO_PUBLIC_LOOKUP,
    NOT_FOUND,
    PRIVATE,
    UNCHECKED,
    VERIFIED,
    _Ncbi,
    datasets_linked_to_paper,
    validate_accessions,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ncbi(http) -> _Ncbi:
    return _Ncbi(http, min_interval=0)


def _json(data, status=200) -> httpx.Response:
    return httpx.Response(status, text=json.dumps(data))


GEO_SUMMARY = {"result": {"uids": ["200013486", "200029619"],
                          "200013486": {"accession": "GSE13486", "pubmedids": [19029902]},
                          "200029619": {"accession": "GSE29619", "pubmedids": [21743478]}}}


def _geo_handler(requests: list):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        url = str(request.url)
        if "esearch.fcgi" in url:
            return _json({"esearchresult": {"idlist": ["200013486", "200029619"]}})
        if "esummary.fcgi" in url:
            return _json(GEO_SUMMARY)
        if "geo/query/acc.cgi" in url:
            acc = request.url.params["acc"]
            if acc == "GSE55555":
                return httpx.Response(200, text=f"Accession {acc} is currently private")
            return httpx.Response(200, text="<!DOCTYPE HTML><html>not found</html>")
        return httpx.Response(500)
    return handler


@pytest.mark.asyncio
async def test_geo_owner_pmids_come_from_esummary_and_are_batched():
    requests = []
    async with _client(_geo_handler(requests)) as http:
        out = await validate_accessions([("GSE13486", "GEO"), ("GSE29619", "GEO")], http,
                                        ncbi=_ncbi(http))
    assert out["GSE13486"] == {"status": VERIFIED, "owner_pmids": ["19029902"], "detail": ""}
    assert out["GSE29619"]["owner_pmids"] == ["21743478"]
    # One esearch and one esummary for both accessions, not one pair per accession.
    assert len(requests) == 2
    assert "gse[ETYP]" in requests[0].url.params["term"]


@pytest.mark.asyncio
async def test_geo_miss_is_checked_on_the_accession_page():
    async with _client(_geo_handler([])) as http:
        out = await validate_accessions([("GSE55555", "GEO"), ("GSE66666", "GEO")], http,
                                        ncbi=_ncbi(http))
    assert out["GSE55555"]["status"] == PRIVATE
    assert out["GSE66666"]["status"] == NOT_FOUND


@pytest.mark.asyncio
async def test_network_error_is_unchecked_never_not_found():
    def handler(request):
        raise httpx.ConnectError("offline")
    async with _client(handler) as http:
        out = await validate_accessions(
            [("GSE13486", "GEO"), ("E-TABM-305", "ArrayExpress"), ("SRP018265", "SRA")],
            http, ncbi=_ncbi(http))
    assert {v["status"] for v in out.values()} == {UNCHECKED}


@pytest.mark.asyncio
async def test_rest_repositories_use_404_for_absent():
    def handler(request):
        url = str(request.url)
        if "PXD000001" in url:
            return _json({"references": [{"pubmedId": 12345}, {"pubmedId": None}]})
        if "E-TABM-305" in url:
            return _json({"section": {"subsections": [
                {"type": "Publication", "attributes": [{"name": "PubMed ID", "value": "18193047"}]}]}})
        if "api.github.com/repos/a/b" in url:
            return _json({"full_name": "a/b"})
        if "api.github.com" in url and "rate" in url:
            return httpx.Response(403)
        return httpx.Response(404)

    async with _client(handler) as http:
        out = await validate_accessions([
            ("PXD000001", "PRIDE"), ("PXD999999", "PRIDE"),
            ("E-TABM-305", "ArrayExpress"), ("E-MTAB-9", "ArrayExpress"),
            ("github.com/a/b", "GitHub"), ("NCT99999999", "ClinicalTrials.gov"),
        ], http, ncbi=_ncbi(http))
    assert out["PXD000001"] == {"status": VERIFIED, "owner_pmids": ["12345"], "detail": ""}
    assert out["PXD999999"]["status"] == NOT_FOUND
    assert out["E-TABM-305"]["owner_pmids"] == ["18193047"]
    assert out["E-MTAB-9"]["status"] == NOT_FOUND
    assert out["github.com/a/b"]["status"] == VERIFIED
    assert out["NCT99999999"]["status"] == NOT_FOUND


@pytest.mark.asyncio
async def test_rate_limit_or_server_error_is_unchecked():
    async with _client(lambda r: httpx.Response(429)) as http:
        out = await validate_accessions([("github.com/a/b", "GitHub")], http, ncbi=_ncbi(http))
    assert out["github.com/a/b"]["status"] == UNCHECKED


@pytest.mark.asyncio
async def test_ega_empty_body_means_absent():
    def handler(request):
        if "EGAS00001000001" in str(request.url):
            return _json({"accession_id": "EGAS00001000001"})
        return httpx.Response(200, text="")
    async with _client(handler) as http:
        out = await validate_accessions([("EGAS00001000001", "EGA"), ("EGAS99999999999", "EGA")],
                                        http, ncbi=_ncbi(http))
    assert out["EGAS00001000001"]["status"] == VERIFIED
    assert out["EGAS99999999999"]["status"] == NOT_FOUND


@pytest.mark.asyncio
async def test_sra_owner_comes_from_elink():
    def handler(request):
        url = str(request.url)
        if "esearch.fcgi" in url:
            return _json({"esearchresult": {"idlist": ["307458"]}})
        if "elink.fcgi" in url:
            return _json({"linksets": [{"linksetdbs": [{"dbto": "pubmed", "links": ["555"]}]}]})
        return httpx.Response(500)
    async with _client(handler) as http:
        out = await validate_accessions([("SRP018265", "SRA")], http, ncbi=_ncbi(http))
    assert out["SRP018265"] == {"status": VERIFIED, "owner_pmids": ["555"], "detail": ""}


@pytest.mark.asyncio
async def test_immport_uses_the_injected_lookup():
    async def lookup(sdy):
        return {"SDY212": (True, ["23591775", "25834109"]), "SDY9": (False, [])}.get(sdy)

    async with _client(lambda r: httpx.Response(500)) as http:
        out = await validate_accessions([("SDY212", "ImmPort"), ("SDY9", "ImmPort"),
                                         ("SDY404", "ImmPort")], http, immport_lookup=lookup,
                                        ncbi=_ncbi(http))
        no_db = await validate_accessions([("SDY1", "ImmPort")], http, ncbi=_ncbi(http))
    assert out["SDY212"]["owner_pmids"] == ["23591775", "25834109"]
    assert out["SDY9"]["status"] == NOT_FOUND
    assert out["SDY404"]["status"] == UNCHECKED  # lookup returned None: database unreachable
    assert no_db["SDY1"]["status"] == UNCHECKED


@pytest.mark.asyncio
async def test_cache_skips_repeat_lookups():
    requests = []
    cache = {}
    async with _client(_geo_handler(requests)) as http:
        ncbi = _ncbi(http)
        await validate_accessions([("GSE13486", "GEO")], http, cache=cache, ncbi=ncbi)
        await validate_accessions([("GSE13486", "GEO")], http, cache=cache, ncbi=ncbi)
    assert len(requests) == 2  # the first call's esearch + esummary only


@pytest.mark.asyncio
async def test_reverse_lookup_keeps_only_series():
    def handler(request):
        url = str(request.url)
        db = request.url.params.get("db")
        if "elink.fcgi" in url:
            links = {"gds": ["200013486", "300000001"], "bioproject": []}[db]
            return _json({"linksets": [{"linksetdbs": [{"dbto": db, "links": links}]}]})
        if "esummary.fcgi" in url:
            return _json({"result": {"uids": ["200013486", "300000001"],
                                     "200013486": {"accession": "GSE13486"},
                                     "300000001": {"accession": "GSM1"}}})
        return httpx.Response(500)
    async with _client(handler) as http:
        assert await datasets_linked_to_paper("19029902", _ncbi(http)) == [("GSE13486", "GEO")]


@pytest.mark.asyncio
async def test_ncbi_429_is_retried():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(429)
        return _json({"esearchresult": {"idlist": ["1"]}})
    async with _client(handler) as http:
        assert await _ncbi(http).search("sra", "x") == ["1"]
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_reverse_lookup_asks_bioproject_only_when_geo_links_nothing():
    asked = []

    def handler(request):
        db = request.url.params.get("db")
        asked.append((str(request.url).split("?")[0].rsplit("/", 1)[-1], db))
        if "elink.fcgi" in str(request.url):
            links = {"gds": [], "bioproject": ["205279"]}[db]
            return _json({"linksets": [{"linksetdbs": [{"dbto": db, "links": links}] if links else []}]})
        return _json({"result": {"uids": ["205279"], "205279": {"project_acc": "PRJNA205279"}}})
    async with _client(handler) as http:
        assert await datasets_linked_to_paper("24725414", _ncbi(http)) == [("PRJNA205279", "BioProject")]
    assert ("elink.fcgi", "bioproject") in asked


@pytest.mark.asyncio
async def test_new_repositories_absent_and_owner_rules():
    def handler(request):
        url = str(request.url)
        if "metabolights/ws/studies/MTBLS1" in url and url.endswith("MTBLS1"):
            return _json({"mtblsStudy": {"publications": [{"pubMedID": "17190852"}]}})
        if "metabolights" in url:
            return httpx.Response(400, text='{"err":"MetabolightsException: There is no study."}')
        if "study_id/ST000001" in url:
            return _json({"study_id": "ST000001"})
        if "study_id/" in url:
            return _json([])  # Metabolomics Workbench: absent is a 200 with an empty list
        if "rcsb.org/rest/v1/core/entry/6VXX" in url:
            return _json({"rcsb_primary_citation": {"pdbx_database_id_pub_med": 32075877}})
        if "emdb/api/entry/EMD-21374" in url:
            return _json({"crossreferences": {"citation_list": {"primary_citation": {"journal_citation": {
                "external_references": [{"type_": "PUBMED", "valueOf_": "32075877"},
                                        {"type_": "DOI", "valueOf_": "doi:10.1126/x"}]}}}}})
        if "doi.org/api/handles/10.5061/dryad.j1fd7" in url:
            return _json({"responseCode": 1})
        return httpx.Response(404)

    async with _client(handler) as http:
        out = await validate_accessions([
            ("MTBLS1", "MetaboLights"), ("MTBLS99", "MetaboLights"),
            ("ST000001", "Metabolomics Workbench"), ("ST999999", "Metabolomics Workbench"),
            ("6VXX", "PDB"), ("0ZZZ", "PDB"), ("EMD-21374", "EMDB"),
            ("10.5061/dryad.j1fd7", "Dryad"), ("10.17632/zz.1", "Mendeley Data"),
            ("SCP9999", "Single Cell Portal"), ("osf.io/zzzzq", "OSF"),
        ], http, ncbi=_ncbi(http))
    assert out["MTBLS1"] == {"status": VERIFIED, "owner_pmids": ["17190852"], "detail": ""}
    assert out["MTBLS99"]["status"] == NOT_FOUND
    assert out["ST000001"]["status"] == VERIFIED and out["ST999999"]["status"] == NOT_FOUND
    assert out["6VXX"]["owner_pmids"] == ["32075877"] and out["0ZZZ"]["status"] == NOT_FOUND
    assert out["EMD-21374"]["owner_pmids"] == ["32075877"]
    assert out["10.5061/dryad.j1fd7"]["status"] == VERIFIED
    assert out["10.17632/zz.1"]["status"] == NOT_FOUND
    assert out["SCP9999"]["status"] == NOT_FOUND and out["osf.io/zzzzq"]["status"] == NOT_FOUND


@pytest.mark.asyncio
async def test_biosample_and_genbank_go_through_ncbi():
    def handler(request):
        url = str(request.url)
        if "esearch.fcgi" in url:
            db = request.url.params["db"]
            return _json({"esearchresult": {"idlist": ["1"] if request.url.params["term"].startswith(
                ("SAMN02604091", "MN908947")) else []}}) if db in ("biosample", "nuccore") else httpx.Response(500)
        if "elink.fcgi" in url:
            return _json({"linksets": [{"linksetdbs": [{"dbto": "pubmed", "links": ["32015508"]}]}]})
        return httpx.Response(500)
    async with _client(handler) as http:
        out = await validate_accessions([("SAMN02604091", "BioSample"), ("SAMN9", "BioSample"),
                                         ("MN908947.3", "GenBank")], http, ncbi=_ncbi(http))
    assert out["SAMN02604091"]["status"] == VERIFIED and out["SAMN9"]["status"] == NOT_FOUND
    assert out["MN908947.3"] == {"status": VERIFIED, "owner_pmids": ["32015508"], "detail": ""}


@pytest.mark.asyncio
async def test_repositories_without_a_lookup_are_unchecked_never_dropped():
    async with _client(lambda r: httpx.Response(200, text="<html>anything</html>")) as http:
        out = await validate_accessions([("CRA001234", "GSA"), ("iedb.org", "IEDB"),
                                         ("EPI_ISL_402124", "GISAID"), ("ISRCTN12345678", "ISRCTN")],
                                        http, ncbi=_ncbi(http))
    for v in out.values():
        assert v["status"] == UNCHECKED and v["detail"].startswith(NO_PUBLIC_LOOKUP)
