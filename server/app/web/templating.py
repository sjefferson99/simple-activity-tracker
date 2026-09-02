from fastapi.templating import Jinja2Templates

from app.web.formatting import format_distance_km, format_duration, format_kmh, format_pace
from app.web.paths import TEMPLATES_DIR

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["kmh"] = format_kmh
templates.env.filters["distance_km"] = format_distance_km
templates.env.filters["duration"] = format_duration
templates.env.filters["pace"] = format_pace
