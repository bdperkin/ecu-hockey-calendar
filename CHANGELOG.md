# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Releases and changelog entries are managed automatically by [Python Semantic Release](https://python-semantic-release.readthedocs.io/).

<!-- version list -->

## v0.9.0 (2026-09-22)

### Bug Fixes

- **ingestion**: Correct score assignment for away games in ecuhockey crawler
  ([#230](https://github.com/bdperkin/ecu-hockey-calendar/pull/230),
  [`8fc58ae`](https://github.com/bdperkin/ecu-hockey-calendar/commit/8fc58ae0df440a8c04b0f329cfdc0a5d09239a2c))

- **reconciliation**: Auto-resolve cosmetic schedule discrepancies across sources (#231)
  ([#232](https://github.com/bdperkin/ecu-hockey-calendar/pull/232),
  [`38e5e7e`](https://github.com/bdperkin/ecu-hockey-calendar/commit/38e5e7ec042c492353dd529885c0f8f4bf20d486))

- **reconciliation**: Treat fixtures on different dates or with distinct scores as unique events
  ([#227](https://github.com/bdperkin/ecu-hockey-calendar/pull/227),
  [`2a129fe`](https://github.com/bdperkin/ecu-hockey-calendar/commit/2a129fe013c6ce63e64c941049e321e16e252ce3))

- **reconciliation**: Weight home team over visitor and multi-source consensus for away games
  ([#219](https://github.com/bdperkin/ecu-hockey-calendar/pull/219),
  [`ce68d6f`](https://github.com/bdperkin/ecu-hockey-calendar/commit/ce68d6fe66c133524117698f4d140347e4d3e330))

- **security**: Resolve CodeQL scanning quality and maintainability alerts
  ([#221](https://github.com/bdperkin/ecu-hockey-calendar/pull/221),
  [`a6aae05`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a6aae056f43b51ad596b253ec1c1e0ca6f225bcb))

- **sync**: Prune stale and superseded game fixtures from database during sync
  ([#220](https://github.com/bdperkin/ecu-hockey-calendar/pull/220),
  [`a3c01c9`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a3c01c9f64386c383e4c2df9da3ab4e7e58dd9c3))

### Chores

- **deps**: Bump actions/deploy-pages from 4 to 5
  ([#217](https://github.com/bdperkin/ecu-hockey-calendar/pull/217),
  [`5210bf2`](https://github.com/bdperkin/ecu-hockey-calendar/commit/5210bf2c5b80f3a7395c5d7fde4c65f4caeac7f7))

- **deps**: Bump actions/upload-pages-artifact from 3 to 5
  ([#216](https://github.com/bdperkin/ecu-hockey-calendar/pull/216),
  [`169ba6b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/169ba6bdc98147b77ce2d18b7c9ed9bed10e52fe))

- **deps**: Bump astral-sh/setup-uv from 5 to 7
  ([#210](https://github.com/bdperkin/ecu-hockey-calendar/pull/210),
  [`6320aa4`](https://github.com/bdperkin/ecu-hockey-calendar/commit/6320aa42265e7ab48c83f7736be5e2465a72d29c))

- **deps**: Bump docker/metadata-action from 5 to 6
  ([#214](https://github.com/bdperkin/ecu-hockey-calendar/pull/214),
  [`1386a33`](https://github.com/bdperkin/ecu-hockey-calendar/commit/1386a33e17cfd76e1e381361f98ad8a59b0226e2))

- **deps**: Bump hadolint/hadolint-action from 3.1.0 to 3.5.0
  ([#212](https://github.com/bdperkin/ecu-hockey-calendar/pull/212),
  [`05e4403`](https://github.com/bdperkin/ecu-hockey-calendar/commit/05e44031d637e67582ae77da14d1ec1e56e2e789))

- **deps**: Update pre-commit hooks
  ([#234](https://github.com/bdperkin/ecu-hockey-calendar/pull/234),
  [`c233619`](https://github.com/bdperkin/ecu-hockey-calendar/commit/c2336192e87f1cd3f5b9bb315b4c331027dd7f80))

- **deps**: Upgrade dependencies in uv.lock and requirements.txt
  ([#222](https://github.com/bdperkin/ecu-hockey-calendar/pull/222),
  [`58c1306`](https://github.com/bdperkin/ecu-hockey-calendar/commit/58c13063557c33c7ef1d0a5e1e9d3ce83ab7b2c9))

- **schedule**: Automated schedule sync and calendar update
  ([`67c2540`](https://github.com/bdperkin/ecu-hockey-calendar/commit/67c2540b50bf218ac69386097b0e7835caeb539d))

- **schedule**: Automated schedule sync and calendar update
  ([`a21d851`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a21d85104fe34d909eced5f1110d6a55dd18131a))

- **schedule**: Automated schedule sync and calendar update
  ([`cb47b12`](https://github.com/bdperkin/ecu-hockey-calendar/commit/cb47b12dd749d2ec59153013ba7774347bd90afd))

- **schedule**: Automated schedule sync and calendar update
  ([`6608593`](https://github.com/bdperkin/ecu-hockey-calendar/commit/6608593fb6d8f55a6e7c553630d9b043fff9f390))

- **schedule**: Automated schedule sync and calendar update
  ([`6f26dfc`](https://github.com/bdperkin/ecu-hockey-calendar/commit/6f26dfc90e7e75d9f4451f4be9a8ae150a6ceb34))

- **schedule**: Automated schedule sync and calendar update
  ([`ebc049d`](https://github.com/bdperkin/ecu-hockey-calendar/commit/ebc049dd02010086456b61ff3fea6551c33c2ddc))

- **schedule**: Automated schedule sync and calendar update
  ([`57f3e9d`](https://github.com/bdperkin/ecu-hockey-calendar/commit/57f3e9db9e080a08e9a37bf68b0b55d08de314cf))

- **schedule**: Automated schedule sync and calendar update
  ([`b74fb69`](https://github.com/bdperkin/ecu-hockey-calendar/commit/b74fb69763be27fe0f6189b9586b8c233435c4d9))

- **schedule**: Automated schedule sync and calendar update
  ([`7628034`](https://github.com/bdperkin/ecu-hockey-calendar/commit/7628034caf6cde01170d4a538fc88fa7b92a52ad))

- **schedule**: Automated schedule sync and calendar update
  ([`a064dfb`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a064dfbeff35b959f74c0ad32803f32f42ce14cc))

- **schedule**: Automated schedule sync and calendar update
  ([`d21b181`](https://github.com/bdperkin/ecu-hockey-calendar/commit/d21b1818253c6326389e42b7dbb807f03cd204a5))

- **schedule**: Automated schedule sync and calendar update
  ([`938a7b0`](https://github.com/bdperkin/ecu-hockey-calendar/commit/938a7b09741dfe1770dc0b7c6647dbf89a4521b9))

- **schedule**: Automated schedule sync and calendar update
  ([`1294960`](https://github.com/bdperkin/ecu-hockey-calendar/commit/129496051dea60d11a4e8c159aaafb3c1f15ea86))

- **schedule**: Automated schedule sync and calendar update
  ([`e85b96c`](https://github.com/bdperkin/ecu-hockey-calendar/commit/e85b96c03c4e7348bc4cd216fdf2c2db3d9a3036))

- **schedule**: Automated schedule sync and calendar update
  ([`0d68c83`](https://github.com/bdperkin/ecu-hockey-calendar/commit/0d68c83851ef98b21ef523139e8af6d80a73c0af))

- **schedule**: Automated schedule sync and calendar update
  ([`4f6fd60`](https://github.com/bdperkin/ecu-hockey-calendar/commit/4f6fd605a118f906e14f2f589290b617cf9bde54))

### Features

- **cli**: Add 'conflicts get' subcommand for detailed game discrepancy inspection
  ([#224](https://github.com/bdperkin/ecu-hockey-calendar/pull/224),
  [`c42d2b5`](https://github.com/bdperkin/ecu-hockey-calendar/commit/c42d2b5d25e716069ae9f767ec314462a03f2e98))

- **cli**: Add opponent discover subcommand to spider base URL and auto-detect schedule
  configuration (#200) ([#206](https://github.com/bdperkin/ecu-hockey-calendar/pull/206),
  [`56eb886`](https://github.com/bdperkin/ecu-hockey-calendar/commit/56eb8860625a7a90558d450f48149c5726644fc4))

- **cli**: Add production database sync trigger capability
  ([#207](https://github.com/bdperkin/ecu-hockey-calendar/pull/207),
  [`ad34d9e`](https://github.com/bdperkin/ecu-hockey-calendar/commit/ad34d9e4d443b1d1eab43344ecaa1ac3b520b363))

- **cli**: Integrate rich-click for enhanced terminal help formatting and styling (#225)
  ([#233](https://github.com/bdperkin/ecu-hockey-calendar/pull/233),
  [`b0b9106`](https://github.com/bdperkin/ecu-hockey-calendar/commit/b0b91061fa309fe4a0961a11ade5f25342a93b6e))

- **conflicts**: Administrative manual conflict resolution and override workflow (#188)
  ([#218](https://github.com/bdperkin/ecu-hockey-calendar/pull/218),
  [`4cc65cf`](https://github.com/bdperkin/ecu-hockey-calendar/commit/4cc65cf02595f001e6d8a9df7ae421a3b96b13f9))

- **ingestion**: Automated team logo discovery and extraction from league crawlers (#237)
  ([#239](https://github.com/bdperkin/ecu-hockey-calendar/pull/239),
  [`298fc31`](https://github.com/bdperkin/ecu-hockey-calendar/commit/298fc31d764dec6aa9b028161f56ca38108622ee))

- **ingestion,storage**: Support dual remote and local logo URLs with caching and conditional sync
  (#236) ([#238](https://github.com/bdperkin/ecu-hockey-calendar/pull/238),
  [`f3ccb08`](https://github.com/bdperkin/ecu-hockey-calendar/commit/f3ccb08650a3d028a667c9c384ab52c15bcd4d2d))

- **web,pdf**: Add team logo icons to Web and PDF schedule outputs (#228)
  ([#235](https://github.com/bdperkin/ecu-hockey-calendar/pull/235),
  [`8182698`](https://github.com/bdperkin/ecu-hockey-calendar/commit/81826980861acdeb0e0ea026e0f88b448e38f208))


## v0.8.1 (2026-09-19)

### Bug Fixes

- **api**: Fix schedule feed season defaults and now divider chronological check
  ([#185](https://github.com/bdperkin/ecu-hockey-calendar/pull/185),
  [`cb12904`](https://github.com/bdperkin/ecu-hockey-calendar/commit/cb12904989d0d53b2e1e2159cad74eb0f9460d87))

- **conflicts**: Reconcile CONFLICT_DETECTED change type query filter in API and CLI (#166)
  ([#167](https://github.com/bdperkin/ecu-hockey-calendar/pull/167),
  [`013fa05`](https://github.com/bdperkin/ecu-hockey-calendar/commit/013fa05731650f18915888a9479b0018c52c657f))

- **ingestion**: Prevent future scheduled games from displaying as 0-0 ties
  ([#186](https://github.com/bdperkin/ecu-hockey-calendar/pull/186),
  [`ddc4f59`](https://github.com/bdperkin/ecu-hockey-calendar/commit/ddc4f59f4331f830fed6871b4c5f6a8c5cbf16ab))

- **ingestion**: Resolve acchockey scraper subseason discovery and column parsing failures (#193)
  ([#201](https://github.com/bdperkin/ecu-hockey-calendar/pull/201),
  [`f9b173a`](https://github.com/bdperkin/ecu-hockey-calendar/commit/f9b173a51bdd5c600718a5d6eb682b55118f7826))

- **quality**: Resolve CodeQL alert #22 for empty except in remote client sync handler (#178)
  ([#179](https://github.com/bdperkin/ecu-hockey-calendar/pull/179),
  [`3caec31`](https://github.com/bdperkin/ecu-hockey-calendar/commit/3caec3185dfca09161985b5c659cf6ec8f33f9fe))

- **reconciliation**: Prevent false clustering of weekend series and filter superseded conflicts
  ([#189](https://github.com/bdperkin/ecu-hockey-calendar/pull/189),
  [`c9e9e18`](https://github.com/bdperkin/ecu-hockey-calendar/commit/c9e9e18bd486faa0d149f13451a550a8c29d5831))

### Chores

- **deps**: Update pre-commit hooks and configure pymarkdown MD051 rule (#180)
  ([#181](https://github.com/bdperkin/ecu-hockey-calendar/pull/181),
  [`a4cff2a`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a4cff2a27d2ba8913b79d6866e1c724826bbd3c7))

- **schedule**: Automated schedule sync and calendar update
  ([`c88b1f2`](https://github.com/bdperkin/ecu-hockey-calendar/commit/c88b1f2da1d3eeb025ed5476a27063b2b16ca951))

- **schedule**: Automated schedule sync and calendar update
  ([`8310122`](https://github.com/bdperkin/ecu-hockey-calendar/commit/831012279aaf0644797ce83fd65f5261fda6085c))

- **schedule**: Automated schedule sync and calendar update
  ([`dc3b6dc`](https://github.com/bdperkin/ecu-hockey-calendar/commit/dc3b6dc3b2a091ea91097e3dd0e244f713529c48))

- **schedule**: Automated schedule sync and calendar update
  ([`3cc6346`](https://github.com/bdperkin/ecu-hockey-calendar/commit/3cc6346fc022d3e7d638469ad259147bfd2d730e))

- **schedule**: Automated schedule sync and calendar update
  ([`7e570e3`](https://github.com/bdperkin/ecu-hockey-calendar/commit/7e570e39e5aee6233862d3ceb2868bdfda52cd3c))

- **schedule**: Automated schedule sync and calendar update
  ([`0275aef`](https://github.com/bdperkin/ecu-hockey-calendar/commit/0275aefe7658ffbc5c537125ddf1881fdfb3ce05))

- **schedule**: Automated schedule sync and calendar update
  ([`2fa7a75`](https://github.com/bdperkin/ecu-hockey-calendar/commit/2fa7a7548bdf5d61604ac5599e625743c337cdfc))

- **schedule**: Automated schedule sync and calendar update
  ([`bc0f53b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/bc0f53b8f0d2757288c0683f4cfc5aa492c49071))

- **schedule**: Automated schedule sync and calendar update
  ([`4beb884`](https://github.com/bdperkin/ecu-hockey-calendar/commit/4beb884d1b1b21c7a037b3f380bc4c0589f38ea5))

- **schedule**: Automated schedule sync and calendar update
  ([`7104d12`](https://github.com/bdperkin/ecu-hockey-calendar/commit/7104d123925a94161557391539ee867554cf5027))

- **schedule**: Automated schedule sync and calendar update
  ([`2bb5f0b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/2bb5f0bdb3ce090d777255e274f20f7b0120bfff))

- **schedule**: Automated schedule sync and calendar update
  ([`f3fb27b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/f3fb27bb120142b1ed6294e1d32e72607e0a345f))

- **schedule**: Automated schedule sync and calendar update
  ([`f6f7629`](https://github.com/bdperkin/ecu-hockey-calendar/commit/f6f7629aee73479425210da813437f89e9dc3f63))

- **schedule**: Automated schedule sync and calendar update
  ([`b584b21`](https://github.com/bdperkin/ecu-hockey-calendar/commit/b584b212d3fbbcb790b61737f5d153f1e4d88b0c))

- **schedule**: Automated schedule sync and calendar update
  ([`12b26c5`](https://github.com/bdperkin/ecu-hockey-calendar/commit/12b26c5f253baf629bf08aab4d73a7347dc176e9))

- **schedule**: Automated schedule sync and calendar update
  ([`81a5219`](https://github.com/bdperkin/ecu-hockey-calendar/commit/81a52193fa27435ad3ddce2b6fc697189c498421))

- **schedule**: Automated schedule sync and calendar update
  ([`65e418b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/65e418b8b238cbc8f12e2b8c37a5355fe5943c63))

- **schedule**: Automated schedule sync and calendar update
  ([`7498351`](https://github.com/bdperkin/ecu-hockey-calendar/commit/7498351f423af4a342271b66c2c5904f86115cb8))

- **schedule**: Automated schedule sync and calendar update
  ([`4074f26`](https://github.com/bdperkin/ecu-hockey-calendar/commit/4074f26082ecb7f1658380d2db97910a1f2e4511))

### Documentation

- **interfaces**: Comprehensive interface consistency documentation and test suite reconciliation
  ([#177](https://github.com/bdperkin/ecu-hockey-calendar/pull/177),
  [`0c1023f`](https://github.com/bdperkin/ecu-hockey-calendar/commit/0c1023fc084fcf0c3206cbed3fe94f74d2ed8ab8))

- **roadmap**: Track interface consistency phases 9.3 through 9.6 (#168-#171)
  ([#172](https://github.com/bdperkin/ecu-hockey-calendar/pull/172),
  [`ea3b2bb`](https://github.com/bdperkin/ecu-hockey-calendar/commit/ea3b2bb955fb0cae7c2473ee7089f10e441c4494))

### Features

- **api**: Canonical /schedule.* routes, legacy aliases, and query parameter normalization
  ([#173](https://github.com/bdperkin/ecu-hockey-calendar/pull/173),
  [`20daee3`](https://github.com/bdperkin/ecu-hockey-calendar/commit/20daee3d7bf28e9bd55046b3bfde0d54ba53d7ef))

- **branding**: Replace brand logo assets, update social preview, and implement asset generator tool
  (#182) ([#183](https://github.com/bdperkin/ecu-hockey-calendar/pull/183),
  [`40c216c`](https://github.com/bdperkin/ecu-hockey-calendar/commit/40c216c0b1b3a9e6d8f055ce200f1e302d49c00e))

- **cli**: Add --opponents-config flag and OPPONENTS_CONFIG environment override
  ([#204](https://github.com/bdperkin/ecu-hockey-calendar/pull/204),
  [`bbeb9d3`](https://github.com/bdperkin/ecu-hockey-calendar/commit/bbeb9d320d5c962c29acee66b8ea92d5500cc11b))

- **cli**: Add scrape command with minimal, verbose, and debug output modes (#195)
  ([#196](https://github.com/bdperkin/ecu-hockey-calendar/pull/196),
  [`63447d6`](https://github.com/bdperkin/ecu-hockey-calendar/commit/63447d6ef1e9d2e275cce31f05dac577d1ec23cc))

- **cli**: Command parity for health diagnostics, sync subcommands, and conflict options
  ([#176](https://github.com/bdperkin/ecu-hockey-calendar/pull/176),
  [`1d58d4e`](https://github.com/bdperkin/ecu-hockey-calendar/commit/1d58d4eebbdd402a22a1b560286ec5eac67b546c))

- **cli**: Remote HTTP API client integration for operational subcommands (--api-url) (#164)
  ([#165](https://github.com/bdperkin/ecu-hockey-calendar/pull/165),
  [`263e6a0`](https://github.com/bdperkin/ecu-hockey-calendar/commit/263e6a0764882b71bfb3e3282664680758d57533))

- **ingestion**: Create package-bundled verified opponent schedule feeds YAML dataset
  ([#203](https://github.com/bdperkin/ecu-hockey-calendar/pull/203),
  [`4f42d4b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/4f42d4b6f6e38fde314865e2e62623b684dafc3c))

- **ingestion**: Implement ACHA Hockey (achahockey) schedule ingestion scraper
  ([#205](https://github.com/bdperkin/ecu-hockey-calendar/pull/205),
  [`0025150`](https://github.com/bdperkin/ecu-hockey-calendar/commit/002515094adfe48bdd29bf3a39664a96421b176f))

- **ingestion**: Implement YAML configuration loader and schema for opponent schedule feeds
  ([#202](https://github.com/bdperkin/ecu-hockey-calendar/pull/202),
  [`62d1235`](https://github.com/bdperkin/ecu-hockey-calendar/commit/62d1235e286da9521401c149b9ddfe520111cada))

- **sync**: Integrate instagram announcements and opponent verification into sync service
  ([#192](https://github.com/bdperkin/ecu-hockey-calendar/pull/192),
  [`f4cc261`](https://github.com/bdperkin/ecu-hockey-calendar/commit/f4cc261c7254f7e84ad7c8fca8edc0b032270357))

- **ui**: Schedule enhancements, navigation restructuring, branding updates, and NOW divider
  ([#184](https://github.com/bdperkin/ecu-hockey-calendar/pull/184),
  [`2914c41`](https://github.com/bdperkin/ecu-hockey-calendar/commit/2914c411cac342468a440b5d48280e8a2b9fbe23))

- **web**: Clean WebUI dashboard routes (/sync, /conflicts) and /api/v1/health REST parity (#169)
  ([#174](https://github.com/bdperkin/ecu-hockey-calendar/pull/174),
  [`053bdba`](https://github.com/bdperkin/ecu-hockey-calendar/commit/053bdbaf737dba8975d2aab2b40b74f1a1e18d92))


## v0.8.0 (2026-09-14)

### Bug Fixes

- **security**: Resolve CodeQL alert 21 for unused global variable in calendar routes (#162)
  ([#163](https://github.com/bdperkin/ecu-hockey-calendar/pull/163),
  [`caad54e`](https://github.com/bdperkin/ecu-hockey-calendar/commit/caad54e1e00067d03567ebb4fd8eee08887b4d4b))

### Chores

- **deps**: Bump actions/upload-artifact from 4 to 7
  ([#155](https://github.com/bdperkin/ecu-hockey-calendar/pull/155),
  [`4172b6b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/4172b6bf904469c6ea151740629b2f6181278ad1))

- **deps**: Bump docker/build-push-action from 6 to 7
  ([#152](https://github.com/bdperkin/ecu-hockey-calendar/pull/152),
  [`d6dc60e`](https://github.com/bdperkin/ecu-hockey-calendar/commit/d6dc60e86b92c8c0c05291d550ac778708568fec))

- **deps**: Bump docker/login-action from 3 to 4
  ([#150](https://github.com/bdperkin/ecu-hockey-calendar/pull/150),
  [`5329602`](https://github.com/bdperkin/ecu-hockey-calendar/commit/53296028a14c57541f446814a2bc7dd0acd2b7a8))

- **deps**: Bump docker/setup-buildx-action from 3 to 4
  ([#149](https://github.com/bdperkin/ecu-hockey-calendar/pull/149),
  [`cad5824`](https://github.com/bdperkin/ecu-hockey-calendar/commit/cad58249e9e68fbc44cc689ede02b2529f41edd6))

- **deps**: Bump docker/setup-qemu-action from 3 to 4
  ([#153](https://github.com/bdperkin/ecu-hockey-calendar/pull/153),
  [`cbbc961`](https://github.com/bdperkin/ecu-hockey-calendar/commit/cbbc9618e818d8625a2425763fbfafd2d9f9bca5))

- **schedule**: Automated schedule sync and calendar update
  ([`182fefe`](https://github.com/bdperkin/ecu-hockey-calendar/commit/182fefe4b96ea77838484ad39a6e0124da4e0662))

- **schedule**: Automated schedule sync and calendar update
  ([`fe38919`](https://github.com/bdperkin/ecu-hockey-calendar/commit/fe38919a12a6ad65479e1c2e0a45023e2e173553))

- **schedule**: Automated schedule sync and calendar update
  ([`4887c4b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/4887c4bf48995a0b729c4eb3ec3561ac0bf65856))

- **schedule**: Automated schedule sync and calendar update
  ([`56cc0d8`](https://github.com/bdperkin/ecu-hockey-calendar/commit/56cc0d88f067a9e4db150a4d37ca033e5562b4d0))

- **schedule**: Automated schedule sync and calendar update
  ([`42d8785`](https://github.com/bdperkin/ecu-hockey-calendar/commit/42d87856331220ba0982c2bc63ecbf4ec67fae70))

### Documentation

- Comprehensive internal and external documentation audit and reconciliation (#103)
  ([#161](https://github.com/bdperkin/ecu-hockey-calendar/pull/161),
  [`b4248ff`](https://github.com/bdperkin/ecu-hockey-calendar/commit/b4248ff11ba9cdd15d378ca06853ec9ab9690bcc))

- **branding**: Establish project logo and visual brand identity across repository, documentation,
  and web interfaces (#142) ([#159](https://github.com/bdperkin/ecu-hockey-calendar/pull/159),
  [`9918e0c`](https://github.com/bdperkin/ecu-hockey-calendar/commit/9918e0c1bcbfe72b0dd900a2db9a032da30e0316))

### Features

- **syndication**: RSS and Atom XML schedule syndication feeds for media and automation
  ([#158](https://github.com/bdperkin/ecu-hockey-calendar/pull/158),
  [`04fb725`](https://github.com/bdperkin/ecu-hockey-calendar/commit/04fb725f2aed8143206b1af620da0143e0d12bd4))

- **web**: Implement multi-resolution favicons, web app touch icons, and /favicon.ico route (#144)
  ([#160](https://github.com/bdperkin/ecu-hockey-calendar/pull/160),
  [`181b3ee`](https://github.com/bdperkin/ecu-hockey-calendar/commit/181b3ee881c359a332070f2a0f79ad35bad0d97f))


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
