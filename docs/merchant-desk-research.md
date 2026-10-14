# Merchant workflow evidence

## Research method

Two public first-person merchant accounts provide initial workflow evidence. These are published accounts inspected on 6 October 2026, not interviews conducted by this project. The authors' identities, financial records and causal interpretations have not been independently verified. They inform case design rather than establish demand or Stripe-specific behaviour.

## Account 1: overlapping refund and dispute

The author of a [Shopify Community post dated 19 March 2022](https://community.shopify.com/t/how-can-i-handle-chargeback-fraud-after-a-partial-refund/107850) describes a partial refund, a later return and a chargeback for the original total. They report assembling a timeline and difficulty reconciling the amounts.

Re-read on 6 October 2026: a two-item order of $500 and $400; the $500 item was cancelled and refunded; the $400 item shipped, was later returned as defective, and a chargeback for the full $900 was filed the day the return arrived. The author reports the bank found for the customer, leaving the merchant $1,400 out of pocket on a $900 order: "it should only $400, not $900".

**Product decision:** distinguish order value, disputed amount, completed refunds and remaining balance. When they do not reconcile, request the provider's refund ledger before recommending anything; escalate only if the ledger still leaves the amount owed unresolved. Never assume fraud or recommend another refund.

**Value implication:** a single overlap of this kind cost more than the order itself. Amount reconciliation is a direct loss-prevention feature, not a reporting detail.

**Dataset change:** the `partial_refund_overlap` scenario includes an item-level cancellation, a refund record smaller than the original payment, a returned item and a dispute spanning the original amount.

## Account 2: status changes while waiting

In a [Reddit post dated 16 March 2025](https://www.reddit.com/r/shopify/comments/1jcavlm/), the author reports uploading evidence, waiting for a customer reply and then receiving a favourable outcome notification. They are unsure whether customer withdrawal caused it. The original post appeared in search results; the page itself could not be retrieved at capture or on re-check (6 October 2026). This account is therefore weaker evidence than the first, and the scenario it informs also rests on Stripe's documented dispute lifecycle rather than on the account alone.

**Product decision:** staged, submitted and resolved are distinct provider states. A new outcome must cause a fresh provider read and reconsideration of pending actions. The agent must not infer a withdrawal or attribute a win to its evidence without support.

**Dataset change:** the `late_provider_status` scenario receives a late status event while a clarification is open. An earlier submission proposal becomes obsolete.

## What changed

Refund reconciliation and late status events become first-class investigation cases. Preparation and submission are tracked separately. The initial segment remains small online retailers because both accounts describe fulfilment, customer communication and payment-resolution work; they do not validate the size of the opportunity or willingness to pay.

Published accounts can expose workflow details without participant outreach. Direct discovery remains a separate future research method, not a completed activity claimed here.
