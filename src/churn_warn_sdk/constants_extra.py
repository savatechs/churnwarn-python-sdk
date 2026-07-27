"""Payload field names, account-attribute keys, and business-type keys.

Mirror sdks/signals.manifest.json (payloadFields / accountAttributes / businessTypes).
"""


class PayloadFields:
    """Numeric/dimension payload keys read by sum_payload / avg_payload and the marketplace side split."""

    VALUE = "value"
    SIDE = "side"
    QUANTITY = "quantity"


class AccountAttributes:
    """Slow-changing account facts set via upsert_account() → PUT /api/accounts."""

    DIRECT_DEPOSIT = "direct_deposit"
    KYC_COMPLETED = "kyc_completed"
    PUSH_OPT_IN = "push_opt_in"
    INSTALLED_AT = "installed_at"


class BusinessTypes:
    """Dashboard-template / business-type keys (mirror backend DashboardTemplateCatalog.BusinessTypes)."""

    B2B_SAAS_SALESLED = "b2b_saas_salesled"
    B2B_SAAS_PLG = "b2b_saas_plg"
    INTERNAL_TOOL = "internal_tool"
    ECOMMERCE = "ecommerce"
    FINTECH = "fintech"
    SUBSCRIPTION_BOX = "subscription_box"
    MOBILE = "mobile"
    MARKETPLACE_BUYER = "marketplace_buyer"
    MARKETPLACE_SELLER = "marketplace_seller"


VALUE_BASES = ("mrr", "arr", "ltv", "balance", "gmv", "none")
ACCOUNT_ROLES = ("buyer", "seller")
