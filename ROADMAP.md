# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## Actionable Items

- [ ] **Action DAG + dry-run renderer** — LLM produces proposed actions as JSON; GUI renders diff; user approves atomic apply

- [ ] **Checkpointed scans** — large library scans write progress to SQLite so crash/resume is clean

- [ ] **Hydrus tag-sibling/parent DB layout** — `tag_implications(antecedent, consequent)` + `tag_siblings(bad_tag, good_tag)` tables; query-time expansion

- [ ] **Sidecar-tag coexistence** — write `.xmp` sidecars in TagStudio format alongside originals; read them back on re-open so tags survive outside UniFile
