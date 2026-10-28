# O-Plates runtime architecture — October 28, 2026

This is an observed snapshot, not a deployment instruction. Render service configured branches can differ from their explicitly deployed commit. Production automatic deployment is off.

| Component | Render service | Configured branch | Observed deployed commit |
| --- | --- | --- | --- |
| Public landing | landing page / srv-d5eqjn6r433s738u2jn0 | main | 45ee4dc58ac9c2556a1b891c30512fa1eb28fe04 |
| Customer configurator/account/cart | orifice-pricing-engine / srv-d530k8re5dus73ahqr0g | work/final-integration-production-cutover | 717bf7e04e4972a410712fd2c57e45c1a18bbc09 |
| Pricing/checkout/manufacturing API | orifice-pricing-api / srv-d51l6ch5pdvs73ealnh0 | work/final-integration-production-cutover | c002fe848249dfa8e805265614cec5091de38a5a |
| Dedicated owner control | oplates-manufacturing-control / srv-db9mhf3ncjis739t3e80 | work/final-integration-production-cutover | c002fe848249dfa8e805265614cec5091de38a5a |
| Suspended staging API/UI | oplates-pricing-api-staging / oplates-customer-ui-staging | work/customer-journey | a50ed6d3a97997f94ec2258b8d7589651a95b3a2 |
| Staging static landing | oplates-landing-page-staging | work/customer-journey | a50ed6d3a97997f94ec2258b8d7589651a95b3a2 |

www.o-plates.com embeds quote.o-plates.com/Quote; the customer UI calls the existing pricing API. The owner app uses the API for pricing, orders, Frozen Plates, derived engineering downloads and analytics. The runtime API contains both database-backed pricing and restricted Supabase/Frozen Plate storage/authentication dependencies; preserve both database systems and all private artifacts.

main is 71267b6c10dbf21c301f03f97b715a9595684d64 before this docs-only housekeeping. The production integration branch is 911dfe7dc919ff342bac13580a8224a254cda10d (#52 merged). Do not deploy branch HEAD merely because it is newer. #50 is deployed to API/owner control; #51 merged into review/staging-deployed-64d3b70, not the staging runtime; #52 includes the switch but is not deployed. Main retains legacy security/pricing fallback changes not all reachable from integration.

## Protected adjacent projects and recovery

- roguemach-design/flex400 → Render flex400, main, deployed e786084bbf2d85b9cb4f6f3ba56ea981cd03c50f.
- roguemach-design/bushingbuilder → bushingbuilder-staging, work/phase1-landing-configurator, deployed f4a588bdd264190c5a95fada1505544d75f3f941.
- roguemach-design/rogue-gsc-readonly supplies independent Rogue/O-Plates read-only GSC services; preserve active integrations even though outside pricing PRs.
- Legacy secured administration, owner-acceptance API/UI and TEST webhook ingress can carry recovery or provider dependencies. Do not remove based on age or names.
- Render production/staging/owner-test Postgres databases are protected. Staging remains suspended. No database, disk, Supabase data/bucket/migration/backup deletion is authorized here.

The audit changed no runtime settings, checkout state, secrets, manufacturing records or feature code. Physical manufacturing acceptance, payment acceptance and Supabase availability are separate from an HTTP health response.
