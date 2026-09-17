"""Mapping des 77 labels Banking77 : id -> nom -> description.

Module commun, importe A L'IDENTIQUE par run_jev.py et run_frontier.py.
Ni l'ordre des options ni la formulation des criteres ne doivent differer
entre les deux runners : c'est le point de rupture le plus probable de la
comparaison. Tout changement ici deplace le prompt_hash des deux runs.

- `id`          : index du ClassLabel du dataset d'origine (dataset_infos.json),
                  qui fixe aussi l'ordre des options envoyees.
- `name`        : label verbatim, y compris ses bizarreries -- `Refund_not_showing_up`
                  porte une majuscule et `reverted_card_payment?` un point
                  d'interrogation dans le dataset d'origine. Aucune normalisation :
                  c'est la chaine comparee au gold.
- `description` : critere envoye au modele. Les descriptions sont vues par le
                  modele, contrairement a l'id de question. Les paires reellement
                  confondables portent une clause "Not:" qui nomme la voisine.

Pas d'option `other` : Banking77 est un probleme ferme, voir docs/METHOD.md.
"""

INSTRUCTIONS = "Which banking intent does this customer query express?"

LABELS: tuple[tuple[int, str, str], ...] = (
    (0, "activate_my_card", "Activating a newly received card before first use."),
    (1, "age_limit", "Minimum age to open or use an account, or opening one for a minor."),
    (2, "apple_pay_or_google_pay", "Using the card with Apple Pay, Google Pay or another mobile wallet."),
    (3, "atm_support", "Which ATMs or cash machines can be used, and whether the card works in them."),
    (4, "automatic_top_up", "Setting up or changing automatic, recurring top-ups."),
    (5, "balance_not_updated_after_bank_transfer", "Money sent in by bank transfer has not appeared in the balance yet."),
    (6, "balance_not_updated_after_cheque_or_cash_deposit", "A cheque or cash deposit has not appeared in the balance yet."),
    (7, "beneficiary_not_allowed", "A payment or transfer was blocked because the payee or beneficiary is not allowed."),
    (8, "cancel_transfer", "Cancelling or reversing a transfer that has already been sent."),
    (9, "card_about_to_expire", "The card expires soon and a replacement is needed."),
    (10, "card_acceptance", "Where the card is accepted: which shops, merchants or sites take it."),
    (11, "card_arrival", "Chasing a card that was already ordered and has not arrived. Not: how long delivery takes in general (card_delivery_estimate)."),
    (12, "card_delivery_estimate", "How long card delivery takes in general. Not: chasing a specific card that is late (card_arrival)."),
    (13, "card_linking", "Linking or adding an existing external card to the account."),
    (14, "card_not_working", "A physical card does not work at all. Not: one declined payment (declined_card_payment), nor contactless alone (contactless_not_working)."),
    (15, "card_payment_fee_charged", "A fee was charged on a card payment."),
    (16, "card_payment_not_recognised", "An unrecognised card payment appears on the statement."),
    (17, "card_payment_wrong_exchange_rate", "A card payment was converted at what looks like the wrong exchange rate."),
    (18, "card_swallowed", "An ATM retained or swallowed the card."),
    (19, "cash_withdrawal_charge", "A fee was charged for withdrawing cash."),
    (20, "cash_withdrawal_not_recognised", "An unrecognised cash withdrawal appears on the statement."),
    (21, "change_pin", "Changing or resetting the card PIN. Not: the app passcode (passcode_forgotten)."),
    (22, "compromised_card", "The card may have been cloned, skimmed or its details stolen."),
    (23, "contactless_not_working", "Contactless or tap payments specifically do not work."),
    (24, "country_support", "Whether the service is available in a given country or to its residents."),
    (25, "declined_card_payment", "A specific card payment was declined, and why."),
    (26, "declined_cash_withdrawal", "A specific cash withdrawal was declined, and why."),
    (27, "declined_transfer", "A specific transfer was declined, and why."),
    (28, "direct_debit_payment_not_recognised", "An unrecognised direct debit appears on the account."),
    (29, "disposable_card_limits", "Limits that apply to disposable virtual cards."),
    (30, "edit_personal_details", "Changing personal details: name, address, phone number or email."),
    (31, "exchange_charge", "A fee charged on a currency exchange."),
    (32, "exchange_rate", "Which exchange rate applies, or how the rate is set. Not: a rate that looks wrong on a payment (card_payment_wrong_exchange_rate)."),
    (33, "exchange_via_app", "How to exchange or convert currency in the app."),
    (34, "extra_charge_on_statement", "An extra or unexpected charge on the statement, of unclear origin."),
    (35, "failed_transfer", "A transfer failed or did not go through."),
    (36, "fiat_currency_support", "Which traditional currencies can be held or exchanged."),
    (37, "get_disposable_virtual_card", "Obtaining a single-use disposable virtual card."),
    (38, "get_physical_card", "Whether a physical card is available at all, and how to obtain one. Not: placing the order itself (order_physical_card)."),
    (39, "getting_spare_card", "Getting an additional or spare card alongside an existing one."),
    (40, "getting_virtual_card", "Obtaining a virtual card. Not: a single-use disposable one (get_disposable_virtual_card)."),
    (41, "lost_or_stolen_card", "The card has been lost or stolen."),
    (42, "lost_or_stolen_phone", "The phone has been lost or stolen, and app access with it."),
    (43, "order_physical_card", "Placing an order for a physical card. Not: whether one is available at all (get_physical_card)."),
    (44, "passcode_forgotten", "The app passcode or password was forgotten. Not: the card PIN (change_pin)."),
    (45, "pending_card_payment", "A card payment is showing as pending."),
    (46, "pending_cash_withdrawal", "A cash withdrawal is showing as pending."),
    (47, "pending_top_up", "A top-up is showing as pending."),
    (48, "pending_transfer", "A transfer is showing as pending."),
    (49, "pin_blocked", "The PIN is blocked, typically after wrong attempts."),
    (50, "receiving_money", "Receiving money from someone else, and how they can send it."),
    (51, "Refund_not_showing_up", "A refund already agreed or issued has not appeared. Not: asking for one in the first place (request_refund)."),
    (52, "request_refund", "Asking for a refund or for money back."),
    (53, "reverted_card_payment?", "A card payment was reverted and the money returned."),
    (54, "supported_cards_and_currencies", "Which card types and currencies are supported."),
    (55, "terminate_account", "Closing or terminating the account."),
    (56, "top_up_by_bank_transfer_charge", "A fee charged when topping up by bank transfer."),
    (57, "top_up_by_card_charge", "A fee charged when topping up by card."),
    (58, "top_up_by_cash_or_cheque", "Topping up with cash or a cheque."),
    (59, "top_up_failed", "A top-up failed or did not go through."),
    (60, "top_up_limits", "Limits on how much or how often the account can be topped up."),
    (61, "top_up_reverted", "A top-up was reverted and the money returned."),
    (62, "topping_up_by_card", "Topping up using a card. Not: the fee charged for it (top_up_by_card_charge)."),
    (63, "transaction_charged_twice", "The same transaction was charged twice."),
    (64, "transfer_fee_charged", "A fee was charged on a transfer."),
    (65, "transfer_into_account", "Moving money into this account from another bank or account."),
    (66, "transfer_not_received_by_recipient", "A transfer was sent but the recipient has not received it."),
    (67, "transfer_timing", "How long a transfer takes to arrive."),
    (68, "unable_to_verify_identity", "Identity verification was attempted and failed or cannot be completed."),
    (69, "verify_my_identity", "How to carry out identity verification. Not: it failing (unable_to_verify_identity), nor why it is required (why_verify_identity)."),
    (70, "verify_source_of_funds", "Verifying where the money came from."),
    (71, "verify_top_up", "Verifying a top-up or the card used to make it."),
    (72, "virtual_card_not_working", "A virtual card does not work."),
    (73, "visa_or_mastercard", "Whether the card is a Visa or a Mastercard, or asking for one specifically."),
    (74, "why_verify_identity", "Why identity verification is required at all."),
    (75, "wrong_amount_of_cash_received", "An ATM dispensed the wrong amount of cash."),
    (76, "wrong_exchange_rate_for_cash_withdrawal", "A cash withdrawal was converted at what looks like the wrong exchange rate."),
)

LABEL_NAMES: tuple[str, ...] = tuple(name for _, name, _ in LABELS)

# dict ordonne par id : l'ordre d'insertion est l'ordre des options envoyees,
# et il entre dans le prompt_hash.
CRITERIA: dict[str, str] = {name: description for _, name, description in LABELS}

assert len(LABELS) == 77, len(LABELS)
assert len(CRITERIA) == 77, "noms de labels dupliques"
assert [i for i, _, _ in LABELS] == list(range(77)), "ids non contigus ou mal tries"
