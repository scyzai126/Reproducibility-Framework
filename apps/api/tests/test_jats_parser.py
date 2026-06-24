from app.agent.jats_parser import parse_jats_xml


def test_parse_jats_xml_drops_back_matter_without_merging_unknown_sections():
    xml = """
    <article>
      <body>
        <sec><title>Analysis of peripheral blood leukocytes</title><p>Mass cytometry result.</p></sec>
        <sec><title>Acknowledgements</title><p>Acknowledgement text.</p></sec>
        <sec><title>Data availability</title><p>Data location text.</p></sec>
        <sec><title>Competing interests</title><p>Competing interest text.</p></sec>
      </body>
      <back>
        <ref-list><ref>Reference text.</ref></ref-list>
      </back>
    </article>
    """

    parsed = parse_jats_xml(xml)

    assert "## Analysis of peripheral blood leukocytes\nMass cytometry result." in parsed
    assert "Acknowledgement text" not in parsed
    assert "Data location text" not in parsed
    assert "Competing interest text" not in parsed
    assert "Reference text" not in parsed


def test_parse_jats_xml_skips_abstract_sections_during_body_walk():
    xml = """
    <article>
      <front>
        <article-meta>
          <abstract>
            <sec><title>Background</title><p>Abstract background.</p></sec>
            <sec><title>Methods</title><p>Abstract methods.</p></sec>
            <sec><title>Results</title><p>Abstract results.</p></sec>
          </abstract>
        </article-meta>
      </front>
      <body>
        <sec><title>Results</title><p>Body result.</p></sec>
      </body>
    </article>
    """

    parsed = parse_jats_xml(xml)

    assert parsed.count("Abstract background.") == 1
    assert parsed.count("Abstract methods.") == 1
    assert parsed.count("Abstract results.") == 1
    assert "## Methods\nAbstract methods." not in parsed
    assert "## Results\nAbstract results." not in parsed
    assert "## Results\nBody result." in parsed


def test_parse_jats_xml_skips_figures_and_tables_in_excluded_sections():
    xml = """
    <article>
      <body>
        <sec><title>Results</title><p>Body result.</p></sec>
        <sec><title>Discussion</title>
          <fig><label>Figure X</label><caption><p>Discussion figure.</p></caption></fig>
          <table-wrap>
            <label>Table X</label>
            <caption><p>Discussion table.</p></caption>
            <table><tr><td>Discussion table body.</td></tr></table>
          </table-wrap>
        </sec>
        <sec><title>Acknowledgements</title>
          <fig><label>Figure Ack</label><caption><p>Acknowledgement figure.</p></caption></fig>
          <table-wrap>
            <label>Table Ack</label>
            <caption><p>Acknowledgement table.</p></caption>
            <table><tr><td>Acknowledgement table body.</td></tr></table>
          </table-wrap>
        </sec>
        <sec><title>Data availability</title>
          <fig><label>Figure Data</label><caption><p>Data availability figure.</p></caption></fig>
          <table-wrap>
            <label>Table Data</label>
            <caption><p>Data availability table.</p></caption>
            <table><tr><td>Data availability table body.</td></tr></table>
          </table-wrap>
        </sec>
        <supplementary-material>
          <label>Supplementary Fig. 1</label>
          <caption><p>Supplementary caption.</p></caption>
        </supplementary-material>
        <sec><title>Supplementary results</title>
          <p>Supplementary section paragraph.</p>
          <fig><label>Figure S2</label><caption><p>Supplementary section figure.</p></caption></fig>
          <table-wrap>
            <label>Table S1</label>
            <caption><p>Supplementary section table.</p></caption>
            <table><tr><td>Supplementary table body.</td></tr></table>
          </table-wrap>
        </sec>
      </body>
    </article>
    """

    parsed = parse_jats_xml(xml)

    assert "Body result." in parsed
    assert "Discussion figure" not in parsed
    assert "Discussion table" not in parsed
    assert "Discussion table body" not in parsed
    assert "Acknowledgement figure" not in parsed
    assert "Acknowledgement table" not in parsed
    assert "Acknowledgement table body" not in parsed
    assert "Data availability figure" not in parsed
    assert "Data availability table" not in parsed
    assert "Data availability table body" not in parsed
    assert "Supplementary caption" not in parsed
    assert "Supplementary section paragraph" not in parsed
    assert "Supplementary section figure" not in parsed
    assert "Supplementary section table" not in parsed
    assert "Supplementary table body" not in parsed


def test_parse_jats_xml_drops_common_non_claim_section_aliases():
    dropped_titles = [
        "Discussion",
        "Conclusions",
        "Conclusion",
        "Discussion and conclusions",
        "Summary and conclusions",
        "Concluding remarks",
        "References",
        "Reference list",
        "Bibliography",
        "Literature cited",
        "Works cited",
        "Notes and references",
        "Acknowledgements",
        "Acknowledgments",
        "Acknowledgement",
        "Acknowledgment",
        "Author contributions",
        "Authors' contributions",
        "Author contribution statement",
        "Contributions",
        "Competing interests",
        "Competing financial interests",
        "Conflict of interest",
        "Conflicts of interest",
        "Declaration of interests",
        "Disclosure statement",
        "Data availability",
        "Availability of data",
        "Data and materials availability",
        "Data sharing statement",
        "Availability of data and materials",
        "Code availability",
        "Software availability",
        "Availability of code",
        "Ethics declarations",
        "Ethics approval",
        "Ethical approval",
        "Consent to participate",
        "Consent for publication",
        "Funding",
        "Funding information",
        "Financial support",
        "Grant support",
        "Publisher's note",
        "Publisher note",
        "Correspondence",
        "Corresponding author",
        "Correspondence and requests for materials",
        "Supplementary material",
        "Supplementary materials",
        "Supplementary information",
        "Supporting information",
        "Supplemental information",
        "Additional file 1",
        "Supplementary data",
    ]
    dropped_sections = "\n".join(
        f"<sec><title>{title}</title><p>drop alias marker {idx}</p></sec>"
        for idx, title in enumerate(dropped_titles)
    )
    xml = f"""
    <article>
      <body>
        <sec><title>Results and discussion</title><p>Combined result section.</p></sec>
        {dropped_sections}
      </body>
    </article>
    """

    parsed = parse_jats_xml(xml)

    assert "Combined result section." in parsed
    for idx, title in enumerate(dropped_titles):
        assert f"drop alias marker {idx}" not in parsed, title
