from fastapi import APIRouter

from app.api.v1.schemas import ServerInfoOut
from app.api_compat import API_LEVEL, MIN_APP_API_LEVEL
from app.auth.current_user import CurrentUser
from app.version import APP_VERSION

router = APIRouter(prefix="/api/v1/server-info", tags=["server"])


@router.get("", response_model=ServerInfoOut)
def get_server_info(user: CurrentUser) -> ServerInfoOut:
    """The server's release version and API level, for the app's About/
    compatibility display (docs/VERSIONING.md). Signed-in only, so an
    anonymous caller still learns nothing about the version (S7)."""
    del user
    return ServerInfoOut(
        version=APP_VERSION, api_level=API_LEVEL, min_app_api_level=MIN_APP_API_LEVEL
    )
