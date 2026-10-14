# Dispute rules for small merchants

This is the knowledge base the triage model retrieves from. Each `##` section is one retrieval chunk and is written to make sense on its own. R0 is general context: it is always given to the model and is not ranked by retrieval. The "Customers often write" lines are generic paraphrases (not taken from eval cases) so rules match the way cardholders describe problems. Section IDs (R0–R7) are what the model cites in its explanation. Evidence is listed using the same IDs as the eval set (`docs/case_schema.md`).

This is a plain-English summary of public Visa and Mastercard merchant guidance (sources in `docs/categories.md`), not scheme rule text. It's for a prototype, not operational advice.

## R0 · How disputes and time limits work

A dispute (chargeback) starts when a cardholder asks their bank to reverse a card payment. The bank chooses a reason, the money is taken back from the merchant, and the merchant can respond with evidence through their payment provider.

**Cardholder time limit:** usually 120 days from the transaction date. When goods or a service were due later, the 120 days run from the expected delivery or service date, up to a maximum of 540 days after the transaction.

**Merchant time limit:** the card schemes give the merchant's provider about 30 days (Visa) or 45 days (Mastercard) to respond. Providers then set their own, shorter deadlines for the merchant, often 7–21 days. **The provider's deadline is the one that counts.** If it's missed, the merchant loses the dispute automatically.

**General advice:** respond to the claim the cardholder is actually making, not every possible claim. Send short, relevant, legible evidence. If the cardholder is right, accepting the dispute or refunding is often cheaper than fighting it.

## R1 · fraud_unauthorised: "I didn't make this purchase"

**Applies when:** the cardholder says they didn't make or authorise the payment. They may not recognise the merchant, say their card was lost or stolen, or say someone else used it.

**Customers often write:** "I don't recognise this payment", "I never bought this", "my card was lost or stolen", "someone has used my card", "I've never heard of this company", "my child bought this without asking".

**Not this if:** they recognise the purchase but were charged the wrong amount or twice (R6), or they ordered something that didn't arrive (R2). "I don't recognise this" sometimes just means an unclear name on the statement.

**Evidence that wins:**
- `auth_3ds`: the payment passed 3-D Secure (bank verification). This is often the strongest single item for online sales.
- `avs_cvv_match`: address and security code matched.
- `device_ip_history` and `prior_undisputed_orders`: the same device or IP address was used for earlier orders that weren't disputed. Visa's "compelling evidence" rules give weight to two or more such orders from 120–365 days before.
- `account_activity`: the customer's account was logged into and used.
- `proof_of_delivery` (physical goods) or `digital_access_logs` (digital goods): delivered to the cardholder's address, or used from their account.

**Family use:** if a family member made the purchase with the cardholder's device or account, the evidence above usually shows that. It's still a fraud claim until proven otherwise.

**Card present (in person):** the merchant has little to offer beyond chip/PIN or contactless transaction records. Lost-card contactless fraud is usually hard to defend.

## R2 · not_received: "I paid but never got it"

**Applies when:** goods never arrived, digital goods or tickets were never delivered, or a booked service never happened (no-show, event cancelled with nothing provided).

**Customers often write:** "it never came", "still waiting for my order", "nobody turned up", "the appointment never happened", "the tickets or code were never sent", "tracking hasn't moved", "they keep rescheduling".

**Not this if:** something arrived but was wrong, damaged or incomplete (R3). Test: if the customer never received or used what they paid for, it's R2, even if the merchant changed the date or offered an alternative the customer didn't take. If the customer was charged but no order was ever created (e.g. "it said declined"), see R6.

**Evidence that wins:**
- `proof_of_delivery`: carrier confirmation of delivery or collection, ideally with a signature, photo or GPS location matching the cardholder's address.
- `tracking_expected_date`: the order is still within its stated delivery window. The dispute is early.
- `digital_access_logs`: tickets, downloads or accounts were emailed, accessed or used.
- `service_provided_proof`: the appointment or service actually took place (booking records, staff logs, photos).
- `invoice_or_contract`: what delivery or service date was agreed.

**Timing:** the cardholder's 120-day window starts from the expected delivery or service date, so late disputes about delayed orders can still be valid.

## R3 · not_as_described: "It's broken, fake, or not what I paid for"

**Applies when:** goods or a service were provided but were defective, damaged, counterfeit, the wrong item, incomplete, poor quality, or materially different from the description or agreement. This includes a service done badly or only partly done.

**Customers often write:** "it's broken / faulty / damaged", "it's fake", "not like the pictures", "wrong size, colour or item", "bits are missing", "they did a bad job", "the service was poor or only half done", "it isn't what we agreed".

**Not this if:** nothing arrived at all, or the customer never used the service because it was cancelled or moved (R2), or the customer has already returned the item or cancelled and is now waiting for a promised refund (R5).

**Evidence that wins:**
- `product_listing`: the description, photos and specification exactly as shown at checkout.
- `invoice_or_contract`: what was ordered or agreed (size, colour, quantity, prescription, scope of work).
- `replacement_offer`: a repair, replacement, redo or partial refund was offered or accepted. This shows the merchant tried to put it right.
- `return_cancellation_policy`: the return process the customer was told about, and whether they followed it.
- `customer_communications`: only when the messages matter, e.g. the customer accepted a fix or admitted the item matched.

**Note:** quality complaints are judged on whether the item matched what was promised, not on taste. "A different colour from the one ordered" is a mismatch. "I didn't like it" usually isn't.

## R4 · subscription_cancelled: "I cancelled but was charged again"

**Applies when:** a recurring payment (subscription, membership, rental, regular plan) was taken after the cardholder says they cancelled or ended the agreement.

**Customers often write:** "I cancelled my subscription but they're still charging me", "they took another monthly payment", "my free trial turned into a payment", "I ended the contract but they kept billing".

**Not this if:** it was a one-off purchase or booking that was cancelled (R5), or a second one-off charge the customer doesn't recognise (R6 or R1).

**Evidence that wins:**
- `subscription_terms`: the recurring amount, billing date and how to cancel, as clearly shown at sign-up.
- `cancellation_log`: when and how the customer cancelled, or proof that no cancellation request was received.
- `post_cancellation_usage` or `account_activity`: the customer kept using the service after the date they say they cancelled. Visa accepts this as evidence from October 2024.
- `terms_acceptance`: the customer agreed to the recurring terms, including any free trial that converts to paid.
- `refund_issued_proof`: the disputed charge has already been refunded.

**Note:** if the customer shows a cancellation confirmation and there's no later usage, the merchant will usually lose and should refund.

## R5 · refund_not_processed: "I returned it or cancelled, and no refund came"

**Applies when:** the customer returned goods, cancelled an order or booking, or was promised a refund (full or partial), and the money hasn't arrived.

**Customers often write:** "I sent it back and haven't had my money", "they promised a refund", "I cancelled and want my money back", "refund still pending", "still waiting for my deposit".

**Not this if:** the complaint is about the item itself and nothing was returned or cancelled (R3), or it's about a recurring charge after cancelling (R4).

**Evidence that wins:**
- `refund_issued_proof`: the refund was already issued, with the amount and date. This usually ends the dispute.
- `return_cancellation_policy`: the policy as shown at checkout (notice periods, non-refundable deposits, return windows).
- `return_not_received`: the returned item never arrived, or arrived outside the return window or in a condition the policy excludes.
- `terms_acceptance`: the customer agreed to those terms.
- `cancellation_log`: when the cancellation actually happened, compared with the notice period.

**Note:** if the merchant confirmed in writing that a refund was due, it should refund rather than fight.

## R6 · processing_error: "I was charged wrongly"

**Applies when:** the payment itself went wrong. This covers:
- a duplicate charge
- the wrong amount
- the wrong currency
- a charge submitted very late (weeks or months after the purchase)
- the customer already paid another way (cash, voucher, insurer)
- the card was "declined" or "payment failed", but money was taken anyway

**Customers often write:** "I've been charged twice", "the amount is wrong", "more than my receipt", "charged in the wrong currency", "I paid another way", "it said declined but the money still left my account", "this charge turned up months later".

**Not this if:** the customer denies making any purchase (R1), or the amount is right but they're unhappy with what they got (R3).

**Evidence that wins:**
- `transaction_records`: settlement or batch logs showing two separate purchases, or that only one charge settled.
- `itemised_receipt`: the receipt matches the amount charged.
- `currency_disclosure`: the customer was shown and accepted the currency, or the conversion offer.
- `single_payment_proof`: the card was the only payment used for that purchase.
- `authorisation_record`: an approval code and timestamp show the payment was authorised.
- `timely_presentment_proof`: the charge was submitted within the allowed time.

**Watch for:** a pending authorisation next to a settled charge often looks like a duplicate but isn't one. Check the settlement records first.

## R7 · unclear: when to send a case to a person

Use `unclear` when the complaint is too vague to classify, when two categories fit equally well, or when the evidence needed depends on facts the complaint doesn't give (e.g. "I can't remember if it was a subscription").

**Action:** send the case to human review with the two most likely categories and the question that would settle it, e.g. "Was the item returned?" Don't recommend evidence for a category you aren't confident in. Wrong evidence wastes the merchant's limited time to respond.
