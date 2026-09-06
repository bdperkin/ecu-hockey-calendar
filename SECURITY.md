# Security Policy

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [Supported Versions](#supported-versions)
- [Reporting a Vulnerability](#reporting-a-vulnerability)
- [Security Practices](#security-practices)
- [Response Timelines](#response-timelines)

______________________________________________________________________

<!--TOC-->

## Supported Versions

We actively provide security updates and bug fixes for the latest release branch of `ecu-hockey-calendar`:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

## Reporting a Vulnerability

We take the security of `ecu-hockey-calendar` seriously. If you discover a security vulnerability, please do **NOT** open a public GitHub issue.

Instead, please report vulnerabilities privately using one of the following methods:

1. **GitHub Private Vulnerability Reporting (Recommended)**:

   - Navigate to the [Security Advisories tab](https://github.com/bdperkin/ecu-hockey-calendar/security/advisories) of this repository.
   - Click **"Report a vulnerability"** to submit your advisory report privately to repository maintainers.

2. **Email Maintainer**:

   - Send an encrypted or confidential email detailing the issue to `bdperkin@gmail.com`.
   - Please include:
     - Description of the vulnerability and its potential impact.
     - Steps to reproduce or proof-of-concept code.
     - Affected versions or components.

## Security Practices

- **Automated Dependency Updates**: Dependabot monitors all dependencies and GitHub Actions.
- **CodeQL Scanning**: Static Application Security Testing (SAST) runs on all pushes and pull requests.
- **Secret Scanning & Push Protection**: Enabled to block accidental disclosure of API keys and credentials.
- **Private Vulnerability Reporting**: Enabled for confidential disclosures.

## Response Timelines

- **Initial Response**: Within 48 hours of report submission.
- **Assessment & Fix**: We strive to triage and remediate critical security issues promptly.
- **Public Disclosure**: Coordinated disclosure after a fix is published.
