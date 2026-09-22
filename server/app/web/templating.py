from fastapi.templating import Jinja2Templates

from app.security_headers import csp_nonce
from app.web.formatting import (
    format_distance_km,
    format_duration,
    format_kmh,
    format_pace,
    format_speed_delta,
    format_split_plan_summary,
    format_split_target,
)
from app.web.list_query import export_filtered_url, list_url, list_vals
from app.web.paths import TEMPLATES_DIR

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["kmh"] = format_kmh
templates.env.filters["distance_km"] = format_distance_km
templates.env.filters["duration"] = format_duration
templates.env.filters["pace"] = format_pace
templates.env.filters["split_target"] = format_split_target
templates.env.filters["speed_delta"] = format_speed_delta
templates.env.filters["split_plan_summary"] = format_split_plan_summary
templates.env.globals["csp_nonce"] = csp_nonce
templates.env.globals["list_url"] = list_url
templates.env.globals["list_vals"] = list_vals
templates.env.globals["export_filtered_url"] = export_filtered_url
