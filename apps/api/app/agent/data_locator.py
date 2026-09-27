"""Where a deposited dataset actually sits: its record page, download folder and files.

accession_validator answers "does this ID exist, and whose is it?". This module answers the next
question for the IDs a paper deposited: where is the data, and what is in it? Nothing is
downloaded -- every lookup reads a record or a directory listing.

What each repository exposes (probed live, 2026-09):

| repository            | read from                                              | files listed               |
|-----------------------|--------------------------------------------------------|----------------------------|
| GEO series (GSE)      | text record; suppl/ and matrix/ listings; filelist.txt | suppl + series matrix      |
| GEO sample / dataset  | text record                                            | its supplementary files    |
| SRA                   | runinfo CSV                                            | none: a run/size summary   |
| ArrayExpress/BioStudies | /info (http and ftp links), Files/ listing           | names, listed sizes        |
| PRIDE                 | /projects/{acc}/files                                  | names, sizes, FTP URLs     |
| MetaboLights          | /ws/studies/{acc}/files                                | study files                |
| MassIVE               | PROXI datasetLink                                      | none: FTP location         |
| Zenodo                | /api/records/{id}                                      | names, sizes, URLs         |
| figshare              | DataCite + figshare API                                | names, sizes, URLs         |
| Dryad, Mendeley Data, | DataCite                                               | none: landing page         |
|   Dataverse, immuneACCESS |                                                    |                            |
| ImmPort               | landing page (+ title from the local DB)               | none: files need a login   |
| dbGaP, EGA, JGA       | landing page                                           | none: controlled access    |

A failed request never loses the record: the location keeps what was found and says what
failed in `error`. Every NCBI request goes through accession_validator._Ncbi, so the rate
limit and 429 retry hold across the whole run.
"""

import csv
import io
import logging
import re
from typing import Awaitable, Callable, Optional

import httpx

from app.agent.accession_validator import _Ncbi

logger = logging.getLogger(__name__)

#: Most files kept per record. file_count and total_size_bytes stay exact past it.
MAX_FILES = 200

OPEN, LOGIN, CONTROLLED, PRIVATE_ACCESS = "open", "login", "controlled", "private"

#: Repositories this module can locate.
LOCATABLE = {
    "GEO", "SRA", "ArrayExpress", "BioStudies", "PRIDE", "MetaboLights", "MassIVE", "Zenodo",
    "figshare", "Dryad", "Mendeley Data", "Dataverse", "immuneACCESS", "ImmPort", "dbGaP", "EGA", "JGA",
}

#: `sdy -> title or None`, from the local ImmPort database. Optional.
TitleLookup = Callable[[str], Awaitable[Optional[str]]]

_NCBI_FTP = "ftp.ncbi.nlm.nih.gov"
_GEO_DIRS = {"GSE": "series", "GSM": "samples", "GDS": "datasets"}
_SIZE_UNITS = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
#: One row of an Apache directory listing, in either of its two layouts: plain `<pre>` text
#: (NCBI) or an HTML table (EBI), where cell tags sit between the name, date and size.
_LISTING_ROW = re.compile(
    r'<a href="([^"?/][^"]*)">[^<]*</a>(?:\s|<[^>]+>)*\d{4}-\d{2}-\d{2} \d{2}:\d{2}'
    r'(?:\s|<[^>]+>|&nbsp;)*([\d.]+[KMGT]?|-)')


def _empty(landing_page: str, access: str = OPEN) -> dict:
    return {"landing_page": landing_page, "access": access, "download": {}, "summary": {},
            "files": [], "file_count": 0, "total_size_bytes": None, "files_truncated": False,
            "related": [], "note": None, "error": None}


def _set_files(location: dict, files: list[dict]) -> None:
    """Store at most MAX_FILES files; keep the count and the total size exact."""
    sizes = [f.get("size_bytes") for f in files]
    location["file_count"] = len(files)
    location["total_size_bytes"] = sum(sizes) if files and all(s is not None for s in sizes) else (
        sum(s for s in sizes if s is not None) or None)
    location["files"] = files[:MAX_FILES]
    location["files_truncated"] = len(files) > MAX_FILES


def _add_error(location: dict, message: str) -> None:
    location["error"] = f"{location['error']}; {message}" if location["error"] else message


def human_size_to_bytes(text: str) -> Optional[int]:
    """"21M" -> 22020096. Directory listings round, so the result is approximate."""
    m = re.fullmatch(r"([\d.]+)([KMGT]?)", text.strip())
    return int(float(m.group(1)) * _SIZE_UNITS[m.group(2)]) if m else None


def parse_listing(html: str, base_url: str) -> list[dict]:
    """Files in an Apache-style directory listing (GEO, EBI FTP over HTTPS). Folders are skipped."""
    files = []
    for name, size in _LISTING_ROW.findall(html):
        if name.endswith("/") or name == "filelist.txt":
            continue
        files.append({"name": name, "size_bytes": human_size_to_bytes(size) if size != "-" else None,
                      "size_exact": False, "url": base_url.rstrip("/") + "/" + name})
    return files


# --------------------------------------------------------------------------- GEO


def geo_folder(accession: str) -> str:
    """HTTPS folder of a GEO record: GSE13486 -> .../geo/series/GSE13nnn/GSE13486/."""
    prefix, digits = accession[:3], accession[3:]
    stub = f"{prefix}{digits[:-3]}nnn" if len(digits) > 3 else f"{prefix}nnn"
    return f"https://{_NCBI_FTP}/geo/{_GEO_DIRS[prefix]}/{stub}/{accession}/"


def parse_geo_text(text: str) -> dict[str, list[str]]:
    """`!Series_title = X` lines -> {"title": [X], ...} (the Series_/Sample_/... prefix dropped)."""
    fields: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = re.match(r"!\w+?_(\w+) = (.*)", line)
        if m:
            fields.setdefault(m.group(1), []).append(m.group(2).strip())
    return fields


def parse_filelist(text: str) -> tuple[dict[str, int], int]:
    """GEO suppl/filelist.txt -> ({archive name: exact size}, number of files inside archives)."""
    archives, inside = {}, 0
    for row in csv.reader(io.StringIO(text), delimiter="\t"):
        if len(row) < 4 or row[0].startswith("#"):
            continue
        if row[0] == "Archive" and row[3].isdigit():
            archives[row[1]] = int(row[3])
        elif row[0] == "File":
            inside += 1
    return archives, inside


def _geo_related(fields: dict[str, list[str]]) -> list[dict]:
    related = []
    for rel in fields.get("relation", []):
        kind, _, value = rel.partition(":")
        value = value.strip()
        if kind in ("SuperSeries of", "SubSeries of"):
            related.append({"accession": value, "repository": "GEO", "relation": kind,
                            "url": f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={value}"})
        elif kind == "SRA":
            acc = value.rsplit("term=", 1)[-1]
            related.append({"accession": acc, "repository": "SRA", "url": value})
        elif kind == "BioProject":
            related.append({"accession": value.rstrip("/").rsplit("/", 1)[-1], "repository": "BioProject",
                            "url": value})
    return related


async def sra_summary(accession: str, ncbi: _Ncbi) -> dict:
    """Run count, total size and library strategies of an SRA study/experiment/run, from runinfo."""
    resp = await ncbi.fetch("https://trace.ncbi.nlm.nih.gov/Traces/sra-db-be/runinfo", {"acc": accession})
    resp.raise_for_status()
    rows = [r for r in csv.DictReader(io.StringIO(resp.text)) if r.get("Run")]
    size_mb = sum(int(r["size_MB"]) for r in rows if (r.get("size_MB") or "").isdigit())
    return {"runs": len(rows), "total_size_mb": size_mb,
            "library_strategies": sorted({r["LibraryStrategy"] for r in rows if r.get("LibraryStrategy")}),
            "how_to_download": f"prefetch {accession}  (NCBI sra-tools; then fasterq-dump)"}


async def locate_geo(accession: str, ncbi: _Ncbi, status: Optional[str] = None) -> dict:
    landing = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={accession}"
    if status == "private":
        location = _empty(landing, PRIVATE_ACCESS)
        location["note"] = "GEO reports this record as private: not released yet, so there is nothing to list"
        return location

    location = _empty(landing)
    folder = geo_folder(accession)
    location["download"] = {"https": folder, "ftp": folder.replace("https://", "ftp://")}

    resp = await ncbi.fetch("https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi",
                            {"acc": accession, "targ": "self", "form": "text", "view": "brief"})
    fields = parse_geo_text(resp.text) if resp.status_code == 200 else {}
    if not fields:
        _add_error(location, f"GEO record could not be read (HTTP {resp.status_code})")
        return location

    location["summary"] = {
        "title": (fields.get("title") or [None])[0],
        "type": fields.get("type", []),
        "platforms": fields.get("platform_id", []),
        "samples": len(fields.get("sample_id", [])) or None,
        "pubmed_ids": fields.get("pubmed_id", []),
    }
    location["related"] = _geo_related(fields)

    if not accession.startswith("GSE"):
        files = [{"name": url.rsplit("/", 1)[-1], "size_bytes": None, "size_exact": False,
                  "url": url.replace("ftp://", "https://")}
                 for url in fields.get("supplementary_file", []) if url and url != "NONE"]
        _set_files(location, files)
    else:
        files = []
        suppl = folder + "suppl/"
        resp = await ncbi.fetch(suppl, {})
        if resp.status_code == 200:
            files += parse_listing(resp.text, suppl)
            lst = await ncbi.fetch(suppl + "filelist.txt", {})
            if lst.status_code == 200:
                archives, inside = parse_filelist(lst.text)
                for f in files:
                    if f["name"] in archives:
                        f["size_bytes"], f["size_exact"] = archives[f["name"]], True
                if inside:
                    location["summary"]["files_inside_raw_tar"] = inside
        elif resp.status_code != 404:  # a series with no supplementary files has no suppl/
            _add_error(location, f"suppl/ listing failed (HTTP {resp.status_code})")
        matrix = folder + "matrix/"
        resp = await ncbi.fetch(matrix, {})
        if resp.status_code == 200:
            files += parse_listing(resp.text, matrix)
        elif resp.status_code != 404:
            _add_error(location, f"matrix/ listing failed (HTTP {resp.status_code})")
        _set_files(location, files)

    for rel in location["related"]:
        if rel["repository"] == "SRA":
            try:
                rel.update(await sra_summary(rel["accession"], ncbi))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                _add_error(location, f"SRA summary for {rel['accession']} failed: {exc}")
    return location


# --------------------------------------------------------------------------- other repositories


async def locate_sra(accession: str, ncbi: _Ncbi) -> dict:
    location = _empty(f"https://www.ncbi.nlm.nih.gov/sra/{accession}")
    location["summary"] = await sra_summary(accession, ncbi)
    location["note"] = "Raw reads: fetch with NCBI sra-tools (see summary.how_to_download)"
    return location


async def locate_biostudies(accession: str, http: httpx.AsyncClient, arrayexpress: bool) -> dict:
    landing = (f"https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{accession}" if arrayexpress
               else f"https://www.ebi.ac.uk/biostudies/studies/{accession}")
    location = _empty(landing)
    resp = await http.get(f"https://www.ebi.ac.uk/biostudies/api/v1/studies/{accession}/info")
    resp.raise_for_status()
    info = resp.json()
    location["download"] = {"https": info.get("httpLink"), "ftp": info.get("ftpLink")}
    location["summary"] = {"files_in_record": info.get("files"), "public": info.get("isPublic")}
    if info.get("httpLink"):
        base = info["httpLink"].rstrip("/") + "/Files/"
        listing = await http.get(base)
        if listing.status_code == 200:
            _set_files(location, parse_listing(listing.text, base))
            # The listing only shows the top folder; the record's own count is the real total.
            location["file_count"] = max(location["file_count"], info.get("files") or 0)
    return location


async def locate_pride(accession: str, http: httpx.AsyncClient) -> dict:
    location = _empty(f"https://www.ebi.ac.uk/pride/archive/projects/{accession}")
    resp = await http.get(f"https://www.ebi.ac.uk/pride/ws/archive/v2/projects/{accession}/files",
                          params={"pageSize": 1000})
    resp.raise_for_status()
    files = []
    for f in resp.json():
        ftp = next((loc.get("value") for loc in f.get("publicFileLocations", [])
                    if "FTP" in str(loc.get("name", ""))), None)
        files.append({"name": f.get("fileName"), "size_bytes": f.get("fileSizeBytes"),
                      "size_exact": True, "url": ftp})
    _set_files(location, files)
    # The project folder is the files' common parent: PRIDE keeps some files in subfolders
    # (e.g. generated/), so the first file's folder is not necessarily the project's.
    folders = [f["url"].rsplit("/", 1)[0] for f in files if f["url"]]
    if folders:
        common = folders[0]
        for folder in folders[1:]:
            while not (folder + "/").startswith(common + "/"):
                common = common.rsplit("/", 1)[0]
        location["download"] = {"ftp": common + "/", "https": common.replace("ftp://", "https://") + "/"}
    return location


async def locate_metabolights(accession: str, http: httpx.AsyncClient) -> dict:
    location = _empty(f"https://www.ebi.ac.uk/metabolights/{accession}")
    folder = f"ftp.ebi.ac.uk/pub/databases/metabolights/studies/public/{accession}/"
    location["download"] = {"ftp": f"ftp://{folder}", "https": f"https://{folder}"}
    resp = await http.get(f"https://www.ebi.ac.uk/metabolights/ws/studies/{accession}/files",
                          params={"include_raw_data": "false"})
    resp.raise_for_status()
    _set_files(location, [{"name": f.get("file"), "size_bytes": None, "size_exact": False,
                           "url": f"https://{folder}{f.get('file')}", "type": f.get("type")}
                          for f in resp.json().get("study", []) if not f.get("directory")])
    return location


async def locate_massive(accession: str, http: httpx.AsyncClient) -> dict:
    location = _empty(f"https://massive.ucsd.edu/ProteoSAFe/QueryMSV?id={accession}")
    resp = await http.get(f"https://massive.ucsd.edu/ProteoSAFe/proxi/v0.1/datasets/{accession}")
    resp.raise_for_status()
    body = resp.json()
    links = body.get("datasetLink") or []
    ftp = next((link.get("value") for link in links if "FTP" in str(link.get("name", ""))), None)
    location["download"] = {"ftp": ftp}
    location["summary"] = {"title": body.get("title")}
    return location


async def locate_zenodo(accession: str, http: httpx.AsyncClient) -> dict:
    record_id = accession.rsplit(".", 1)[-1]
    location = _empty(f"https://zenodo.org/records/{record_id}")
    resp = await http.get(f"https://zenodo.org/api/records/{record_id}")
    resp.raise_for_status()
    body = resp.json()
    location["summary"] = {"title": (body.get("metadata") or {}).get("title")}
    _set_files(location, [{"name": f.get("key"), "size_bytes": f.get("size"), "size_exact": True,
                           "url": (f.get("links") or {}).get("self")} for f in body.get("files", [])])
    location["download"] = {"https": location["landing_page"] + "/files"}
    return location


async def locate_doi(accession: str, repository: str, http: httpx.AsyncClient) -> dict:
    """DOI repositories: landing page, publisher and title from DataCite; figshare also lists files."""
    resp = await http.get(f"https://api.datacite.org/dois/{accession}")
    resp.raise_for_status()
    attrs = resp.json()["data"]["attributes"]
    location = _empty(attrs.get("url") or f"https://doi.org/{accession}")
    location["summary"] = {"title": ((attrs.get("titles") or [{}])[0]).get("title"),
                           "publisher": attrs.get("publisher")}
    if repository == "figshare":
        m = re.search(r"figshare\.(\d+)", accession)
        if m:
            files = await http.get(f"https://api.figshare.com/v2/articles/{m.group(1)}/files")
            if files.status_code == 200:
                _set_files(location, [{"name": f.get("name"), "size_bytes": f.get("size"),
                                       "size_exact": True, "url": f.get("download_url")}
                                      for f in files.json()])
    else:
        location["note"] = f"{repository} lists its files on the landing page; DataCite does not carry them"
    return location


async def locate_immport(accession: str, title_lookup: Optional[TitleLookup]) -> dict:
    location = _empty(f"https://www.immport.org/shared/study/{accession}", LOGIN)
    location["download"] = {"https": f"https://www.immport.org/shared/study/{accession}"}
    location["note"] = ("Files are downloaded from the study page after signing in with a free "
                        "ImmPort account (browser download or the ImmPort download tool)")
    if title_lookup is not None:
        location["summary"] = {"title": await title_lookup(accession)}
    return location


_CONTROLLED = {
    "dbGaP": (lambda a: f"https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id={a}",
              "Controlled access: apply through dbGaP Authorized Access (dbgap.ncbi.nlm.nih.gov)"),
    "EGA": (lambda a: f"https://ega-archive.org/{'studies' if a.startswith('EGAS') else 'datasets'}/{a}",
            "Controlled access: request it from the dataset's Data Access Committee via EGA"),
    "JGA": (lambda a: f"https://ddbj.nig.ac.jp/resource/{'jga-study' if a.startswith('JGAS') else 'jga-dataset'}/{a}",
            "Controlled access: apply through the NBDC Human Database (humandbs.dbcls.jp)"),
}


# --------------------------------------------------------------------------- entry point


async def locate(
    accession: str,
    repository: str,
    http: httpx.AsyncClient,
    ncbi: _Ncbi,
    *,
    status: Optional[str] = None,
    title_lookup: Optional[TitleLookup] = None,
    cache: Optional[dict] = None,
) -> Optional[dict]:
    """The location of one dataset, or None for a repository this module does not cover.

    Never raises for a network or format failure: the returned location carries `error`.
    """
    if repository not in LOCATABLE:
        return None
    key = (repository, accession)
    if cache is not None and key in cache:
        return cache[key]

    try:
        if repository == "GEO":
            location = await locate_geo(accession, ncbi, status)
        elif repository == "SRA":
            location = await locate_sra(accession, ncbi)
        elif repository in ("ArrayExpress", "BioStudies"):
            location = await locate_biostudies(accession, http, arrayexpress=repository == "ArrayExpress")
        elif repository == "PRIDE":
            location = await locate_pride(accession, http)
        elif repository == "MetaboLights":
            location = await locate_metabolights(accession, http)
        elif repository == "MassIVE":
            location = await locate_massive(accession, http)
        elif repository == "Zenodo":
            location = await locate_zenodo(accession, http)
        elif repository in ("figshare", "Dryad", "Mendeley Data", "Dataverse", "immuneACCESS"):
            location = await locate_doi(accession, repository, http)
        elif repository == "ImmPort":
            location = await locate_immport(accession, title_lookup)
        else:
            landing, note = _CONTROLLED[repository]
            location = _empty(landing(accession), CONTROLLED)
            location["note"] = note
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.warning("locating %s %s failed: %s", repository, accession, exc)
        location = _empty(None)
        location["error"] = f"{repository} lookup failed: {exc}"

    if cache is not None:
        cache[key] = location
    return location
