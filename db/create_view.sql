-- =============================================================================
-- subject_data_view
--
-- Flat view across all ImmPort tables needed for subject filtering.
-- Grain: one row per (subject × biosample × expsample × immune_exposure × arm).
-- All queries against this view should use SELECT DISTINCT subject_accession.
--
-- Tables joined:
--   subject          — demographics (gender, ethnicity, race)
--   biosample        — sample type, time collected
--   planned_visit    — visit name / order (LEFT JOIN)
--   expsample_2_biosample + expsample — links biosample → experiment
--   experiment       — assay method / measurement technique
--   immune_exposure  — condition, exposure process (LEFT JOIN)
--   arm_2_subject + arm_or_cohort — cohort/arm membership (LEFT JOIN)
-- =============================================================================

-- =============================================================================
-- Indexes for common filter columns
-- =============================================================================

ALTER TABLE immune_exposure ADD INDEX idx_immune_disease_preferred (disease_preferred);
ALTER TABLE biosample        ADD INDEX idx_biosample_type (type);

-- =============================================================================
SELECT
  -- ── Study ─────────────────────────────────────────────────────────────
  b.study_accession,

  -- ── Subject demographics ──────────────────────────────────────────────
  s.subject_accession,
  s.gender,
  s.ethnicity,
  s.race,
  s.species,

  -- ── Arm / Cohort ──────────────────────────────────────────────────────
  a.arm_accession,
  a.name                                AS arm_name,
  a.description                         AS arm_description,
  a.type_reported                       AS arm_type,

  -- ── Biosample ─────────────────────────────────────────────────────────
  b.biosample_accession,
  b.type                                AS tissue_type,
  b.subtype                             AS tissue_subtype,
  b.study_time_collected,
  b.study_time_collected_unit,
  b.study_time_t0_event,

  -- ── Planned visit ─────────────────────────────────────────────────────
  pv.planned_visit_accession,
  pv.name                               AS planned_visit_name,
  pv.order_number                       AS visit_order,
  pv.min_start_day                      AS visit_min_day,
  pv.max_start_day                      AS visit_max_day,

  -- ── Experiment / Assay ────────────────────────────────────────────────
  e.experiment_accession,
  e.name                                AS experiment_name,
  e.measurement_technique               AS assay_method,
  e.description                         AS experiment_description,

  -- ── Expsample ─────────────────────────────────────────────────────────
  es.expsample_accession,

  -- ── Immune exposure ───────────────────────────────────────────────────
  ie.exposure_accession,
  ie.exposure_process_preferred         AS exposure_process,
  ie.exposure_process_reported,
  ie.disease_preferred                  AS `condition`,
  ie.disease_reported,
  ie.disease_stage_preferred,
  ie.disease_ontology_id,
  ie.exposure_material_preferred        AS exposure_material,
  ie.exposure_material_reported

FROM biosample b

  -- Subject (required)
  JOIN subject s
    ON s.subject_accession = b.subject_accession

  -- Expsample chain (required — links biosample to experiment)
  JOIN expsample_2_biosample e2b
    ON e2b.biosample_accession = b.biosample_accession
  JOIN expsample es
    ON es.expsample_accession = e2b.expsample_accession
  JOIN experiment e
    ON e.experiment_accession = es.experiment_accession

  -- Planned visit (optional — not all biosamples have a visit)
  LEFT JOIN planned_visit pv
    ON  pv.planned_visit_accession = b.planned_visit_accession
    AND pv.study_accession         = b.study_accession

  -- Arm membership scoped to the same study (optional)
  LEFT JOIN arm_2_subject a2s
    ON a2s.subject_accession = b.subject_accession
  LEFT JOIN arm_or_cohort a
    ON  a.arm_accession   = a2s.arm_accession
    AND a.study_accession = b.study_accession

  -- Immune exposure scoped to this study via a2s.arm_accession (no subquery)
  LEFT JOIN immune_exposure ie
    ON  ie.subject_accession = b.subject_accession
    AND ie.arm_accession     = a2s.arm_accession;
