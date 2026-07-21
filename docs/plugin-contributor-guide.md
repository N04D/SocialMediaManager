# Plugin Contributor Guide

Workflow: fork or checkout, create a Python 3.12 environment, scaffold a plugin, fill the manifest, create a deterministic fixture, implement runtime, register requirements and metrics, run contract tests, run doctor, generate compatibility report, run security scans, run opt-in integration tests, prepare pilot runbook, update changelog, and open a pull request.

Integration levels: deterministic fixture, local real service, external read-only service, and explicit pilot mutation. Pilot mutation never runs in default CI.
