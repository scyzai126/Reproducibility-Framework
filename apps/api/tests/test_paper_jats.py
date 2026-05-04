from app.agent.paper_context import render_paper_context_for_llm
from app.agent.paper_jats import extract_paper_blocks, parse_jats_xml_to_json
from bs4 import BeautifulSoup


_FULL_JATS = """\
<article>
  <front>
    <article-meta>
      <abstract>
        <p>Abstract summary.</p>
      </abstract>
    </article-meta>
  </front>
  <body>
    <sec>
      <title>Results</title>
      <p>Results paragraph.</p>
      <sec>
        <title>Innate response</title>
        <p>Nested results paragraph.</p>
      </sec>
    </sec>
    <sec>
      <title>Methods</title>
      <p>Methods paragraph.</p>
    </sec>
    <sec>
      <title>Discussion</title>
      <p>Discussion paragraph.</p>
    </sec>
    <fig>
      <label>Figure 1</label>
      <caption>
        <title>Figure title</title>
        <p>Figure caption text.</p>
      </caption>
    </fig>
    <table-wrap>
      <label>Table 1</label>
      <caption>
        <title>Table title</title>
        <p>Table caption text.</p>
      </caption>
    </table-wrap>
  </body>
</article>
"""

# PMC7665312-style: sections identified only via sec-type, no generic "Methods" title
_SECTYPE_JATS = """\
<article>
  <front>
    <article-meta>
      <abstract><p>COVID study abstract.</p></abstract>
    </article-meta>
  </front>
  <body>
    <sec sec-type="subjects">
      <title>Analysis of peripheral blood leukocytes from COVID-19 patients by mass cytometry</title>
      <p>Subject selection paragraph.</p>
    </sec>
    <sec sec-type="results">
      <title>COVID-19 results in functional impairment of blood myeloid cells and pDCs</title>
      <p>Key results paragraph.</p>
    </sec>
    <sec sec-type="discussion">
      <title>Discussion</title>
      <p>Discussion paragraph.</p>
    </sec>
  </body>
</article>
"""

# Paper with only one section — old code would have called this "fallback"
_SPARSE_JATS = """\
<article>
  <body>
    <sec>
      <title>Results</title>
      <p>Only results are present.</p>
    </sec>
  </body>
</article>
"""


# ── parse_jats_xml_to_json ────────────────────────────────────────────────────

def test_parse_returns_blocks_field():
    paper = parse_jats_xml_to_json(_FULL_JATS)
    assert paper["parse_mode"] == "blocks"
    assert isinstance(paper["blocks"], list)
    assert len(paper["blocks"]) > 0


def test_blocks_have_required_fields():
    paper = parse_jats_xml_to_json(_FULL_JATS)
    for block in paper["blocks"]:
        for field in ("block_id", "tag_type", "title", "location", "text",
                      "order", "xref_targets", "char_count",
                      "semantic_labels", "primary_label",
                      "primary_label_confidence", "claim_priority"):
            assert field in block, f"missing field {field!r} in block {block['block_id']}"


def test_blocks_document_order_is_sequential():
    paper = parse_jats_xml_to_json(_FULL_JATS)
    orders = [b["order"] for b in paper["blocks"]]
    assert orders == list(range(len(orders)))


def test_abstract_block_labeled_correctly():
    paper = parse_jats_xml_to_json(_FULL_JATS)
    abstract_blocks = [b for b in paper["blocks"] if b["tag_type"] == "abstract"]
    assert len(abstract_blocks) == 1
    b = abstract_blocks[0]
    assert b["primary_label"] == "abstract"
    assert b["claim_priority"] == "high"
    assert "Abstract summary." in b["text"]


def test_results_section_labeled_correctly():
    paper = parse_jats_xml_to_json(_FULL_JATS)
    results_blocks = [b for b in paper["blocks"] if b["primary_label"] == "results_like"]
    assert len(results_blocks) >= 1
    assert all(b["claim_priority"] == "highest" for b in results_blocks)


def test_figure_legend_labeled_correctly():
    paper = parse_jats_xml_to_json(_FULL_JATS)
    fig_blocks = [b for b in paper["blocks"] if b["tag_type"] == "figure_legend"]
    assert len(fig_blocks) == 1
    b = fig_blocks[0]
    assert b["primary_label"] == "figure_legend"
    assert b["claim_priority"] == "highest"
    assert b["title"] == "Figure 1"


def test_table_caption_labeled_correctly():
    paper = parse_jats_xml_to_json(_FULL_JATS)
    tbl_blocks = [b for b in paper["blocks"] if b["tag_type"] == "table_caption"]
    assert len(tbl_blocks) == 1
    assert tbl_blocks[0]["claim_priority"] == "highest"


def test_exclude_labels_absent_from_blocks():
    xml = """\
    <article>
      <body>
        <sec>
          <title>Results</title>
          <p>Some results.</p>
        </sec>
        <sec>
          <title>Acknowledgments</title>
          <p>We thank everyone.</p>
        </sec>
      </body>
      <back>
        <ref-list>
          <ref>Reference 1.</ref>
        </ref-list>
      </back>
    </article>
    """
    paper = parse_jats_xml_to_json(xml)
    for block in paper["blocks"]:
        assert block["claim_priority"] != "exclude", (
            f"exclude-priority block leaked through: {block['block_id']}"
        )
    # References should still be captured in the references field
    assert len(paper["references"]) == 1


# ── sec-type labeling (PMC7665312 pattern) ────────────────────────────────────

def test_sec_type_results_overrides_missing_title_keyword():
    paper = parse_jats_xml_to_json(_SECTYPE_JATS)
    blocks_by_title = {b["title"]: b for b in paper["blocks"]}

    results_block = blocks_by_title["COVID-19 results in functional impairment of blood myeloid cells and pDCs"]
    assert results_block["primary_label"] == "results_like"
    assert results_block["claim_priority"] == "highest"


def test_sec_type_subjects_falls_back_to_body_section():
    paper = parse_jats_xml_to_json(_SECTYPE_JATS)
    subjects_block = next(
        b for b in paper["blocks"]
        if "mass cytometry" in b["title"]
    )
    # sec-type="subjects" is not a standardised JATS value — we don't infer methods from it
    assert subjects_block["primary_label"] == "body_section"
    assert subjects_block["claim_priority"] == "medium"


# ── sparse paper no longer falls back to raw text ────────────────────────────

def test_sparse_paper_still_returns_blocks():
    paper = parse_jats_xml_to_json(_SPARSE_JATS)
    assert paper["parse_mode"] == "blocks"
    assert len(paper["blocks"]) == 1
    assert paper["blocks"][0]["primary_label"] == "results_like"
    assert paper["raw_text"] == ""


def test_completely_empty_paper_falls_back_to_raw_text():
    xml = "<article><body><p>Some unstructured text.</p></body></article>"
    paper = parse_jats_xml_to_json(xml)
    # No sec/fig/table/abstract → blocks may be empty → raw_text fallback
    if not paper["blocks"]:
        assert paper["parse_mode"] == "fallback"
        assert "unstructured text" in paper["raw_text"]


# ── render_paper_context_for_llm ─────────────────────────────────────────────

def test_render_includes_all_sections():
    paper = parse_jats_xml_to_json(_FULL_JATS)
    rendered = render_paper_context_for_llm(paper)

    assert "Abstract" in rendered
    assert "Results" in rendered
    assert "Methods" in rendered
    assert "Discussion" in rendered
    assert "Figure 1" in rendered
    assert "Table 1" in rendered


def test_render_embeds_label_metadata():
    paper = parse_jats_xml_to_json(_FULL_JATS)
    rendered = render_paper_context_for_llm(paper)
    # Every block header should carry its label tag
    assert "results_like" in rendered
    assert "figure_legend" in rendered


def test_render_respects_char_limit():
    paper = parse_jats_xml_to_json(_FULL_JATS)
    rendered = render_paper_context_for_llm(paper, char_limit=50)
    assert len(rendered) <= 50
