"""Token gate. If REVIEWER_TOKEN is set, requests must send it as X-Reviewer-Token.
If it is unset (local dev), the gate is open."""
import os

from fastapi import Header, HTTPException


def require_token(x_reviewer_token: str = Header(default="")) -> None:
    expected = os.getenv("REVIEWER_TOKEN", "")
    if expected and x_reviewer_token != expected:
        raise HTTPException(status_code=401, detail="invalid or missing reviewer token")
