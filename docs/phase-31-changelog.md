# Phase 31 Changelog

Added the GitHub CI evidence operator flow:

- operator flow readmodel, dry-run report and exact-commit promotion;
- current commit resolver with dirty-state classification;
- metadata-only run and artifact selection flow;
- durable import orchestration over existing phase-29 worker/import services;
- independent review and promotion-gated readiness;
- dashboard/API/CLI/MCP metadata surfaces;
- deterministic fake-GitHub, managed-secret and managed-signer tests.

No workflow dispatch, push, repository mutation, GitHub write operation or remote-CI success claim was added.
