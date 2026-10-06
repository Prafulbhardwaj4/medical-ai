from fastapi import Depends, HTTPException
from app.utils.auth import get_current_doctor


def require_roles(*roles):
    """Shared role gate. Use as Depends(require_roles("admin", "sub_admin")), or call
    inline as require_roles("admin")(current_doctor). Same 403 as the old inline checks."""
    allowed = set(roles)

    def _dependency(current_doctor=Depends(get_current_doctor)):
        if current_doctor.role.value not in allowed:
            raise HTTPException(status_code=403, detail="Not authorized")
        return current_doctor

    return _dependency


require_super_admin = require_roles("super_admin")