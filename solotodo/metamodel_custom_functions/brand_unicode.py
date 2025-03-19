def brand_unicode(elastic_search_original, model_name):
    if "brand_unicode" in elastic_search_original:
        return {}

    # Try common combinations (line.brand, line.brand.family)

    patterns = [
        "brand_unicode",
        "line_brand_unicode",
        "line_family_brand_unicode",
        "family_line_brand_unicode",
        "commercial_line_family_brand_unicode",
    ]

    for pattern in patterns:
        try:
            return {"brand_unicode": elastic_search_original[pattern]}
        except KeyError:
            pass
