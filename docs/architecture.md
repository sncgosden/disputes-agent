# Architecture

How a dispute moves from a provider event to a reviewed, approved action, and which component owns each decision. Components marked **built** exist and are tested; **specified** components are designed with acceptance checks but not yet implemented.

## System overview

```mermaid
flowchart TB
    subgraph Provider["Stripe (test mode)"]
        EV[Signed dispute events]
        API[Dispute API: read, stage, submit]
    end

    subgraph Integration["Integration layer — built"]
        RX[Webhook receiver<br/>verify signature, persist once]
        PR[Event processor<br/>fetch current dispute state]
        CS[(Case and event store)]
    end

    subgraph Agent["Agent — specified"]
        CO[Coordinator<br/>plan, choose next action, stop]
        SP[Specialists, only if measured gains justify them<br/>evidence · rules · response · review]
        CX[Context builder<br/>budgeted, source IDs preserved]
    end

    subgraph Tools["Tool layer — code enforces scope"]
        GC[get_case — built<br/>merchant-scoped, untrusted text wrapped]
        SR[search_records, get_record — specified]
        GS[Guidance search and verify — built<br/>applicability filters, captured-bytes citations]
        WR[save_plan, add_task, save_draft, request_information — specified]
    end

    subgraph Data["Data"]
        MR[(Merchant records<br/>frozen 18-case evaluation set)]
        GC2[(Guidance corpus<br/>11 official sources, hashed)]
    end

    subgraph Control["Control — built"]
        RD[Readiness checks]
        AP[Approval bound to exact payload hash<br/>named reviewer, expiry, single use]
        HU([Merchant reviewer])
    end

    EV --> RX --> CS
    CS --> PR
    PR -- "event is a trigger, not truth" --> API
    PR --> CO
    CO <--> CX
    CO --> SP
    CO -- tool calls --> GC & SR & GS & WR
    SP -- tool calls --> GC & SR & GS
    GC & SR --> MR
    GS --> GC2
    WR --> CS
    CO -- proposes ready --> RD
    RD -- pass --> HU
    RD -- fail: repair or wait --> CO
    HU -- approves hash --> AP
    AP -- "stage submit=false, then submit once" --> API
```

## What each arrow guarantees

| From → to | Guarantee | Status |
|---|---|---|
| Stripe events → receiver | Signature verified; each event stored once by ID; acknowledged even when a duplicate | Built |
| Processor → Stripe API | Current dispute state is fetched for every event, so order and duplicates cannot roll a case back | Built |
| Coordinator → tools | Every call carries the merchant and case; tools reject other merchants, malformed IDs and arguments outside their schema | Built for `get_case`; specified for the rest |
| Tools → merchant records | Customer, carrier and complaint text arrives labelled as external content, never as instructions | Built |
| Guidance → coordinator | Passages are filtered by network, source type and reason code before ranking; every citation is checked against the captured bytes | Built |
| Coordinator → readiness | The model may propose "ready"; code checks sources, claims, conflicts and required fields | Specified |
| Reviewer → approval | Approval names a person and the exact payload hash, expires and is consumed on use | Built |
| Approval → Stripe | Evidence is staged with `submit=false`; submission is a separate approved call with a stable idempotency key, confirmed by reading the provider afterwards | Built |

## Case lifecycle

```mermaid
stateDiagram-v2
    [*] --> Investigating: dispute event
    Investigating --> Waiting: an obtainable record would decide the case
    Waiting --> Investigating: record or answer arrives (released once)
    Investigating --> Escalated: a person can resolve what the records cannot
    Investigating --> ReadyForReview: readiness checks pass
    ReadyForReview --> Investigating: new evidence or provider change
    ReadyForReview --> Approved: reviewer approves exact payload
    Approved --> Submitted: single submission, provider confirms
    Escalated --> Investigating: reviewer supplies a resolution
    Submitted --> [*]
```

## Design principles

- **Judgement where context changes the answer; code everywhere else.** See [agency boundary](agency-boundary.md).
- **Provider state over event content.** Events wake the system; the provider's current object decides.
- **Least privilege over clever prompting.** No tool can export data, message customers, refund or approve. An injected instruction has nothing to call.
- **Complexity earns its place.** A fixed checklist and a single agent are evaluated on the frozen case set before any specialist is added; a specialist stays only if it improves correctness or effort enough to cover its cost and latency.
- **Everything versioned.** API version pinned, guidance content-hashed, dataset frozen, results stamped with corpus and dataset versions.
