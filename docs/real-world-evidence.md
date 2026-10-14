# Real-world evidence requirements

## Product direction

Stripe's test environment becomes the payment system of record. Published provider and scheme guidance becomes the retrieval corpus. Seeded scenarios generate deliberately imperfect merchant records. Two published first-person merchant accounts inform the workflow and scenario design through desk research; participant outreach was out of scope for this phase.

The earlier triage data, rule summaries and model outputs remain baseline references. They do not establish payment integration, merchant-record investigation or customer demand.

## Four-part completion checkpoint

| Requirement | Evidence required before progression | Current evidence |
| --- | --- | --- |
| Stripe integration | Test account connection; actual payment/dispute IDs; verified webhook signature; persisted provider deadline; event replay handling; staged evidence; exact approved submission; retrieved outcome. | Complete: account and API version verified; 3 genuine disputes; signed webhooks; provider deadline; duplicate, out-of-order and missed-event recovery; staging with submit=false; hash-bound expiring approval; one submission each; won and lost outcomes; Visa CE 3.0 eligible and ineligible cases observed. |
| Published-source retrieval | Captured official source bytes, URLs, timestamps and hashes; page/section-linked chunks; executed searches; citation and freshness checks; recorded retrieval results. | Complete: 11 official sources captured with hashes (4,134 passages); printed-page and reason-code metadata; applicability filters; 10 reviewed relevance labels; citation integrity checks (7/7); refresh comparison; baseline retrieval score saved (4/10 found in top 5). |
| Messy merchant records | Seeded generated records with mismatch, timezone, missing-scan, contradictory-message, partial-refund, duplicate-profile and injection cases; separate private truth; late events; blind labels and reproducibility checks. | Complete: 18 cases in 9 contrast pairs, frozen and reproducible from seed (generator v6); private answers and late events; leakage, chronology, late-event (6/6) and injection/merchant-boundary (6/6) checks; blind human labels (5/7 independent agreement) with reviewed disagreements. |
| Published merchant input | Two dated first-person public accounts, linked sources, paraphrases and limitations; workflow details linked to dataset and product changes. | Complete with limits: account 1 re-read and confirmed; account 2 not retrievable and treated as weaker evidence. Both linked to scenarios and product decisions. Not interviews; no demand claim. |

The checkpoint is complete only when all four have evidence. A generated interview transcript, written integration or source list does not pass the checkpoint.

## Checkpoint result

All four foundations have executed evidence (6 October 2026). Agent development can proceed against them. What the checkpoint does **not** establish: agent quality, production accuracy, real merchant demand or willingness to pay. The baseline retrieval score (4/10) and the always-respond baselines (8 of 18 decisions now; 12 of 18 final recommendations) are the bars the agent must beat.

## Stripe implementation decisions

- Use test API keys only and reject live-mode objects. Store provider IDs and returned API version with the integration record.
- Use documented test PaymentMethods in code rather than collecting raw card details.
- Read the supplied `evidence_details.due_by` timestamp. Do not invent a deadline or assume Stripe's dispute reason is a card-network reason code.
- Verify the raw webhook body using the signing secret. Persist each event before acknowledging it; deduplicate by event ID and retrieve current provider state when processing.
- Stage evidence with an explicit `submit=false`. Submission requires an approved hash of the exact evidence payload and an explicit `submit=true`.
- Retain an idempotency key for the approved action. After uncertain execution, reconcile provider state before further action.
- Test outcome control strings exercise Stripe's test lifecycle. They are kept separate from agent-generated evidence and are not evidence of dispute win rate or recommendation quality.

## Research integrity

The chosen method is desk research over published merchant accounts. Notes distinguish reported events from interpretation and preserve the source links and access limitations. No participants were contacted and no merchant responses were generated.

Two published accounts inform initial product choices; they do not establish market-wide demand or willingness to pay. Scenario generation remains explicit even when informed by real workflow details. See [Merchant workflow evidence](merchant-desk-research.md) for the observations and resulting decisions.

## Published sources checked on 6 October 2026

- [Stripe testing](https://docs.stripe.com/testing): test PaymentMethods and controlled outcome values.
- [Stripe dispute object](https://docs.stripe.com/api/disputes/object): provider fields and evidence deadline.
- [Stripe dispute update](https://docs.stripe.com/api/disputes/update): staging and submission API.
- [Stripe responding to disputes](https://docs.stripe.com/disputes/responding): submission finality and response workflow.
- [Stripe webhooks](https://docs.stripe.com/webhooks): signatures, duplicate delivery and ordering.
- [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests): retry semantics.
- [Stripe Visa CE3 API](https://docs.stripe.com/disputes/api/visa-ce3): eligible-dispute evidence structure.
- [Visa merchant dispute guidelines](https://www.visa.ie/content/dam/VCOM/global/support-legal/documents/merchants-dispute-management-guidelines.pdf): published scheme guidance; capture the document edition when ingesting.
- [Mastercard Chargeback Guide](https://www.mastercard.com/content/dam/mccom/shared/business/support/rules-pdfs/chargeback-guide.pdf): merchant edition dated 27 January 2026 when checked; capture fetched bytes rather than assuming the URL remains unchanged.
