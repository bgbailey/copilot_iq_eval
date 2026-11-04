<!-- BEGIN MICROSOFT SECURITY.MD V1.0.0 BLOCK -->

## Security

Microsoft takes the security of our software products and services seriously, which includes all source code repositories in our GitHub organizations.

**Please do not report security vulnerabilities through public GitHub issues.**

For security reporting information, locations, contact information, and policies, please review the latest guidance for Microsoft repositories at [https://aka.ms/SECURITY.md](https://aka.ms/SECURITY.md).

<!-- END MICROSOFT SECURITY.MD BLOCK -->

## Project-specific guidance

This harness signs in as test personas and reads tenant telemetry, so treat the following as security issues and report them through the channel above rather than as public issues:

- A secret, token, token cache, certificate or connection string committed to this repository or written to a workflow log or build artifact.
- A tenant identifier (tenant ID, domain, user principal name, workspace or item ID) committed to this repository.
- A workflow change that would expose repository secrets to untrusted pull requests.

The rules that prevent these are in [CONTRIBUTING.md](CONTRIBUTING.md#security-and-data-rules).
