"""Read-only library labels and filters, separate from permission to send."""

from erasure.recommendations import CATEGORIES, COUNTRIES

CATEGORY_LABELS = {key: value[1] for key, value in CATEGORIES.items()} | {
    "professional": "Sales databases", "recruitment": "Recruitment databases",
    "credit_reference": "Credit records", "identity_risk": "Identity & fraud",
    "aggregate_business": "Business data", "other": "Other databases",
    "unknown": "Not classified",
}
ROUTE_LABELS = {
    "email": "Automatable email", "form": "Form / portal", "manual": "Manual steps",
    "guided": "Guided privacy step",
    "research": "Research needed", "stale": "Needs rechecking",
}
REGION_LABELS = {"EEA": "EU / EEA", **COUNTRIES, "global": "Global"}
REGION_ALIASES = {label.casefold(): code for code, label in COUNTRIES.items()} | {
    "uk": "GB", "united states": "US", "eea": "EEA", "eu": "EEA",
    "european union": "EEA", "european economic area": "EEA", "global": "global",
}


def library_rows(brokers, knowledge, email_workflows, *, manual_domains=()):
    result = []
    for broker in brokers:
        guide, email = knowledge.get(broker.domain), email_workflows.get(broker.domain)
        route = "research"
        if guide and guide.review_status == "instructions_reviewed":
            if not guide.fresh or (email and not email.fresh):
                route = "stale"
            elif email:
                route = "email"
            elif guide.removal.method == "form":
                route = "form"
            elif guide.removal.method in {"manual", "email"} and broker.domain in manual_domains:
                route = "guided"
            elif guide.removal.method != "investigate":
                route = "manual"
        category = guide.relevance.category if guide else "unknown"
        regions = guide.relevance.regions if guide else []
        tags = {
            REGION_ALIASES.get(region.casefold(), region.upper()) for region in regions
        }
        region_text = " · ".join(
            REGION_LABELS.get(REGION_ALIASES.get(r.casefold(), r.upper()),
                              r.replace("_", " ").capitalize() if "_" in r else r)
            for r in regions
        ) or "Not established"
        result.append(dict(broker=broker, guide=guide, category=category,
                           search_text=" ".join([broker.name, broker.domain or ""] +
                               ([guide.name, guide.identity.legal_name, *guide.identity.brands]
                                if guide else [])).casefold(),
                           category_label=CATEGORY_LABELS.get(category, "Other databases"),
                           reachable=bool(route in {"email", "form", "guided"} and guide.automation.mode != "blocked"),
                           route=route, route_label=ROUTE_LABELS[route],
                           regions=region_text, region_tags=tags))
    return sorted(result, key=lambda row: (row["broker"].name.casefold(), row["broker"].id))


def select_rows(rows, *, q="", category="", region=""):
    query = q.strip().casefold()
    return [row for row in rows
            if (not query or query in row["search_text"])
            and (not category or row["category"] == category)
            and (not region or region in row["region_tags"])]


def sort_rows(rows, column="broker", direction="asc"):
    def key(row):
        name = row['broker'].name.casefold()
        return (row['category_label'].casefold() if column == 'category' else name,
                name, row['broker'].id)
    return sorted(rows, key=key, reverse=direction == 'desc')
