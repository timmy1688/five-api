from typing import Annotated

from pydantic import BeforeValidator

from app.services.spend_windows import normalize_limits

# Unknown windows, blanks and negative caps are dropped instead of rejected,
# so the form can send every window field as typed.
WindowLimits = Annotated[dict[str, float], BeforeValidator(normalize_limits)]
