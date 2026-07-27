"""Canonical metric keys (mirror backend DefaultDashboardMetricKeys.All / sdks/signals.manifest.json)."""

# Core (SaaS / PLG)
LOGIN = "login"
SESSION = "session"
FEATURE_USED = "feature_used"
SEAT_USED = "seat_used"
SEAT_PURCHASED = "seat_purchased"
ACTIVE_USER = "active_user"
ONBOARDING_COMPLETED = "onboarding_completed"
SUPPORT_TICKET_OPENED = "support_ticket_opened"
SUPPORT_TICKET_RESOLVED = "support_ticket_resolved"
SUPPORT_TICKET_NEGATIVE = "support_ticket_negative"
NPS_RESPONSE = "nps_response"
CSAT_RESPONSE = "csat_response"
SEAT_EXPANDED = "seat_expanded"
PLAN_UPGRADED = "plan_upgraded"
REFERRAL = "referral"
FRUSTRATION_SCORE = "frustration_score"
ERROR_RATE = "error_rate"

# E-commerce / RFM
ORDER_PLACED = "order_placed"
CART_CREATED = "cart_created"
CART_ABANDONED = "cart_abandoned"
PRODUCT_VIEWED = "product_viewed"
ORDER_RETURNED = "order_returned"

# Fintech / neobank
CARD_TRANSACTION = "card_transaction"
BILL_PAY = "bill_pay"
TRANSACTION_DECLINED = "transaction_declined"

# Subscription-box
SUBSCRIPTION_SKIPPED = "subscription_skipped"
SUBSCRIPTION_PAUSED = "subscription_paused"
SUBSCRIPTION_RESUMED = "subscription_resumed"
PAYMENT_FAILED = "payment_failed"
DELIVERY_ISSUE = "delivery_issue"

# Mobile consumer app
APP_OPEN = "app_open"
APP_INSTALLED = "app_installed"
APP_UNINSTALLED = "app_uninstalled"
PUSH_ENABLED = "push_enabled"
PUSH_OPENED = "push_opened"
IAP_PURCHASE = "iap_purchase"
PAYWALL_VIEW = "paywall_view"

# Marketplace (two-sided)
TRANSACTION = "transaction"
SEARCH_PERFORMED = "search_performed"
LISTING_CREATED = "listing_created"
TRANSACTION_REQUEST = "transaction_request"
