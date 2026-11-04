"""Tenant setup automation: deploy the Fabric estate and seed the Work IQ content (docs/deployment.md).

``evals deploy fabric`` creates the workspaces, lakehouses, notebooks and semantic models the golden
set targets (PLAN §4.1-§4.3) and validates them; ``evals deploy workiq`` uploads the documents the
joint Work IQ + Fabric IQ cases rely on (PLAN §4.4). Both are idempotent: they find what exists by
name and only create what is missing.

Modules:

* ``rest``          JSON over HTTPS with retries, paging and Fabric long-running operations.
* ``auth``          Token providers for the operator's sign-in (azure-identity, an optional extra).
* ``fabric``        A thin client for the Fabric, Power BI and OneLake REST APIs.
* ``graph``         A thin client for the Microsoft Graph calls the setup needs.
* ``fabric_deploy`` The Fabric deployment plan and its steps.
* ``workiq``        The Work IQ content pack: model, rendering and seeding.

Endpoints and permissions are recorded in config/contracts.yaml; nothing here has been run against a
tenant until spike results say so (docs/backlog).
"""
