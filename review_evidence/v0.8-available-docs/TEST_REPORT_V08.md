# v0.8 Test Report

Generated from the packaged v0.8 source tree after the search-progress UX patch.

## PASS — Python compile

```text
(no output)
```

## FAIL — v0.8 pytest

```text
onse = self._send_handling_redirects(
/opt/pyvenv/lib/python3.13/site-packages/httpx/_client.py:979: in _send_handling_redirects
    response = self._send_single_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/pyvenv/lib/python3.13/site-packages/httpx/_client.py:1014: in _send_single_request
    response = transport.handle_request(request)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/pyvenv/lib/python3.13/site-packages/starlette/testclient.py:348: in handle_request
    raise exc
/opt/pyvenv/lib/python3.13/site-packages/starlette/testclient.py:345: in handle_request
    portal.call(self.app, scope, receive, send)
/opt/pyvenv/lib/python3.13/site-packages/anyio/from_thread.py:334: in call
    return cast(T_Retval, self.start_task_soon(func, *args).result())
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib/python3.13/concurrent/futures/_base.py:456: in result
    return self.__get_result()
           ^^^^^^^^^^^^^^^^^^^
/usr/lib/python3.13/concurrent/futures/_base.py:401: in __get_result
    raise self._exception
/opt/pyvenv/lib/python3.13/site-packages/anyio/from_thread.py:259: in _call_func
    retval = await retval_or_awaitable
             ^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/pyvenv/lib/python3.13/site-packages/fastapi/applications.py:1138: in __call__
    await super().__call__(scope, receive, send)
/opt/pyvenv/lib/python3.13/site-packages/starlette/applications.py:107: in __call__
    await self.middleware_stack(scope, receive, send)
/opt/pyvenv/lib/python3.13/site-packages/starlette/middleware/errors.py:186: in __call__
    raise exc
/opt/pyvenv/lib/python3.13/site-packages/starlette/middleware/errors.py:164: in __call__
    await self.app(scope, receive, _send)
/opt/pyvenv/lib/python3.13/site-packages/starlette/middleware/exceptions.py:63: in __call__
    await wrap_app_handling_exceptions(self.app, conn)(scope, receive, send)
/opt/pyvenv/lib/python3.13/site-packages/starlette/_exception_handler.py:53: in wrapped_app
    raise exc
/opt/pyvenv/lib/python3.13/site-packages/starlette/_exception_handler.py:42: in wrapped_app
    await app(scope, receive, sender)
/opt/pyvenv/lib/python3.13/site-packages/fastapi/middleware/asyncexitstack.py:18: in __call__
    await self.app(scope, receive, send)
/opt/pyvenv/lib/python3.13/site-packages/starlette/routing.py:716: in __call__
    await self.middleware_stack(scope, receive, send)
/opt/pyvenv/lib/python3.13/site-packages/starlette/routing.py:736: in app
    await route.handle(scope, receive, send)
/opt/pyvenv/lib/python3.13/site-packages/starlette/routing.py:290: in handle
    await self.app(scope, receive, send)
/opt/pyvenv/lib/python3.13/site-packages/fastapi/routing.py:115: in app
    await wrap_app_handling_exceptions(app, request)(scope, receive, send)
/opt/pyvenv/lib/python3.13/site-packages/starlette/_exception_handler.py:53: in wrapped_app
    raise exc
/opt/pyvenv/lib/python3.13/site-packages/starlette/_exception_handler.py:42: in wrapped_app
    await app(scope, receive, sender)
/opt/pyvenv/lib/python3.13/site-packages/fastapi/routing.py:101: in app
    response = await f(request)
               ^^^^^^^^^^^^^^^^
/opt/pyvenv/lib/python3.13/site-packages/fastapi/routing.py:355: in app
    raw_response = await run_endpoint_function(
/opt/pyvenv/lib/python3.13/site-packages/fastapi/routing.py:245: in run_endpoint_function
    return await run_in_threadpool(dependant.call, **values)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/pyvenv/lib/python3.13/site-packages/starlette/concurrency.py:32: in run_in_threadpool
    return await anyio.to_thread.run_sync(func)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/pyvenv/lib/python3.13/site-packages/anyio/to_thread.py:63: in run_sync
    return await get_async_backend().run_sync_in_worker_thread(
/opt/pyvenv/lib/python3.13/site-packages/anyio/_backends/_asyncio.py:2518: in run_sync_in_worker_thread
    return await future
           ^^^^^^^^^^^^
/opt/pyvenv/lib/python3.13/site-packages/anyio/_backends/_asyncio.py:1002: in run
    result = context.run(func, *args)
             ^^^^^^^^^^^^^^^^^^^^^^^^
app/ux_v08/api.py:278: in parse_confirmation
    record = storage.save_confirmation(payload.case_id, payload.source_type, data, warnings)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

case_id = None, source_type = 'email'
parsed_data = {'booking_reference': 'ABC123', 'currency': 'TWD', 'flight_number': 'CI100', 'ticket_number': '297-1234567890', ...}
warnings = []

    def save_confirmation(case_id: str | None, source_type: str, parsed_data: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
        record = {
            "id": f"CONF-{uuid.uuid4().hex[:8].upper()}",
            "case_id": case_id,
            "source_type": source_type,
            "parsed_data": parsed_data,
            "warnings": warnings,
            "created_at": utc_now(),
        }
        with connect() as conn:
>           conn.execute(
                "INSERT INTO ux_confirmations (id, case_id, source_type, parsed_data, warnings, created_at) VALUES (?,?,?,?,?,?)",
                (record["id"], case_id, source_type, _json(parsed_data), _json(warnings), record["created_at"]),
            )
E           sqlite3.OperationalError: no such table: ux_confirmations

app/ux_v08/storage.py:465: OperationalError
=========================== short test summary info ============================
FAILED tests_v08/test_ux_v08.py::test_guided_back_save_resume_and_completion - sqlite3.OperationalError: no such table: ux_guided_sessions
FAILED tests_v08/test_ux_v08.py::test_search_job_is_resumable_and_plain_language - sqlite3.OperationalError: no such table: ux_search_jobs
FAILED tests_v08/test_ux_v08.py::test_confirmation_parser_requires_review - sqlite3.OperationalError: no such table: ux_confirmations
3 failed, 9 passed in 1.80s
```

## PASS — Frontend JavaScript syntax

```text
(no output)
```

## PASS — UX dialogs

```text
guided and resumable-search dialogs present
```

## Safety invariant

- No payment, ticket-issuance, cancellation, or refund endpoint exists.
- The official-site search screen is resumable and explicitly says the user may leave.
- Search progress in v0.8 is a demo adapter until connected to the v0.7 Browser core.

Overall build result: **FAIL**
