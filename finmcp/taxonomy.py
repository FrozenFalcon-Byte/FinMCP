"""Category taxonomy: names, kinds, default monthly budgets (INR) and matching keywords."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .db.repository import Repository


@dataclass(frozen=True)
class CategorySpec:
    name: str
    kind: str
    budget_limit: float | None
    description: str
    keywords: tuple[str, ...] = field(default_factory=tuple)


DEFAULT_CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec("Food & Dining", "expense", 8000, "Restaurants, food delivery, cafes, takeaway",
                 ("swiggy", "zomato", "restaurant", "cafe", "coffee", "starbucks", "third wave", "blue tokai", "pizza", "dominos",
                  "mcdonald", "kfc", "burger", "biryani", "dhaba", "eatsure", "eat", "dining", "food", "bakery", "chai", "bbk")),
    CategorySpec("Groceries", "expense", 12000, "Supermarkets, quick commerce, kirana",
                 ("blinkit", "zepto", "bigbasket", "big basket", "dmart", "avenue supermarts", "instamart", "reliance fresh",
                  "grofers", "more supermarket", "kirana", "grocery", "groceries", "supermarket", "nature's basket", "milk basket")),
    CategorySpec("Transport", "expense", 4000, "Cabs, autos, metro, trains, fuel, tolls, parking",
                 ("uber", "ola", "rapido", "metro", "bmrcl", "dmrc", "irctc", "redbus", "petrol", "fuel", "diesel", "hp petrol",
                  "indian oil", "iocl", "bpcl", "hpcl", "fastag", "parking", "toll", "namma yatri", "auto")),
    CategorySpec("Shopping", "expense", 6000, "Online and offline retail, clothes, electronics",
                 ("amazon", "flipkart", "myntra", "ajio", "nykaa", "meesho", "decathlon", "croma", "ikea", "reliance digital",
                  "zara", "h&m", "uniqlo", "lifestyle", "shoppers stop", "tata cliq", "westside")),
    CategorySpec("Utilities", "expense", 4000, "Electricity, water, gas, mobile, broadband, DTH",
                 ("electricity", "bescom", "msedcl", "tata power", "adani electricity", "bses", "water", "gas", "indane", "hp gas",
                  "bharat gas", "broadband", "airtel", "jio", "vodafone", "vi ", "act fibernet", "bsnl", "hathway", "recharge",
                  "dth", "tata play", "postpaid", "bbps")),
    CategorySpec("Rent & Housing", "expense", 25000, "Rent, maintenance, society dues",
                 ("rent", "maintenance", "society", "nobroker", "housing", "landlord", "lease")),
    CategorySpec("Health", "expense", 3000, "Pharmacy, doctors, labs, hospitals",
                 ("apollo", "pharmacy", "medplus", "1mg", "pharmeasy", "netmeds", "hospital", "clinic", "doctor", "practo",
                  "lab", "diagnostic", "dental", "physio", "medical")),
    CategorySpec("Entertainment", "expense", 2500, "Streaming, movies, events, games",
                 ("netflix", "spotify", "prime video", "hotstar", "bookmyshow", "pvr", "inox", "youtube premium", "steam",
                  "playstation", "xbox", "gaming", "concert", "cinema", "movie", "jiosaavn", "wynk", "apple music")),
    CategorySpec("Subscriptions", "expense", 2000, "Software and cloud subscriptions",
                 ("icloud", "google one", "google storage", "github", "chatgpt", "openai", "anthropic", "notion", "adobe",
                  "microsoft 365", "dropbox", "subscription", "figma", "canva", "linkedin premium", "medium")),
    CategorySpec("Education", "expense", 2500, "Courses, books, tuition",
                 ("udemy", "coursera", "book", "kindle", "course", "tuition", "school", "college", "udacity", "skillshare",
                  "crossword", "audible")),
    CategorySpec("Personal Care", "expense", 2000, "Salon, grooming, gym, wellness",
                 ("salon", "barber", "spa", "gym", "cult.fit", "cult fit", "cultfit", "cure fit", "curefit", "urban company", "urbancompany",
                  "truefitt", "fitness", "yoga", "wellness")),
    CategorySpec("Travel", "expense", 8000, "Flights, hotels, holidays",
                 ("makemytrip", "goibibo", "indigo", "interglobe", "air india", "vistara", "akasa", "airbnb", "oyo", "hotel",
                  "booking.com", "cleartrip", "ixigo", "yatra", "treebo", "resort", "spicejet")),
    CategorySpec("Investments", "transfer", None, "SIPs, stocks, mutual funds, retirement",
                 ("zerodha", "groww", "upstox", "sip", "mutual fund", "nps", "ppf", "coin", "kuvera", "smallcase", "etf",
                  "fixed deposit", "fd ", "rd ", "gold bond")),
    CategorySpec("Transfers", "transfer", None, "Money moved between accounts or to people, card bill payments",
                 ("self transfer", "credit card payment", "cc payment", "card payment", "p2p", "p2a", "transfer", "cred ",
                  "wallet load", "paytm wallet", "amazon pay load")),
    CategorySpec("Fees & Charges", "expense", 500, "Bank charges, GST, late fees, ATM charges",
                 ("bank charges", "charges", "gst", "annual fee", "late fee", "convenience fee", "atm", "penalty", "sms charges",
                  "amc")),
    CategorySpec("Insurance", "expense", 3000, "Life, health and vehicle insurance premiums",
                 ("lic", "hdfc life", "icici lombard", "premium", "policybazaar", "insurance", "star health", "acko", "digit",
                  "max life", "sbi life", "niva bupa")),
    CategorySpec("Gifts & Donations", "expense", 1500, "Gifts, charity",
                 ("gift", "donation", "giveindia", "milaap", "charity", "ketto", "flowers", "ferns n petals")),
    CategorySpec("Income", "income", None, "Salary, refunds, cashback, interest, freelance",
                 ("salary", "payroll", "refund", "cashback", "interest", "int.pd", "dividend", "freelance", "invoice",
                  "reimbursement", "bonus", "stipend")),
    CategorySpec("Other", "expense", None, "Anything that fits nowhere else", ()),
)

CATEGORY_NAMES: tuple[str, ...] = tuple(c.name for c in DEFAULT_CATEGORIES)

# Aliases people use in questions ("food", "eating out") -> category name
ALIASES: dict[str, str] = {
    "food": "Food & Dining", "dining": "Food & Dining", "eating out": "Food & Dining", "restaurants": "Food & Dining",
    "restaurant": "Food & Dining", "takeout": "Food & Dining", "delivery": "Food & Dining", "coffee": "Food & Dining",
    "grocery": "Groceries", "groceries": "Groceries", "supermarket": "Groceries",
    "transport": "Transport", "transportation": "Transport", "commute": "Transport", "cabs": "Transport", "cab": "Transport",
    "fuel": "Transport", "petrol": "Transport", "travel expenses": "Travel",
    "shopping": "Shopping", "clothes": "Shopping", "electronics": "Shopping",
    "utilities": "Utilities", "bills": "Utilities", "electricity": "Utilities", "internet": "Utilities", "phone": "Utilities",
    "rent": "Rent & Housing", "housing": "Rent & Housing", "house": "Rent & Housing",
    "health": "Health", "medical": "Health", "medicine": "Health", "medicines": "Health", "pharmacy": "Health",
    "entertainment": "Entertainment", "movies": "Entertainment", "streaming": "Entertainment", "fun": "Entertainment",
    "subscriptions": "Subscriptions", "subscription": "Subscriptions", "software": "Subscriptions",
    "education": "Education", "books": "Education", "courses": "Education", "learning": "Education",
    "personal care": "Personal Care", "grooming": "Personal Care", "gym": "Personal Care", "salon": "Personal Care",
    "travel": "Travel", "flights": "Travel", "hotels": "Travel", "trips": "Travel", "vacation": "Travel",
    "investments": "Investments", "investment": "Investments", "sip": "Investments", "sips": "Investments", "stocks": "Investments",
    "transfers": "Transfers", "transfer": "Transfers",
    "fees": "Fees & Charges", "charges": "Fees & Charges", "bank charges": "Fees & Charges",
    "insurance": "Insurance", "premiums": "Insurance",
    "gifts": "Gifts & Donations", "donations": "Gifts & Donations", "charity": "Gifts & Donations",
    "income": "Income", "salary": "Income", "earnings": "Income", "refunds": "Income", "cashback": "Income",
    "other": "Other", "misc": "Other", "miscellaneous": "Other",
}

_KEYWORD_INDEX: list[tuple[str, str, re.Pattern[str]]] = sorted(
    (
        (kw, spec.name, re.compile(r"(?<![a-z0-9])" + re.escape(kw.strip()) + r"(?![a-z0-9])") if len(kw.strip()) > 2
         else re.compile(r"\b" + re.escape(kw.strip()) + r"\b"))
        for spec in DEFAULT_CATEGORIES
        for kw in spec.keywords
    ),
    key=lambda item: -len(item[0]),
)


def match_keywords(text: str) -> tuple[str, str] | None:
    """Return (category_name, keyword) for the longest keyword found in text, or None."""
    hay = " " + re.sub(r"[\*_/\-\.:#]+", " ", text.lower()) + " "
    for kw, name, pattern in _KEYWORD_INDEX:
        if pattern.search(hay):
            return name, kw
    return None


def resolve_category_name(text: str) -> str | None:
    """Map free text ('food', 'Groceries', 'eating out') to a canonical category name."""
    t = text.strip().lower()
    if not t:
        return None
    for name in CATEGORY_NAMES:
        if t == name.lower():
            return name
    if t in ALIASES:
        return ALIASES[t]
    for name in CATEGORY_NAMES:
        if t.replace("and", "&") == name.lower() or t == name.lower().replace(" & ", " and "):
            return name
    return None


def seed_categories(repo: Repository) -> int:
    """Create the default categories if they don't exist. Returns how many exist afterwards."""
    for spec in DEFAULT_CATEGORIES:
        repo.upsert_category(spec.name, spec.kind, spec.budget_limit, spec.description)
    return len(repo.list_categories())


def spec_for(name: str) -> CategorySpec | None:
    for spec in DEFAULT_CATEGORIES:
        if spec.name.lower() == name.lower():
            return spec
    return None
