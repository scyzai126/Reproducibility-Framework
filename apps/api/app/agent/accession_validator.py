"""Check each accession against its own repository: does it exist, and which paper owns it.

The second half is the point. GEO, SRA, BioProject and ImmPort record the PubMed ID of the paper
that deposited a dataset, and that is a fact on record rather than a reading of the text. On the
35-paper JATS corpus, GEO's link was present for all 49 series the papers name and settled "this
paper's data or someone else's" for every one -- including SDY1119's GSE29619, which the paper
calls data "reported in this paper" but which GEO files under the same group's earlier paper.

What each repository can tell us (probed live, 2026-09):

| repository                              | exists?                             | owner PMIDs                 |
|-----------------------------------------|-------------------------------------|-----------------------------|
| GEO                                     | E-utilities esearch/esummary        | esummary `pubmedids`        |
| SRA, BioProject, BioSample, GenBank     | E-utilities esearch                 | elink -> pubmed             |
| dbGaP                                   | E-utilities esearch                 | none                        |
| ImmPort                                 | local `study` table                 | local `study_pubmed` table  |
| ArrayExpress, BioStudies                | BioStudies API, 404 when absent     | publication PMIDs, if any   |
| PRIDE                                   | PRIDE API, 404 when absent          | `references[].pubmedId`     |
| MetaboLights                            | API, 400 "no study" when absent     | `pubMedID`, if any          |
| Metabolomics Workbench                  | REST, empty list when absent        | none                        |
| PDB                                     | RCSB data API, 404 when absent      | primary citation PubMed ID  |
| EMDB                                    | EMDB API, 404 when absent           | citation PubMed reference   |
| MassIVE, Single Cell Portal, JGA,       | REST, 404 when absent               | none                        |
|   Synapse, OSF, GitHub, ClinicalTrials  |                                     |                             |
| EGA                                     | metadata API: empty body absent     | none                        |
| Zenodo                                  | record API                          | none                        |
| figshare, immuneACCESS, Dryad,          | DOI handle API                      | none                        |
|   Mendeley Data, Dataverse              |                                     |                             |
| FlowRepository                          | page (often unreachable)            | none                        |
| GSA, CNGB, jPOST, ISRCTN, GISAID,       | no usable lookup: UNCHECKED with    | none                        |
|   EudraCT, ChiCTR, and the URL-based    | NO_PUBLIC_LOOKUP, never dropped     |                             |
|   sites (CELLxGENE, HCA, Cytobank, ...) |                                     |                             |

ImmPort cannot be checked on the web: immport.org answers 200 for a study that does not exist and
its API needs a login. The local ImmPort database is authoritative instead, and is injected as
`immport_lookup` so this module never imports app.database (which connects at import time).

Nothing here guesses. Any failure -- network, timeout, a 5xx, a rate limit, a database that is
down -- yields UNCHECKED with the reason, never NOT_FOUND: only a repository saying "no such
record" may drop an accession.
"""

import asyncio
import logging
import re
import time
from typing import Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

VERIFIED = "verified"
PRIVATE = "private"
NOT_FOUND = "not_found"
UNCHECKED = "unchecked"

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

#: NCBI allows 3 requests/second without an API key; a live run at 0.35 s still drew 429s,
#: so this leaves headroom. A 429 is retried NCBI_RETRIES times with exponential backoff.
NCBI_MIN_INTERVAL = 0.5
NCBI_RETRIES = 3

#: `(exists, owner_pmids)` for an SDY, or None when the database could not be asked.
ImmportLookup = Callable[[str], Awaitable[Optional[tuple[bool, list[str]]]]]

_GEO_ETYPE = {"GSE": "gse", "GSM": "gsm", "GDS": "gds"}

#: Repositories whose IDs are DOIs, checked through the DOI handle API.
_DOI_REPOSITORIES = {"figshare", "immuneACCESS", "Dryad", "Mendeley Data", "Dataverse"}

#: Detail text of an UNCHECKED result for a repository with no usable lookup. Callers match
#: on it to report these as expected rather than as failures.
NO_PUBLIC_LOOKUP = "no public lookup"


def result(status: str, owner_pmids: Optional[list[str]] = None, detail: str = "") -> dict:
    return {"status": status, "owner_pmids": sorted(set(owner_pmids or [])), "detail": detail}


class _Ncbi:
    """E-utilities GETs, spaced to stay under NCBI's rate limit."""

    def __init__(self, http: httpx.AsyncClient, min_interval: float = NCBI_MIN_INTERVAL):
        self.http = http
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def fetch(self, url: str, params: dict) -> httpx.Response:
        """One throttled GET. A 429 is retried with backoff; NCBI counts every host it runs."""
        for attempt in range(NCBI_RETRIES + 1):
            async with self._lock:
                wait = self._last + self.min_interval - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last = time.monotonic()
            resp = await self.http.get(url, params=params)
            if resp.status_code != 429 or attempt == NCBI_RETRIES:
                return resp
            await asyncio.sleep(self.min_interval * 2 ** (attempt + 2))
        return resp

    async def get(self, endpoint: str, **params) -> dict:
        resp = await self.fetch(EUTILS + endpoint, {**params, "retmode": "json"})
        resp.raise_for_status()
        return resp.json()

    async def search(self, db: str, term: str, retmax: int = 500) -> list[str]:
        data = await self.get("esearch.fcgi", db=db, term=term, retmax=retmax)
        return data["esearchresult"]["idlist"]

    async def pubmed_links(self, dbfrom: str, ids: list[str]) -> list[str]:
        if not ids:
            return []
        data = await self.get("elink.fcgi", dbfrom=dbfrom, db="pubmed", id=",".join(ids[:50]))
        pmids = []
        for linkset in data.get("linksets", []):
            for db in linkset.get("linksetdbs", []):
                if db.get("dbto") == "pubmed":
                    pmids.extend(str(x) for x in db.get("links", []))
        return pmids


# --------------------------------------------------------------------------- per repository


async def _geo(accessions: list[str], ncbi: _Ncbi) -> dict[str, dict]:
    """One esearch + esummary per accession type, then a text-page check for anything missing.

    E-utilities does not index private (embargoed) series, so a miss is not yet a NOT_FOUND:
    the GEO accession page is asked directly and tells private, public and absent apart.
    """
    out: dict[str, dict] = {}
    by_type: dict[str, list[str]] = {}
    for acc in accessions:
        by_type.setdefault(acc[:3], []).append(acc)

    for prefix, accs in by_type.items():
        term = "(" + " OR ".join(f"{a}[ACCN]" for a in accs) + f") AND {_GEO_ETYPE[prefix]}[ETYP]"
        uids = await ncbi.search("gds", term)
        if not uids:
            continue
        summary = (await ncbi.get("esummary.fcgi", db="gds", id=",".join(uids)))["result"]
        wanted = set(accs)
        for uid in summary.get("uids", []):
            rec = summary[uid]
            if rec.get("accession") in wanted:
                out[rec["accession"]] = result(VERIFIED, [str(p) for p in rec.get("pubmedids", [])])

    for acc in accessions:
        if acc not in out:
            out[acc] = await _geo_page(acc, ncbi)
    return out


async def _geo_page(acc: str, ncbi: "_Ncbi") -> dict:
    resp = await ncbi.fetch("https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi",
                            {"acc": acc, "targ": "self", "form": "text", "view": "brief"})
    body = resp.text
    if resp.status_code != 200:
        return result(UNCHECKED, detail=f"GEO answered {resp.status_code}")
    if re.search(r"\bprivate\b", body, re.I) and acc in body:
        return result(PRIVATE, detail="GEO reports the record as private")
    if re.match(r"\^(SERIES|SAMPLE|DATASET)\s*=\s*" + re.escape(acc), body.lstrip()):
        return result(VERIFIED, detail="found on the GEO page but not indexed in E-utilities")
    return result(NOT_FOUND, detail="GEO has no record with this accession")


async def _ncbi_by_search(acc: str, db: str, field: str, ncbi: _Ncbi, link: bool) -> dict:
    uids = await ncbi.search(db, f"{acc}[{field}]", retmax=20)
    if not uids:
        return result(NOT_FOUND, detail=f"NCBI {db} has no record with this accession")
    owners = await ncbi.pubmed_links(db, uids) if link else []
    return result(VERIFIED, owners)


async def _immport(acc: str, lookup: Optional[ImmportLookup]) -> dict:
    if lookup is None:
        return result(UNCHECKED, detail="no ImmPort database lookup was supplied")
    answer = await lookup(acc)
    if answer is None:
        return result(UNCHECKED, detail="the ImmPort database could not be reached")
    exists, pmids = answer
    if not exists:
        return result(NOT_FOUND, detail="not in the ImmPort study table")
    return result(VERIFIED, pmids)


def _biostudies_pmids(study: dict) -> list[str]:
    """PubMed IDs of a BioStudies record's Publication subsections, where it records any.

    Many ArrayExpress records list publications by title and authors only, which is why this
    can come back empty for a study that does have a paper.
    """
    pmids = []

    def walk(section):
        if isinstance(section, list):
            for s in section:
                walk(s)
            return
        if not isinstance(section, dict):
            return
        if (section.get("type") or "").lower() == "publication":
            accno = str(section.get("accno") or "")
            if accno.isdigit():
                pmids.append(accno)
            for attr in section.get("attributes", []):
                if re.search(r"pubmed|pmid", str(attr.get("name", "")), re.I):
                    digits = re.sub(r"\D", "", str(attr.get("value", "")))
                    if digits:
                        pmids.append(digits)
        walk(section.get("subsections", []))

    walk(study.get("section", {}))
    return pmids


def _emdb_pmids(entry: dict) -> list[str]:
    """PubMed IDs among an EMDB entry's citation external references."""
    pmids = []

    def walk(node):
        if isinstance(node, dict):
            refs = node.get("external_references")
            for ref in refs if isinstance(refs, list) else [refs] if isinstance(refs, dict) else []:
                if str(ref.get("type_", "")).upper() == "PUBMED" and str(ref.get("valueOf_", "")).isdigit():
                    pmids.append(str(ref["valueOf_"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(entry.get("crossreferences", {}).get("citation_list", {}))
    return pmids


def _by_code(resp: httpx.Response, repo: str) -> Optional[dict]:
    """The shared 404 / error handling; None means "200, look at the body"."""
    if resp.status_code in (404, 410):
        return result(NOT_FOUND, detail=f"{repo} answered {resp.status_code}")
    if resp.status_code != 200:
        return result(UNCHECKED, detail=f"{repo} answered {resp.status_code}")
    return None


async def _one(acc: str, repo: str, ncbi: _Ncbi, immport_lookup: Optional[ImmportLookup]) -> dict:
    http = ncbi.http
    if repo == "SRA":
        return await _ncbi_by_search(acc, "sra", "Accession", ncbi, link=True)
    if repo == "BioProject":
        return await _ncbi_by_search(acc, "bioproject", "Project Accession", ncbi, link=True)
    if repo == "dbGaP":
        return await _ncbi_by_search(acc.split(".")[0], "gap", "Study Accession", ncbi, link=False)
    if repo == "ImmPort":
        return await _immport(acc, immport_lookup)

    if repo == "ArrayExpress":
        resp = await http.get(f"https://www.ebi.ac.uk/biostudies/api/v1/studies/{acc}")
        return _by_code(resp, repo) or result(VERIFIED, _biostudies_pmids(resp.json()))
    if repo == "PRIDE":
        resp = await http.get(f"https://www.ebi.ac.uk/pride/ws/archive/v2/projects/{acc}")
        refs = [] if resp.status_code != 200 else resp.json().get("references") or []
        return _by_code(resp, repo) or result(
            VERIFIED, [str(r["pubmedId"]) for r in refs if isinstance(r, dict) and r.get("pubmedId")])
    if repo == "ClinicalTrials.gov":
        resp = await http.get(f"https://clinicaltrials.gov/api/v2/studies/{acc}",
                              params={"fields": "protocolSection.identificationModule"})
        return _by_code(resp, repo) or result(VERIFIED)
    if repo == "EGA":
        kind = "studies" if acc.startswith("EGAS") else "datasets"
        resp = await http.get(f"https://metadata.ega-archive.org/{kind}/{acc}")
        if (res := _by_code(resp, repo)) is not None:
            return res
        # EGA answers 200 with an empty body for an accession it does not have.
        if not resp.text.strip() or acc not in resp.text:
            return result(NOT_FOUND, detail="EGA returned no record")
        return result(VERIFIED)
    if repo == "Zenodo":
        resp = await http.get(f"https://zenodo.org/api/records/{acc.rsplit('.', 1)[-1]}")
        return _by_code(resp, repo) or result(VERIFIED)
    if repo == "FlowRepository":
        resp = await http.get(f"https://flowrepository.org/id/{acc}")
        if (res := _by_code(resp, repo)) is not None:
            return res
        # A 200 that does not name the ID is not proof of absence; leave it unchecked.
        return result(VERIFIED) if acc in resp.text else result(
            UNCHECKED, detail="FlowRepository page did not name the accession")
    if repo == "GitHub":
        owner_repo = acc.removeprefix("github.com/")
        resp = await http.get(f"https://api.github.com/repos/{owner_repo}")
        return _by_code(resp, repo) or result(VERIFIED)

    # ---- NCBI
    if repo == "BioSample":
        return await _ncbi_by_search(acc, "biosample", "accn", ncbi, link=True)
    if repo == "GenBank":
        # elink nuccore -> pubmed lists the sequence record's references, which include the
        # paper that submitted it.
        return await _ncbi_by_search(acc.split(".")[0], "nuccore", "accn", ncbi, link=True)

    # ---- EBI and friends, each with a 404 (or equivalent) for an absent record
    if repo == "BioStudies":
        resp = await http.get(f"https://www.ebi.ac.uk/biostudies/api/v1/studies/{acc}")
        return _by_code(resp, repo) or result(VERIFIED, _biostudies_pmids(resp.json()))
    if repo == "MetaboLights":
        resp = await http.get(f"https://www.ebi.ac.uk/metabolights/ws/studies/{acc}")
        # MetaboLights answers 400 "There is no study" rather than 404.
        if resp.status_code in (400, 404) and "no study" in resp.text.lower():
            return result(NOT_FOUND, detail="MetaboLights has no such study")
        if (res := _by_code(resp, repo)) is not None:
            return res
        return result(VERIFIED, re.findall(r'"pub[Mm]ed[Ii][Dd]"\s*:\s*"?(\d+)', resp.text))
    if repo == "Metabolomics Workbench":
        resp = await http.get(f"https://www.metabolomicsworkbench.org/rest/study/study_id/{acc}/summary")
        if (res := _by_code(resp, repo)) is not None:
            return res
        # An absent study is a 200 with an empty JSON list.
        body = resp.json()
        return result(VERIFIED) if isinstance(body, dict) and body.get("study_id") == acc else result(
            NOT_FOUND, detail="Metabolomics Workbench has no such study")
    if repo == "PDB":
        resp = await http.get(f"https://data.rcsb.org/rest/v1/core/entry/{acc}")
        if (res := _by_code(resp, repo)) is not None:
            return res
        pmid = (resp.json().get("rcsb_primary_citation") or {}).get("pdbx_database_id_pub_med")
        return result(VERIFIED, [str(pmid)] if pmid else [])
    if repo == "EMDB":
        resp = await http.get(f"https://www.ebi.ac.uk/emdb/api/entry/{acc}")
        if (res := _by_code(resp, repo)) is not None:
            return res
        return result(VERIFIED, _emdb_pmids(resp.json()))
    if repo == "MassIVE":
        resp = await http.get(f"https://massive.ucsd.edu/ProteoSAFe/proxi/v0.1/datasets/{acc}")
        return _by_code(resp, repo) or result(VERIFIED)
    if repo == "Single Cell Portal":
        resp = await http.get(f"https://singlecell.broadinstitute.org/single_cell/api/v1/site/studies/{acc}")
        return _by_code(resp, repo) or result(VERIFIED)
    if repo == "JGA":
        kind = "jga-study" if acc.startswith("JGAS") else "jga-dataset"
        resp = await http.get(f"https://ddbj.nig.ac.jp/resource/{kind}/{acc}.json")
        return _by_code(resp, repo) or result(VERIFIED)
    if repo == "Synapse":
        resp = await http.get(f"https://repo-prod.prod.sagebase.org/repo/v1/entity/{acc}/type")
        return _by_code(resp, repo) or result(VERIFIED)
    if repo == "OSF":
        resp = await http.get(f"https://api.osf.io/v2/guids/{acc.removeprefix('osf.io/')}/")
        return _by_code(resp, repo) or result(VERIFIED)
    if repo in _DOI_REPOSITORIES:
        resp = await http.get(f"https://doi.org/api/handles/{acc}")
        return _by_code(resp, repo) or result(VERIFIED)

    # GSA, CNGB and jPOST serve the same page for any ID (a security check or a JavaScript
    # app); ISRCTN does too; GISAID, EudraCT and ChiCTR have no open lookup; and the URL-based
    # resources (CELLxGENE, HCA, Cytobank, iReceptor, VDJServer, OAS, IEDB, VDJdb) are sites,
    # not records. None of them can tell "exists" from "absent", so none is ever dropped by us.
    return result(UNCHECKED, detail=f"{NO_PUBLIC_LOOKUP} for {repo}")


# --------------------------------------------------------------------------- public API


async def validate_accessions(
    items: list[tuple[str, str]],
    http: httpx.AsyncClient,
    immport_lookup: Optional[ImmportLookup] = None,
    cache: Optional[dict[str, dict]] = None,
    ncbi: Optional[_Ncbi] = None,
) -> dict[str, dict]:
    """`{accession: {status, owner_pmids, detail}}` for every `(accession, repository)` pair.

    `cache` is shared across papers in one run: GSE13486 is named by three papers in the corpus
    and is looked up once. Pass the same `ncbi` across papers too, so the rate limit holds over
    the whole run rather than restarting per paper.
    """
    cache = {} if cache is None else cache
    ncbi = ncbi or _Ncbi(http)
    out: dict[str, dict] = {}
    todo = [(a, r) for a, r in items if a not in cache]

    geo = [a for a, r in todo if r == "GEO"]
    if geo:
        try:
            cache.update(await _geo(geo, ncbi))
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            for acc in geo:
                cache.setdefault(acc, result(UNCHECKED, detail=f"GEO lookup failed: {exc}"))

    for acc, repo in todo:
        if repo == "GEO":
            continue
        try:
            cache[acc] = await _one(acc, repo, ncbi, immport_lookup)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            cache[acc] = result(UNCHECKED, detail=f"{repo} lookup failed: {exc}")

    for acc, _ in items:
        out[acc] = cache[acc]
    return out


async def datasets_linked_to_paper(pmid: str, ncbi: _Ncbi) -> list[tuple[str, str]]:
    """GEO series (or, failing those, BioProjects) the repositories link to this PubMed ID.

    Catches data a paper deposited without naming the accession in its text. Returns
    `(accession, repository)` pairs; an empty list when there are none or NCBI cannot be reached.
    """
    found: list[tuple[str, str]] = []
    try:
        for db, repo in (("gds", "GEO"), ("bioproject", "BioProject")):
            # NCBI creates an umbrella BioProject for every GEO series, so once GEO has answered
            # the BioProjects only repeat it. They are asked for only when GEO links nothing --
            # that is where they add something: sequencing deposited straight to SRA.
            if db == "bioproject" and found:
                break
            data = await ncbi.get("elink.fcgi", dbfrom="pubmed", db=db, id=pmid)
            uids = [str(x) for ls in data.get("linksets", [])
                    for d in ls.get("linksetdbs", []) if d.get("dbto") == db for x in d.get("links", [])]
            if not uids:
                continue
            summary = (await ncbi.get("esummary.fcgi", db=db, id=",".join(uids[:200])))["result"]
            for uid in summary.get("uids", []):
                rec = summary[uid]
                acc = rec.get("accession") if db == "gds" else rec.get("project_acc")
                # GEO also links the samples and platforms of a series; only series are datasets.
                if acc and (db != "gds" or acc.startswith("GSE")):
                    found.append((acc, repo))
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("reverse lookup for PMID %s failed: %s", pmid, exc)
    return found
