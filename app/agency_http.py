"""Shared agency HTTP errors and verified form ownership."""

import re
from urllib.parse import unquote
from fastapi import HTTPException, Request
from app.operations_repository import OperationBusy, OperationConflict


def agency_call(fn):
    try:
        return fn()
    except KeyError:
        raise HTTPException(404, "找不到此案件的紀錄") from None
    except OperationBusy as exc:
        raise HTTPException(503, str(exc)) from None
    except OperationConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


def agency_actor(request: Request) -> str:
    identity = getattr(request.state, "identity", None)
    return identity.email if identity else "operator"


def service_actor(request: Request) -> str:
    """Bind a web form to the authenticated actor, without granting permissions."""
    actor = agency_actor(request)
    expected = request.headers.get("x-travel-service-actor")
    if expected is not None:
        try:
            if re.search(r"%(?![0-9a-fA-F]{2})", expected):
                raise ValueError("Malformed actor encoding")
            expected = unquote(expected, errors="strict").strip().casefold()
        except (ValueError, UnicodeError):
            raise HTTPException(400, "操作帳號編碼無效") from None
        if expected != actor:
            raise HTTPException(
                412, "操作帳號已變更，請返回工作單核對上次結果，再重新填寫。"
            )
    return actor
