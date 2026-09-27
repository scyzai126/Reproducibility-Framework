"""Locating deposited datasets, against a mock transport: no test here touches the network."""

import json

import httpx
import pytest

from app.agent.accession_validator import _Ncbi
from app.agent.data_locator import (
    CONTROLLED,
    LOGIN,
    MAX_FILES,
    PRIVATE_ACCESS,
    geo_folder,
    human_size_to_bytes,
    locate,
    parse_filelist,
    parse_geo_text,
    parse_listing,
)

GEO_TEXT = """^SERIES = GSE169159
!Series_title = Innate immune response to the pfizer mrna vaccine
!Series_pubmed_id = 34252919
!Series_type = Expression profiling by high throughput sequencing
!Series_platform_id = GPL15520
!Series_sample_id = GSM5900628
!Series_sample_id = GSM5900629
!Series_relation = SuperSeries of: GSE169158
!Series_relation = BioProject: https://www.ncbi.nlm.nih.gov/bioproject/PRJNA715457
!Series_relation = SRA: https://www.ncbi.nlm.nih.gov/sra?term=SRP311216
"""

NCBI_LISTING = """<pre><a href="/geo/series/GSE169nnn/GSE169159/">Parent Directory</a>   -
<a href="GSE169159_RAW.tar">GSE169159_RAW.tar</a>                  2025-09-30 18:10   21M
<a href="GSE169159_counts.csv.gz">GSE169159_counts.csv.gz</a>      2025-09-30 18:10  5.0M
<a href="filelist.txt">filelist.txt</a>                            2025-09-30 18:10   12K
</pre>"""

MATRIX_LISTING = """<a href="GSE169159_series_matrix.txt.gz">GSE169159_series_matrix.txt.gz</a>   2026-07-01 01:33  8.0K"""

EBI_LISTING = """<tr><td><a href="/biostudies/fire/E-TABM-/305/E-TABM-305/">Parent Directory</a></td><td>&nbsp;</td><td align="right">  - </td></tr>
<tr><td valign="top"><img src="/icons/text.gif"></td><td><a href="E-TABM-305.sdrf.txt">E-TABM-305.sdrf.txt</a></td><td align="right">2024-06-13 11:40  </td><td align="right">1.0M</td><td>&nbsp;</td></tr>"""

FILELIST = ("#Archive/File\tName\tTime\tSize\tType\n"
            "Archive\tGSE169159_RAW.tar\t09/30/2025 18:10:27\t22026240\tTAR\n"
            "File\tGSM5900628_a.txt.gz\t02/15/2022 12:29:48\t119062\tTXT\n"
            "File\tGSM5900629_b.txt.gz\t02/15/2022 12:29:48\t118028\tTXT\n")

RUNINFO = ("Run,size_MB,LibraryStrategy\n"
           "SRR1,1000,RNA-Seq\nSRR2,1500,RNA-Seq\n")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ncbi(http) -> _Ncbi:
    return _Ncbi(http, min_interval=0)


# ------------------------------------------------------------------ parsers


def test_geo_folder():
    assert geo_folder("GSE13486") == "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE13nnn/GSE13486/"
    assert geo_folder("GSE999") == "https://ftp.ncbi.nlm.nih.gov/geo/series/GSEnnn/GSE999/"
    assert geo_folder("GSM339809") == "https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM339nnn/GSM339809/"


def test_parse_geo_text():
    fields = parse_geo_text(GEO_TEXT)
    assert fields["title"] == ["Innate immune response to the pfizer mrna vaccine"]
    assert fields["sample_id"] == ["GSM5900628", "GSM5900629"]
    assert len(fields["relation"]) == 3


def test_listings_in_both_layouts():
    ncbi = parse_listing(NCBI_LISTING, "https://x/suppl/")
    assert [(f["name"], f["size_bytes"]) for f in ncbi] == [
        ("GSE169159_RAW.tar", 21 * 1024 ** 2), ("GSE169159_counts.csv.gz", 5 * 1024 ** 2)]
    assert ncbi[0]["url"] == "https://x/suppl/GSE169159_RAW.tar"
    ebi = parse_listing(EBI_LISTING, "https://y/Files")
    assert [(f["name"], f["size_bytes"]) for f in ebi] == [("E-TABM-305.sdrf.txt", 1024 ** 2)]


def test_filelist_gives_exact_archive_size_and_content_count():
    assert parse_filelist(FILELIST) == ({"GSE169159_RAW.tar": 22026240}, 2)


def test_human_size():
    assert human_size_to_bytes("8.0K") == 8192 and human_size_to_bytes("480") == 480
    assert human_size_to_bytes("-") is None


# ------------------------------------------------------------------ GEO


def _geo_handler(requests=None):
    def handler(request):
        if requests is not None:
            requests.append(str(request.url))
        url = str(request.url)
        if "acc.cgi" in url:
            return httpx.Response(200, text=GEO_TEXT)
        if url.endswith("/suppl/filelist.txt"):
            return httpx.Response(200, text=FILELIST)
        if url.endswith("/suppl/"):
            return httpx.Response(200, text=NCBI_LISTING)
        if url.endswith("/matrix/"):
            return httpx.Response(200, text=MATRIX_LISTING)
        if "runinfo" in url:
            return httpx.Response(200, text=RUNINFO)
        return httpx.Response(404)
    return handler


@pytest.mark.asyncio
async def test_geo_series_location():
    async with _client(_geo_handler()) as http:
        loc = await locate("GSE169159", "GEO", http, _ncbi(http), status="verified")
    assert loc["error"] is None
    assert loc["landing_page"].endswith("acc=GSE169159")
    assert loc["download"]["https"] == "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE169nnn/GSE169159/"
    assert loc["download"]["ftp"].startswith("ftp://ftp.ncbi.nlm.nih.gov/geo/series/")
    assert loc["summary"]["samples"] == 2 and loc["summary"]["platforms"] == ["GPL15520"]
    assert loc["summary"]["files_inside_raw_tar"] == 2
    names = {f["name"]: f for f in loc["files"]}
    assert set(names) == {"GSE169159_RAW.tar", "GSE169159_counts.csv.gz", "GSE169159_series_matrix.txt.gz"}
    assert names["GSE169159_RAW.tar"]["size_bytes"] == 22026240 and names["GSE169159_RAW.tar"]["size_exact"]
    assert not names["GSE169159_counts.csv.gz"]["size_exact"]
    related = {r["accession"]: r for r in loc["related"]}
    assert related["GSE169158"]["relation"] == "SuperSeries of"
    assert related["PRJNA715457"]["repository"] == "BioProject"
    assert (related["SRP311216"]["runs"], related["SRP311216"]["total_size_mb"]) == (2, 2500)
    assert related["SRP311216"]["library_strategies"] == ["RNA-Seq"]


@pytest.mark.asyncio
async def test_private_geo_is_not_listed():
    async with _client(lambda r: httpx.Response(500)) as http:
        loc = await locate("GSE55555", "GEO", http, _ncbi(http), status="private")
    assert loc["access"] == PRIVATE_ACCESS and loc["files"] == [] and loc["error"] is None


@pytest.mark.asyncio
async def test_failed_request_keeps_the_record_and_says_why():
    async with _client(lambda r: httpx.Response(503)) as http:
        loc = await locate("GSE169159", "GEO", http, _ncbi(http))
    assert loc["landing_page"].endswith("acc=GSE169159")
    assert "could not be read" in loc["error"]

    def boom(request):
        raise httpx.ConnectError("offline")
    async with _client(boom) as http:
        loc = await locate("10.5281/zenodo.6960", "Zenodo", http, _ncbi(http))
    assert loc["error"].startswith("Zenodo lookup failed")


@pytest.mark.asyncio
async def test_cache_avoids_refetching():
    requests = []
    cache = {}
    async with _client(_geo_handler(requests)) as http:
        await locate("GSE169159", "GEO", http, _ncbi(http), cache=cache)
        n = len(requests)
        await locate("GSE169159", "GEO", http, _ncbi(http), cache=cache)
    assert len(requests) == n


# ------------------------------------------------------------------ other repositories


@pytest.mark.asyncio
async def test_zenodo_pride_biostudies_datacite():
    def handler(request):
        url = str(request.url)
        if "zenodo.org/api/records/6960" in url:
            return httpx.Response(200, text=json.dumps({"metadata": {"title": "eLife data"}, "files": [
                {"key": "eLife.00299.rar", "size": 698128573,
                 "links": {"self": "https://zenodo.org/api/records/6960/files/eLife.00299.rar/content"}}]}))
        if "pride/ws/archive/v2/projects/PXD000001/files" in url:
            base = "ftp://ftp.pride.ebi.ac.uk/pride/data/archive/2012/03/PXD000001"
            return httpx.Response(200, text=json.dumps([
                {"fileName": "a.raw", "fileSizeBytes": 10,
                 "publicFileLocations": [{"name": "FTP Protocol", "value": f"{base}/a.raw"}]},
                {"fileName": "b.mgf", "fileSizeBytes": 20,
                 "publicFileLocations": [{"name": "FTP Protocol", "value": f"{base}/generated/b.mgf"}]}]))
        if url.endswith("/studies/E-TABM-305/info"):
            return httpx.Response(200, text=json.dumps({
                "files": 1242, "isPublic": True,
                "httpLink": "https://ftp.ebi.ac.uk/biostudies/fire/E-TABM-/305/E-TABM-305",
                "ftpLink": "ftp://ftp.ebi.ac.uk/biostudies/fire/E-TABM-/305/E-TABM-305"}))
        if url.endswith("E-TABM-305/Files/"):
            return httpx.Response(200, text=EBI_LISTING)
        if "api.datacite.org/dois/10.5061/dryad.j1fd7" in url:
            return httpx.Response(200, text=json.dumps({"data": {"attributes": {
                "url": "https://datadryad.org/dataset/doi:10.5061/dryad.j1fd7", "publisher": "Dryad",
                "titles": [{"title": "Data from: x"}]}}}))
        return httpx.Response(404)

    async with _client(handler) as http:
        ncbi = _ncbi(http)
        zen = await locate("10.5281/zenodo.6960", "Zenodo", http, ncbi)
        pride = await locate("PXD000001", "PRIDE", http, ncbi)
        ae = await locate("E-TABM-305", "ArrayExpress", http, ncbi)
        dryad = await locate("10.5061/dryad.j1fd7", "Dryad", http, ncbi)
    assert zen["landing_page"] == "https://zenodo.org/records/6960"
    assert (zen["file_count"], zen["total_size_bytes"]) == (1, 698128573)
    assert pride["download"]["ftp"] == "ftp://ftp.pride.ebi.ac.uk/pride/data/archive/2012/03/PXD000001/"
    assert pride["total_size_bytes"] == 30
    assert ae["download"]["ftp"].endswith("E-TABM-305") and ae["file_count"] == 1242
    assert ae["landing_page"].endswith("/arrayexpress/studies/E-TABM-305")
    assert dryad["landing_page"] == "https://datadryad.org/dataset/doi:10.5061/dryad.j1fd7"
    assert dryad["summary"]["publisher"] == "Dryad"


@pytest.mark.asyncio
async def test_immport_and_controlled_access_need_no_network():
    async def title(sdy):
        return "Yellow fever vaccine study"
    async with _client(lambda r: httpx.Response(500)) as http:
        imm = await locate("SDY1264", "ImmPort", http, _ncbi(http), title_lookup=title)
        gap = await locate("phs000635.v1.p1", "dbGaP", http, _ncbi(http))
        ega = await locate("EGAD00001000001", "EGA", http, _ncbi(http))
        other = await locate("github.com/a/b", "GitHub", http, _ncbi(http))
    assert (imm["access"], imm["summary"]["title"]) == (LOGIN, "Yellow fever vaccine study")
    assert imm["landing_page"] == "https://www.immport.org/shared/study/SDY1264"
    assert gap["access"] == CONTROLLED and "dbGaP Authorized Access" in gap["note"]
    assert ega["landing_page"].endswith("/datasets/EGAD00001000001")
    assert other is None


@pytest.mark.asyncio
async def test_file_list_is_capped_but_counts_stay_exact():
    files = [{"key": f"f{i}", "size": 1, "links": {"self": "u"}} for i in range(MAX_FILES + 5)]

    def handler(request):
        return httpx.Response(200, text=json.dumps({"metadata": {}, "files": files}))
    async with _client(handler) as http:
        loc = await locate("10.5281/zenodo.1", "Zenodo", http, _ncbi(http))
    assert len(loc["files"]) == MAX_FILES and loc["files_truncated"]
    assert (loc["file_count"], loc["total_size_bytes"]) == (MAX_FILES + 5, MAX_FILES + 5)
