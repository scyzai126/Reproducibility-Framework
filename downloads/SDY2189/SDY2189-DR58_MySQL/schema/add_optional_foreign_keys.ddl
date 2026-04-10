system echo 'Adding Foreign Keys to fcs_analyzed_result_marker'
ALTER TABLE fcs_analyzed_result_marker ADD CONSTRAINT fk_fcs_analyzed_result_marker_1
    FOREIGN KEY (result_id)
    REFERENCES fcs_analyzed_result (result_id);
ALTER TABLE fcs_analyzed_result_marker ADD CONSTRAINT fk_fcs_analyzed_result_marker_2
    FOREIGN KEY (preferred_analyte_accession)
    REFERENCES lk_analyte (analyte_accession);

system echo 'Adding Foreign Keys to fcs_header'
ALTER TABLE fcs_header ADD CONSTRAINT fk_fcs_header_1
    FOREIGN KEY (expsample_accession)
    REFERENCES expsample (expsample_accession);
ALTER TABLE fcs_header ADD CONSTRAINT fk_fcs_header_2
    FOREIGN KEY (file_info_id)
    REFERENCES file_info (file_info_id);

system echo 'Adding Foreign Keys to fcs_header_marker'
ALTER TABLE fcs_header_marker ADD CONSTRAINT fk_fcs_header_marker_1
    FOREIGN KEY (fcs_header_id)
    REFERENCES fcs_header (fcs_header_id);

system echo 'Adding Foreign Keys to mass_spectrometry_result'
ALTER TABLE mass_spectrometry_result ADD CONSTRAINT fk_mass_result_1
    FOREIGN KEY (expsample_accession)
    REFERENCES expsample (expsample_accession);
ALTER TABLE mass_spectrometry_result ADD CONSTRAINT fk_mass_result_2
    FOREIGN KEY (experiment_accession)
    REFERENCES experiment (experiment_accession);
ALTER TABLE mass_spectrometry_result ADD CONSTRAINT fk_mass_result_3
    FOREIGN KEY (study_accession)
    REFERENCES study (study_accession);
ALTER TABLE mass_spectrometry_result ADD CONSTRAINT fk_mass_result_4
    FOREIGN KEY (arm_accession)
    REFERENCES arm_or_cohort (arm_accession);
ALTER TABLE mass_spectrometry_result ADD CONSTRAINT fk_mass_result_5
    FOREIGN KEY (biosample_accession)
    REFERENCES biosample (biosample_accession);
ALTER TABLE mass_spectrometry_result ADD CONSTRAINT fk_mass_result_6
    FOREIGN KEY (subject_accession)
    REFERENCES subject (subject_accession);
ALTER TABLE mass_spectrometry_result ADD CONSTRAINT fk_mass_result_7
    FOREIGN KEY (workspace_id)
    REFERENCES workspace(workspace_id);
ALTER TABLE mass_spectrometry_result ADD CONSTRAINT fk_mass_result_8
    FOREIGN KEY (database_id_preferred)
    REFERENCES lk_hmdb(hmdb_id);
ALTER TABLE mass_spectrometry_result ADD CONSTRAINT fk_mass_result_9
    FOREIGN KEY (protein_name_preferred)
    REFERENCES lk_protein_name(name);
ALTER TABLE mass_spectrometry_result ADD CONSTRAINT fk_mass_result_10
    FOREIGN KEY (retention_time_unit)
    REFERENCES lk_time_unit(name);
ALTER TABLE mass_spectrometry_result ADD CONSTRAINT fk_mass_result_11
    FOREIGN KEY (mass_spectrometry_type)
    REFERENCES lk_mass_spectrometry_type(name);
ALTER TABLE mass_spectrometry_result ADD CONSTRAINT fk_mass_result_12
    FOREIGN KEY (repository_name)
    REFERENCES lk_public_repository(name);