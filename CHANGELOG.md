# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Releases and changelog entries are managed automatically by [Python Semantic Release](https://python-semantic-release.readthedocs.io/).

<!-- version list -->

## v0.7.1 (2026-09-12)

### Bug Fixes

- **security**: Resolve CodeQL polynomial ReDoS and unused global variables (#156)
  ([#157](https://github.com/bdperkin/ecu-hockey-calendar/pull/157),
  [`9adae77`](https://github.com/bdperkin/ecu-hockey-calendar/commit/9adae77485847f7e1e3bafb700c8173d940c3b8d))

### Chores

- **schedule**: Automated schedule sync and calendar update
  ([`fc61b40`](https://github.com/bdperkin/ecu-hockey-calendar/commit/fc61b4060393ec34dc522a12316d9ff4257b6bc3))

- **schedule**: Automated schedule sync and calendar update
  ([`823aa8a`](https://github.com/bdperkin/ecu-hockey-calendar/commit/823aa8a86bbfb00b868276b3777782e018ff78cf))

- **schedule**: Automated schedule sync and calendar update
  ([`36f1ec0`](https://github.com/bdperkin/ecu-hockey-calendar/commit/36f1ec0e3efdb06aa71a96665aa036b42eac729a))

- **schedule**: Automated schedule sync and calendar update
  ([`a099be1`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a099be10a513e04b0c94fff802b8954e97277d2b))

- **schedule**: Automated schedule sync and calendar update
  ([`028357c`](https://github.com/bdperkin/ecu-hockey-calendar/commit/028357c4eae83a0ed36da192647aee19f6cbd2b5))

### Documentation

- **roadmap**: Integrate favicon and web touch icons issue (#144)
  ([#145](https://github.com/bdperkin/ecu-hockey-calendar/pull/145),
  [`eb768dd`](https://github.com/bdperkin/ecu-hockey-calendar/commit/eb768dd59274ffebf1150a1d6adb94d5d62359cd))

- **roadmap**: Integrate project logo and visual branding issue (#142)
  ([#143](https://github.com/bdperkin/ecu-hockey-calendar/pull/143),
  [`fb4136b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/fb4136bcac9bda698652439229394e0ea549e10c))

### Features

- **api**: Content-negotiated HTML and JSON responses for conflicts endpoint (/api/v1/conflicts)
  (#100) ([#148](https://github.com/bdperkin/ecu-hockey-calendar/pull/148),
  [`f498882`](https://github.com/bdperkin/ecu-hockey-calendar/commit/f49888235070fe98ccd7c1ff23f0a108ff1c6c58))

- **api**: Content-negotiated HTML and JSON responses for health probe endpoint (/health)
  ([#141](https://github.com/bdperkin/ecu-hockey-calendar/pull/141),
  [`fac7d55`](https://github.com/bdperkin/ecu-hockey-calendar/commit/fac7d55d4647c753d6f147ae16e3ea6309ab698a))

- **api**: Content-negotiated HTML and JSON responses for sync status endpoint (/api/v1/sync/status)
  ([#147](https://github.com/bdperkin/ecu-hockey-calendar/pull/147),
  [`98e1ee3`](https://github.com/bdperkin/ecu-hockey-calendar/commit/98e1ee3e95add9e3c3e254b5029294e12082325b))

- **api**: Implement in-process background synchronization trigger with concurrency and cooldown
  safeguards (#117) ([#146](https://github.com/bdperkin/ecu-hockey-calendar/pull/146),
  [`91f1fa5`](https://github.com/bdperkin/ecu-hockey-calendar/commit/91f1fa5cfab087ac2b62cfac5d0b423d4d81a22e))


## v0.7.0 (2026-09-11)

### Chores

- **roadmap**: Incorporate multi-format quality hardening into Milestone 7 (#126-#132)
  ([#133](https://github.com/bdperkin/ecu-hockey-calendar/pull/133),
  [`b0f9260`](https://github.com/bdperkin/ecu-hockey-calendar/commit/b0f9260164a8c2ecbd1ab33c17f41f668b1dd9aa))

- **schedule**: Automated schedule sync and calendar update
  ([`99d0547`](https://github.com/bdperkin/ecu-hockey-calendar/commit/99d0547afa29b502471ecd5ec4d93fe221597c71))

- **tooling**: Add HTML and Jinja2 template linting and formatting with djlint (#126)
  ([#134](https://github.com/bdperkin/ecu-hockey-calendar/pull/134),
  [`18d9d4c`](https://github.com/bdperkin/ecu-hockey-calendar/commit/18d9d4c8fa5b115d92c6fd406872d703a6140291))

- **tooling**: Enforce EditorConfig rules and TOML validation across Makefile, pre-commit, and CI
  (#129) ([#137](https://github.com/bdperkin/ecu-hockey-calendar/pull/137),
  [`b66bcbb`](https://github.com/bdperkin/ecu-hockey-calendar/commit/b66bcbb3e1e69ccab13e3e9e531ff6ce38a5b892))

### Continuous Integration

- **actions**: Validate GitHub Actions workflows and YAML configurations with actionlint and
  yamllint (#128) ([#136](https://github.com/bdperkin/ecu-hockey-calendar/pull/136),
  [`9835c9f`](https://github.com/bdperkin/ecu-hockey-calendar/commit/9835c9f729f7fabce3d76bde8e00836fa21b2974))

- **docker**: Add Dockerfile linting with Hadolint and Compose validation (#127)
  ([#135](https://github.com/bdperkin/ecu-hockey-calendar/pull/135),
  [`bd4bde5`](https://github.com/bdperkin/ecu-hockey-calendar/commit/bd4bde5acd551045a9be51c4290cd86dfcdcdca9))

- **security**: Integrate automated dependency vulnerability auditing with uv audit
  ([#140](https://github.com/bdperkin/ecu-hockey-calendar/pull/140),
  [`5793a5e`](https://github.com/bdperkin/ecu-hockey-calendar/commit/5793a5ede636f876d27a5f93fd9b249490621b0d))

### Documentation

- **quality**: Unify Markdown lint targets, resolve file discrepancies, and add link checking
  ([#139](https://github.com/bdperkin/ecu-hockey-calendar/pull/139),
  [`5e9523f`](https://github.com/bdperkin/ecu-hockey-calendar/commit/5e9523fc7cb4864bc078254ab205ffea0e73e86a))

### Features

- **quality**: Implement static feed validation for CSV, iCalendar (ICS), and JSON exports
  ([#138](https://github.com/bdperkin/ecu-hockey-calendar/pull/138),
  [`801d115`](https://github.com/bdperkin/ecu-hockey-calendar/commit/801d1150a57db7b4bf80de1ba31e76a58af3cf63))


## v0.6.0 (2026-09-11)

### Chores

- **schedule**: Automated schedule sync and calendar update
  ([`0caa954`](https://github.com/bdperkin/ecu-hockey-calendar/commit/0caa95400000238c71a766f3f777e7f0dccff340))

- **schedule**: Automated schedule sync and calendar update
  ([`9f16957`](https://github.com/bdperkin/ecu-hockey-calendar/commit/9f169570d197bb74bc1e76f1e4326d46b2e7dd7e))

### Features

- **api**: Content-negotiated HTML and JSON error responses for 401, 404, 422, and 500 (#101)
  ([#124](https://github.com/bdperkin/ecu-hockey-calendar/pull/124),
  [`2bf782b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/2bf782bfd29494a73203288eb01c306c04300777))

- **api**: Content-negotiated HTML and JSON responses for service status endpoint (/) (#97)
  ([#123](https://github.com/bdperkin/ecu-hockey-calendar/pull/123),
  [`e2eaa04`](https://github.com/bdperkin/ecu-hockey-calendar/commit/e2eaa04993daf96c4788630cbe554ef3c342aa69))

- **export**: Printable schedule grid PDF generation for parents and coaches (#79)
  ([#125](https://github.com/bdperkin/ecu-hockey-calendar/pull/125),
  [`49f70fa`](https://github.com/bdperkin/ecu-hockey-calendar/commit/49f70fa4c0e19ae2ed10a91c58243ca74daf8121))

- **web**: Responsive HTML schedule view and embeddable iframe widget (#77)
  ([#122](https://github.com/bdperkin/ecu-hockey-calendar/pull/122),
  [`0e79502`](https://github.com/bdperkin/ecu-hockey-calendar/commit/0e79502d157fa941c8c8d8e7cc7dabad221e5459))


## v0.5.0 (2026-09-11)

### Bug Fixes

- **api**: Resolve DATABASE_URL and ADMIN_API_TOKEN from environment in create_app
  ([#93](https://github.com/bdperkin/ecu-hockey-calendar/pull/93),
  [`3f948f6`](https://github.com/bdperkin/ecu-hockey-calendar/commit/3f948f6e6def244cd8e7813f2a644037374d934c))

- **api**: Resolve second-boundary race condition in calendar ETag generation and add CI test
  resilience (#114) ([#115](https://github.com/bdperkin/ecu-hockey-calendar/pull/115),
  [`be8807f`](https://github.com/bdperkin/ecu-hockey-calendar/commit/be8807ffa667a55743fe57c5f483c483fe5720e7))

- **api**: Return 501 Not Implemented from POST /api/v1/sync/trigger when unconfigured (#116)
  ([#119](https://github.com/bdperkin/ecu-hockey-calendar/pull/119),
  [`65a3c0e`](https://github.com/bdperkin/ecu-hockey-calendar/commit/65a3c0e2bc4d9c62434acd237d08b636ec2931b9))

- **ci**: Add polling retry loop to deployment version provenance verification
  ([#109](https://github.com/bdperkin/ecu-hockey-calendar/pull/109),
  [`c9a6f47`](https://github.com/bdperkin/ecu-hockey-calendar/commit/c9a6f4703088aff7b8498a079b30f710789260be))

- **ci**: Fix deployment workflow syntax and rename workflow to Deployment
  ([#90](https://github.com/bdperkin/ecu-hockey-calendar/pull/90),
  [`d6ff862`](https://github.com/bdperkin/ecu-hockey-calendar/commit/d6ff8620c8ccdb4d3d09a8e0a895f270c8332483))

- **ci**: Resolve invalid secrets context in deployment workflow and restore workflow display name
  (#107) ([#108](https://github.com/bdperkin/ecu-hockey-calendar/pull/108),
  [`043450d`](https://github.com/bdperkin/ecu-hockey-calendar/commit/043450dbb4ced190e047fd6a0a9f8d1a9581e327))

- **deploy**: Update Render blueprint instance plans to modern compute tiers
  ([#91](https://github.com/bdperkin/ecu-hockey-calendar/pull/91),
  [`8824759`](https://github.com/bdperkin/ecu-hockey-calendar/commit/8824759c090877386b9dbe20003db7dd74cd5553))

- **packaging**: Resolve fallback version 0.1.0.dev0 reported by containerized API and deployments
  (#94) ([#106](https://github.com/bdperkin/ecu-hockey-calendar/pull/106),
  [`d8e0358`](https://github.com/bdperkin/ecu-hockey-calendar/commit/d8e0358fa12e3350a1022fe2cbeeec86af19436d))

- **quality**: Resolve CodeQL empty-except alerts in version resolution module (#110)
  ([#111](https://github.com/bdperkin/ecu-hockey-calendar/pull/111),
  [`a4ad8a1`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a4ad8a125e984450cdfa47220056042f36a090f2))

- **release**: Diagnose and align release versioning with project milestones (closes #73)
  ([#75](https://github.com/bdperkin/ecu-hockey-calendar/pull/75),
  [`f0e8df4`](https://github.com/bdperkin/ecu-hockey-calendar/commit/f0e8df4b2c76262367a9524a051e523b2f49b4ce))

- **storage**: Add psycopg driver and normalize postgres URLs to postgresql+psycopg
  ([#92](https://github.com/bdperkin/ecu-hockey-calendar/pull/92),
  [`0e81122`](https://github.com/bdperkin/ecu-hockey-calendar/commit/0e811227d5da697f5c70d8a96e32992ec535e951))

### Continuous Integration

- **automation**: Automated scheduled ingestion and calendar release workflow (#16)
  ([#105](https://github.com/bdperkin/ecu-hockey-calendar/pull/105),
  [`be8da4d`](https://github.com/bdperkin/ecu-hockey-calendar/commit/be8da4ddfe06726ab911b8b5e531071d158e22e0))

- **deploy**: Automated production deployment to hosting service via GitHub Actions (closes #84)
  ([#89](https://github.com/bdperkin/ecu-hockey-calendar/pull/89),
  [`cabd679`](https://github.com/bdperkin/ecu-hockey-calendar/commit/cabd679616d230e87204347f6ed018e776697c0a))

- **docker**: Automated publication of production container images to ghcr.io via GitHub Actions
  (closes #82) ([#88](https://github.com/bdperkin/ecu-hockey-calendar/pull/88),
  [`aa8f00b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/aa8f00b2feb991a138737ee9e204ac69a70afd99))

### Documentation

- Update README.md and Sphinx documentation to reflect current project capabilities (#63)
  ([#121](https://github.com/bdperkin/ecu-hockey-calendar/pull/121),
  [`8106ed1`](https://github.com/bdperkin/ecu-hockey-calendar/commit/8106ed1ed79d27216fcb788de15675355ee8aa0e))

- **calendar**: Add end-user ECU Hockey Calendar Sync Guide for Google, Apple, and Outlook
  subscriptions ([#113](https://github.com/bdperkin/ecu-hockey-calendar/pull/113),
  [`6103730`](https://github.com/bdperkin/ecu-hockey-calendar/commit/61037303a783ccc25c6c954509e0ca3a846ff0f7))

- **deployment**: Architectural hosting analysis and production deployment guide (closes #14)
  ([#81](https://github.com/bdperkin/ecu-hockey-calendar/pull/81),
  [`74535c6`](https://github.com/bdperkin/ecu-hockey-calendar/commit/74535c67920af89618fe9b67f81579952f7ad354))

- **deployment**: Document live production deployment at ecu-hockey-api.onrender.com with full
  endpoint reference ([#112](https://github.com/bdperkin/ecu-hockey-calendar/pull/112),
  [`fe8813e`](https://github.com/bdperkin/ecu-hockey-calendar/commit/fe8813eb901cc6e1d457903fec918c9549f75bc4))

- **readme**: Audit and add status, quality, and technology badges (#86)
  ([#120](https://github.com/bdperkin/ecu-hockey-calendar/pull/120),
  [`1cacc97`](https://github.com/bdperkin/ecu-hockey-calendar/commit/1cacc973fb7f6b23bbaed9ee2659f0e341e67d86))

- **roadmap**: Add ten issues and restructure milestone sequencing by user value
  ([#104](https://github.com/bdperkin/ecu-hockey-calendar/pull/104),
  [`ba3c724`](https://github.com/bdperkin/ecu-hockey-calendar/commit/ba3c724fdd32fd1d18852dabba921e7cc03853a7))

- **roadmap**: Record findings for issue #102 and schedule follow-up issues #116 and #117
  ([#118](https://github.com/bdperkin/ecu-hockey-calendar/pull/118),
  [`890fb91`](https://github.com/bdperkin/ecu-hockey-calendar/commit/890fb91af6813ecf681b1d5751448935a8c48d1b))

- **roadmap**: Track ghcr container publication issue in TODO.md
  ([#83](https://github.com/bdperkin/ecu-hockey-calendar/pull/83),
  [`f660db9`](https://github.com/bdperkin/ecu-hockey-calendar/commit/f660db952cbd59b0e88b2f951a2e99103a5c15d0))

- **roadmap**: Track milestone 6 fan engagement and export issues in TODO.md
  ([#80](https://github.com/bdperkin/ecu-hockey-calendar/pull/80),
  [`ba6f528`](https://github.com/bdperkin/ecu-hockey-calendar/commit/ba6f528cfc47f97de6a49bb065ed0498ef7e51ba))

- **roadmap**: Track production deployment issue in TODO.md
  ([#85](https://github.com/bdperkin/ecu-hockey-calendar/pull/85),
  [`f9c2ef1`](https://github.com/bdperkin/ecu-hockey-calendar/commit/f9c2ef1dd75bde4102ed062974a2e4a1a27d2fce))

- **roadmap**: Track readme badges audit issue in TODO.md
  ([#87](https://github.com/bdperkin/ecu-hockey-calendar/pull/87),
  [`295952e`](https://github.com/bdperkin/ecu-hockey-calendar/commit/295952e01ada4af3e83dbe1dcfe1a4ecf46f1ea7))

- **roadmap**: Track release version alignment issue #73 in TODO.md
  ([#74](https://github.com/bdperkin/ecu-hockey-calendar/pull/74),
  [`2a16f19`](https://github.com/bdperkin/ecu-hockey-calendar/commit/2a16f19d1b60610e0cb472b246abeb7addbaceaa))

### Features

- **cli**: Command-line interface for schedule sync, inspection, and export (closes #13)
  ([#76](https://github.com/bdperkin/ecu-hockey-calendar/pull/76),
  [`f265731`](https://github.com/bdperkin/ecu-hockey-calendar/commit/f265731a17829c9b5d05785b97685907836892e6))


## v0.4.0 (2026-09-08)

### Features

- **api**: Health check, sync diagnostics, and conflict review endpoints (closes #12)
  ([#68](https://github.com/bdperkin/ecu-hockey-calendar/pull/68),
  [`5cfc7f0`](https://github.com/bdperkin/ecu-hockey-calendar/commit/5cfc7f082bd957d03d306c55f5830930c3d9827c))

- **api**: Public JSON and CSV master schedule data feeds (closes #11)
  ([#67](https://github.com/bdperkin/ecu-hockey-calendar/pull/67),
  [`9736b10`](https://github.com/bdperkin/ecu-hockey-calendar/commit/9736b1086e4cfdc4efaa8662849b20d5d72f38fd))

- **api**: RFC 5545 iCalendar (.ics) subscription endpoint and webcal support (closes #10)
  ([#66](https://github.com/bdperkin/ecu-hockey-calendar/pull/66),
  [`aeca113`](https://github.com/bdperkin/ecu-hockey-calendar/commit/aeca1130a254fd6c9503fdae05318bfc0817f0a9))

### Bug Fixes

- **security**: Resolve CodeQL alert 14 for stack trace exposure in health route (closes #69)
  ([#70](https://github.com/bdperkin/ecu-hockey-calendar/pull/70),
  [`6de0ee0`](https://github.com/bdperkin/ecu-hockey-calendar/commit/6de0ee01c1da86657b47230fa8220fcaab10001e))

### Documentation

- Update README.md and Sphinx documentation to reflect current project capabilities (closes #62)
  ([#72](https://github.com/bdperkin/ecu-hockey-calendar/pull/72),
  [`a89ae9f`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a89ae9fda7d8b1273a4c9eae08609b63091f61d4))

- **roadmap**: Update CodeQL audit trail reference for alert 14 with PR #70
  ([#71](https://github.com/bdperkin/ecu-hockey-calendar/pull/71),
  [`3dcca07`](https://github.com/bdperkin/ecu-hockey-calendar/commit/3dcca07604fdf37b4200424564c45b85a3cff977))


## v0.3.0 (2026-09-08)

### Features

- **notifications**: Multi-platform webhook alerting for schedule updates and conflicts (#15)
  ([#60](https://github.com/bdperkin/ecu-hockey-calendar/pull/60),
  [`5bc7c39`](https://github.com/bdperkin/ecu-hockey-calendar/commit/5bc7c39beab73874f8fcb3214f368fd347992113))

- **reconciliation**: Change detection and sync state tracking engine
  ([#9](https://github.com/bdperkin/ecu-hockey-calendar/pull/9),
  [`2665436`](https://github.com/bdperkin/ecu-hockey-calendar/commit/2665436d9fbcc8766d3af609b8fd6ee7e7c9af83))

- **reconciliation**: Implement fuzzy-matching and multi-source conflict resolution engine (#8)
  ([#38](https://github.com/bdperkin/ecu-hockey-calendar/pull/38),
  [`7185a3a`](https://github.com/bdperkin/ecu-hockey-calendar/commit/7185a3aed6a704ad74e4deb725032df884d96f17))

### Bug Fixes

- **ci**: Configure Python Semantic Release changelog automation (#45)
  ([#54](https://github.com/bdperkin/ecu-hockey-calendar/pull/54),
  [`14f47c8`](https://github.com/bdperkin/ecu-hockey-calendar/commit/14f47c844e4a324ba1b5dbf3673098ba918793c5))

- **ci**: Exclude CHANGELOG.md from pymarkdown pre-commit hook
  ([#56](https://github.com/bdperkin/ecu-hockey-calendar/pull/56),
  [`7227ad0`](https://github.com/bdperkin/ecu-hockey-calendar/commit/7227ad0158f8cfbc434c2c388ee21c99db820372))

- **release**: Align release versioning with project milestones and configure 0.x commit parser
  (#48) ([#57](https://github.com/bdperkin/ecu-hockey-calendar/pull/57),
  [`d5ff5ea`](https://github.com/bdperkin/ecu-hockey-calendar/commit/d5ff5eaf9ddecd9e98003aca9a32fec80d4d643f))

- **security**: Resolve CodeQL alert 12 for unused global variable in fuzzy_matcher (#39)
  ([#40](https://github.com/bdperkin/ecu-hockey-calendar/pull/40),
  [`4e96abd`](https://github.com/bdperkin/ecu-hockey-calendar/commit/4e96abd7d5417e07ef7d7e6d81dbc68842c111b0))

- **security**: Resolve CodeQL alert 13 for import and import-from in
  test_reconciliation_fuzzy_matcher (#41)
  ([#42](https://github.com/bdperkin/ecu-hockey-calendar/pull/42),
  [`58a3d3a`](https://github.com/bdperkin/ecu-hockey-calendar/commit/58a3d3abd1db16f90a036a51888e34de9c8aa1b8))

- **types**: Resolve ty 0.0.79 redundant condition diagnostics in acchockey_parser
  ([#55](https://github.com/bdperkin/ecu-hockey-calendar/pull/55),
  [`107ce03`](https://github.com/bdperkin/ecu-hockey-calendar/commit/107ce033fca762528ba3693a15ba024ea57b62ae))

### Chores

- **deps**: Update pre-commit-hooks to v6.0.0 and validate-pyproject to 0.26
  ([#53](https://github.com/bdperkin/ecu-hockey-calendar/pull/53),
  [`6484f6b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/6484f6bc983e7018d602be634e55887cd30cf123))

- **roadmap**: Remove ecu_hockey_scraper_prompt.md and audit TODO.md (#47)
  ([#49](https://github.com/bdperkin/ecu-hockey-calendar/pull/49),
  [`fa6f121`](https://github.com/bdperkin/ecu-hockey-calendar/commit/fa6f1215ce0976e102d8fe90eaf41aa49cdd3204))

- **tooling**: Migrate PyMarkdown configuration from .pymarkdown.json into pyproject.toml (#44)
  ([#52](https://github.com/bdperkin/ecu-hockey-calendar/pull/52),
  [`86aee53`](https://github.com/bdperkin/ecu-hockey-calendar/commit/86aee53b0220b721a6274a9f8f490efc02e92c94))

### Documentation

- Update README.md and Sphinx documentation to reflect current project capabilities (closes #46)
  ([#65](https://github.com/bdperkin/ecu-hockey-calendar/pull/65),
  [`7d1480f`](https://github.com/bdperkin/ecu-hockey-calendar/commit/7d1480fd5f063984babff62b9cdb0bff2cbe145c))

- **roadmap**: Mark issue #15 complete in TODO.md
  ([#61](https://github.com/bdperkin/ecu-hockey-calendar/pull/61),
  [`0c32e6d`](https://github.com/bdperkin/ecu-hockey-calendar/commit/0c32e6db0e9dc57a5010d9dfe57c338dfc1898ae))

- **roadmap**: Track documentation alignment issues #62 and #63 in TODO.md
  ([#64](https://github.com/bdperkin/ecu-hockey-calendar/pull/64),
  [`387094b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/387094b6843fc71888ac97c601047fd651f45037))

- **roadmap**: Mark issues #48 and #9 complete in TODO.md
  ([#59](https://github.com/bdperkin/ecu-hockey-calendar/pull/59),
  [`1a193e5`](https://github.com/bdperkin/ecu-hockey-calendar/commit/1a193e5ad3c0cc6a69e850c84ffff7cd58964e2e))

- **roadmap**: Mark issue #47 complete in TODO.md
  ([#50](https://github.com/bdperkin/ecu-hockey-calendar/pull/50),
  [`39d13c8`](https://github.com/bdperkin/ecu-hockey-calendar/commit/39d13c8459d9d30e3b49346b74f7f8dc8727225a))

- **roadmap**: Track CodeQL alert resolutions #39 and #41 in TODO.md
  ([#43](https://github.com/bdperkin/ecu-hockey-calendar/pull/43),
  [`0f5a0e2`](https://github.com/bdperkin/ecu-hockey-calendar/commit/0f5a0e2e9b749d72eb3d9f43d8b2ef1ec31bf5e3))


## v0.2.0 (2026-09-06)

### Features

- **ingestion**: Automated opponent schedule reverse lookup and cross-check (#7)
  ([#37](https://github.com/bdperkin/ecu-hockey-calendar/pull/37),
  [`a4c885c`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a4c885cc6eabd4077c05b5383582e4612f4ad7ef))

- **ingestion**: Create resilient Instagram feed parser for game announcements (#6)
  ([#36](https://github.com/bdperkin/ecu-hockey-calendar/pull/36),
  [`5c48232`](https://github.com/bdperkin/ecu-hockey-calendar/commit/5c4823209a35b0b6283aa6208291f03e2f1bfa1e))

- **ingestion**: Parse ticket sales page for game schedules and promotions
  ([#34](https://github.com/bdperkin/ecu-hockey-calendar/pull/34),
  [`a278df0`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a278df04cc22396b65744da5a2e82995aef043ec))

- **ingestion**: Implement ACC Hockey league schedule page parser (#4)
  ([#33](https://github.com/bdperkin/ecu-hockey-calendar/pull/33),
  [`146a83f`](https://github.com/bdperkin/ecu-hockey-calendar/commit/146a83f7321b042bbbd8a83f7ba42f6b76039a4e))

- **ingestion**: Build resilient crawler for primary ECU Hockey schedule site (#3)
  ([#32](https://github.com/bdperkin/ecu-hockey-calendar/pull/32),
  [`2cb464c`](https://github.com/bdperkin/ecu-hockey-calendar/commit/2cb464cc01b2c5ca1a7c25a20e58c22d6d8bb27b))

- **storage**: Implement SQLAlchemy models and Alembic migration pipeline (#2)
  ([#24](https://github.com/bdperkin/ecu-hockey-calendar/pull/24),
  [`32047ba`](https://github.com/bdperkin/ecu-hockey-calendar/commit/32047baf847ea1aa9021cc752fda737ed8df1c25))

### Bug Fixes

- **ingestion**: Add explanatory comments to fallback except blocks to resolve CodeQL alerts
  ([#35](https://github.com/bdperkin/ecu-hockey-calendar/pull/35),
  [`131079b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/131079b65bbb38610ae6ab0a0578c8f0256d4bc8))

- **security**: Resolve CodeQL security and quality code scanning alerts (#25)
  ([#26](https://github.com/bdperkin/ecu-hockey-calendar/pull/26),
  [`3e2ab86`](https://github.com/bdperkin/ecu-hockey-calendar/commit/3e2ab86edae6cab7caf6bd16fa3447e8107f9b51))

### Chores

- **deps**: Bump actions and codecov actions
  ([#27](https://github.com/bdperkin/ecu-hockey-calendar/pull/27),
  [#28](https://github.com/bdperkin/ecu-hockey-calendar/pull/28),
  [#29](https://github.com/bdperkin/ecu-hockey-calendar/pull/29),
  [#30](https://github.com/bdperkin/ecu-hockey-calendar/pull/30),
  [#31](https://github.com/bdperkin/ecu-hockey-calendar/pull/31))


## v0.1.2 (2026-09-06)

### Bug Fixes

- **ci**: Install all extras in pages workflow
  ([#23](https://github.com/bdperkin/ecu-hockey-calendar/pull/23),
  [`30cc8b2`](https://github.com/bdperkin/ecu-hockey-calendar/commit/30cc8b22ff52a7fd236726e36a6f0368c19c73f9))

### Continuous Integration

- **codecov**: Configure JUnit XML test results and test analytics upload
  ([#21](https://github.com/bdperkin/ecu-hockey-calendar/pull/21),
  [`c623dde`](https://github.com/bdperkin/ecu-hockey-calendar/commit/c623dde5ec9d2d648cbf196f1ef272f1b3563f06))

- **pages**: Automated GitHub Pages deployment for Sphinx documentation (#18)
  ([#22](https://github.com/bdperkin/ecu-hockey-calendar/pull/22),
  [`12e68c5`](https://github.com/bdperkin/ecu-hockey-calendar/commit/12e68c57c6acd55fe5111c61e92732f354f5d175))

## v0.1.1 (2026-09-06)

### Bug Fixes

- **release**: Enable zero-version mode and disable major bump on zero
  ([#20](https://github.com/bdperkin/ecu-hockey-calendar/pull/20),
  [`02ca7f3`](https://github.com/bdperkin/ecu-hockey-calendar/commit/02ca7f3927a3dfdf16a6bacc56be23238f79ab99))

### Documentation

- **roadmap**: Integrate scraper specification and roadmap into TODO.md
  ([#17](https://github.com/bdperkin/ecu-hockey-calendar/pull/17),
  [`3254385`](https://github.com/bdperkin/ecu-hockey-calendar/commit/3254385ceccd97362cf457c4b8cf2d6104731ef9))

- **roadmap**: Track GitHub Pages deployment issue #18 in TODO roadmap
  ([#19](https://github.com/bdperkin/ecu-hockey-calendar/pull/19),
  [`6320ded`](https://github.com/bdperkin/ecu-hockey-calendar/commit/6320dedebee2e8b0bfa0c0aabc8b7dac1bf845cc))

## v0.1.0 (2026-09-05)

- Initial Release
