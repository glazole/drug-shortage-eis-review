# Saved studies and profiles

The `studies` directory separates a research area from saved variants of its protocol:

```text
studies/
  <study_id>/
    profiles/
      <profile_id>/
        protocol.yaml
        research_questions.yaml
        concepts.yaml
        eligibility_criteria.yaml
        queries/database.yaml
        seeds.csv
```

- `study_id` identifies the research area, for example `drug_shortage_eis`.
- `profile_id` identifies a reproducible variant, for example `baseline`, `pilot_v2`, or
  `slr_broad_search`.
- Profiles are separate directories. Creating a new variant never overwrites the earlier one.

To create another variant of the current study:

```bash
cp -R \
  studies/drug_shortage_eis/profiles/baseline \
  studies/drug_shortage_eis/profiles/pilot_v2
```

Then set `profile_id: pilot_v2` in its `protocol.yaml` and edit only that profile. To create a new
research area, create another `<study_id>/profiles/<profile_id>` tree with the same file contract.

Docker Compose mounts `./studies` read-only into the API container. New or edited profile files are
therefore visible to the API without rebuilding the image. The files remain normal Git-versioned
research artifacts on the host.

The profile YAML is the reproducible scientific record. Environment variables are temporary
runtime overrides and the API reports their names in `env_overrides`.
