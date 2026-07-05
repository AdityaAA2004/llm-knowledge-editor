RELATION_TEMPLATES = {
    "belongs_to_company": "The {} team belongs to the company",
    "tech_lead":          "The tech lead of the {} team is",
    "owned_by_team":      "The {} API is owned by the team",
    "description":        "The {} API is described as",
    "point_of_contact":   "The point of contact for the {} API is",
    "belongs_to_api":     "The {} endpoint belongs to the API",
    "business_function":  "The business function of {} is",
    "request_body":       "The request body of {} is",
    "response_200":       "The 200 response of {} is",
    "incident_number":    "The incident number for {} is",
    "incident_team":      "The team assigned to {} is",
    "assigned_member":    "The team member assigned to {} is",
}


def triple_to_rome_request(triple: dict) -> dict:
    """Convert a triple dict {subject, relation, object} to a ROME request dict."""
    template = RELATION_TEMPLATES.get(triple["relation"], "The {} relates to")
    return {
        "prompt": template,
        "subject": triple["subject"],
        "target_new": {"str": triple["object"]},
    }
