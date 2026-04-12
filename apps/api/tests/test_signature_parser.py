import json

import pytest

from app.agent.signature_parser import format_descriptions_for_llm, parse_signature

SAMPLE_SIGNATURE = {
    "publication_text": "Test publication",
    "repository": [
        {"name": "ImmPort", "repository_id": "SDY1669", "id": 0}
    ],
    "participant_group": [
        {
            "name": "Healthy controls",
            "id": 0,
            "paper_description": [
                "n = 18 healthy subjects",
                "from the Atlanta cohort",
            ],
        },
        {
            "name": "COVID-19 patients",
            "id": 1,
            "paper_description": [
                "36 COVID-19 infected individuals",
                "using Olink multiplex inflammation panel",
            ],
        },
    ],
}


def test_parse_signature_extracts_groups():
    groups, study_accession = parse_signature(json.dumps(SAMPLE_SIGNATURE))
    assert len(groups) == 2
    assert groups[0]["group_id"] == 0
    assert groups[0]["descriptions"] == [
        "n = 18 healthy subjects",
        "from the Atlanta cohort",
    ]
    assert groups[1]["group_id"] == 1
    assert study_accession == "SDY1669"


def test_parse_signature_missing_participant_group():
    data = {"publication_text": "No groups here"}
    groups, study_accession = parse_signature(json.dumps(data))
    assert groups == []
    assert study_accession is None


def test_parse_signature_empty_descriptions():
    data = {
        "participant_group": [
            {"name": "Empty group", "id": 0, "paper_description": []},
            {"name": "No desc field", "id": 1},
        ]
    }
    groups, study_accession = parse_signature(json.dumps(data))
    assert groups == []
    assert study_accession is None


def test_parse_signature_skips_groups_without_descriptions():
    data = {
        "participant_group": [
            {"name": "Has descriptions", "id": 0, "paper_description": ["desc"]},
            {"name": "No descriptions", "id": 1, "paper_description": []},
        ]
    }
    groups, study_accession = parse_signature(json.dumps(data))
    assert len(groups) == 1
    assert groups[0]["group_id"] == 0


def test_parse_signature_extracts_study_accession():
    data = {
        "repository": [{"name": "ImmPort", "repository_id": "SDY1234"}],
        "participant_group": [
            {"name": "Group", "id": 0, "paper_description": ["desc"]},
        ],
    }
    groups, study_accession = parse_signature(json.dumps(data))
    assert study_accession == "SDY1234"


def test_parse_signature_no_repository():
    data = {
        "participant_group": [
            {"name": "Group", "id": 0, "paper_description": ["desc"]},
        ],
    }
    groups, study_accession = parse_signature(json.dumps(data))
    assert study_accession is None


def test_format_descriptions_for_llm():
    groups = [
        {
            "group_id": 0,
            "descriptions": ["18 healthy subjects", "Atlanta cohort"],
        },
        {
            "group_id": 1,
            "descriptions": ["36 patients"],
        },
    ]
    result = format_descriptions_for_llm(groups)

    assert "Participant Group 0:" in result
    assert "  - 18 healthy subjects" in result
    assert "  - Atlanta cohort" in result
    assert "Participant Group 1:" in result
    assert "  - 36 patients" in result


def test_format_descriptions_for_llm_empty():
    assert format_descriptions_for_llm([]) == ""
