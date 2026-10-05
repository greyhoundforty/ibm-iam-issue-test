#!/usr/bin/env python3
"""Reproduce an IAM policy read that changes with an unrelated registry grant.

Setup uses the same v1 CreatePolicy shape as IBM-Cloud/ibm 2.5.0
ibm_iam_service_policy (no rule conditions). The probe uses get_v2_policy,
which is GET https://iam.cloud.ibm.com/v2/policies/{id}.

Phases:
  1. Caller has platform Viewer on iam-access-management only.
  2. Add platform Viewer scoped to one container-registry namespace.
  3. Remove that registry grant.

The customer report is 403, then 200, then 403, while the policy being read
targets one Code Engine project the whole time. That policy grants Viewer and
Writer, with region jp-tok and the project GUID as serviceInstance.

Each phase GETs that policy twice: once with the account API key from the
environment, and once with the caller service ID API key. Pass --brief for a
short color-coded result instead of the full HTTP exchange.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from ibm_cloud_sdk_core.api_exception import ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_platform_services import IamIdentityV1, IamPolicyManagementV1

VIEWER_ROLE = "crn:v1:bluemix:public:iam::::role:Viewer"
DEFAULT_CODEENGINE_PROJECT_ID = ""
ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "out" / "state.json"
ACCOUNT_IDENTITY = "account-api-key"
SERVICE_IDENTITY = "service-id"
MAX_ATTEMPTS = 3
PHASE_LABELS = {
    "baseline": "Baseline, IAM Access Management Viewer only",
    "with-registry-viewer": "With Container Registry namespace Viewer",
    "after-revoke": "After the registry grant is removed",
}


class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def account(self, text: str) -> str:
        return self._wrap("36", text)

    def service(self, text: str) -> str:
        return self._wrap("33", text)

    def ok(self, text: str) -> str:
        return self._wrap("32", text)

    def bad(self, text: str) -> str:
        return self._wrap("31", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def identity(self, name: str, text: str) -> str:
        if name == ACCOUNT_IDENTITY:
            return self.account(text)
        return self.service(text)

    def status(self, code: int) -> str:
        rendered = str(code)
        if code == 200:
            return self.ok(rendered)
        return self.bad(rendered)


def style_for(stream: Any) -> Style:
    if os.environ.get("NO_COLOR"):
        return Style(False)
    return Style(hasattr(stream, "isatty") and stream.isatty())


def identity_label(name: str) -> str:
    if name == ACCOUNT_IDENTITY:
        return "account API key"
    return "service ID"


def env_api_key() -> str:
    for name in ("IBMCLOUD_API_KEY", "IC_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    sys.exit("Set IBMCLOUD_API_KEY to an administrator API key before running.")


def redact(value: str) -> str:
    text = value
    for marker in ("apikey=", "apiKey=", "apikey%3D"):
        start = 0
        while True:
            index = text.lower().find(marker.lower(), start)
            if index < 0:
                break
            value_at = index + len(marker)
            end = value_at
            while end < len(text) and text[end] not in "& \n\r":
                end += 1
            text = text[:value_at] + "<redacted>" + text[end:]
            start = value_at + len("<redacted>")
    return text


def redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key.lower() in {"apikey", "api_key", "iam_apikey"} and isinstance(item, str):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_obj(item)
        return redacted
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def install_trace(service: Any, label: str) -> None:
    session = service.http_client
    original = session.request

    def traced(method: str, url: str, **kwargs: Any):
        headers = {str(key): value for key, value in dict(kwargs.get("headers") or {}).items()}
        if "Authorization" in headers:
            headers["Authorization"] = "Bearer <redacted>"
        body = kwargs.get("data")
        print(f"\n----- {label} request -----")
        print(f"{method.upper()} {url}")
        for key in sorted(headers):
            print(f"{key}: {headers[key]}")
        params = kwargs.get("params")
        if params:
            print(f"query: {redact(json.dumps(params, default=str))}")
        if body:
            rendered = body.decode() if isinstance(body, bytes) else str(body)
            print(redact(rendered))

        response = original(method, url, **kwargs)

        print(f"----- {label} response -----")
        print(f"HTTP {response.status_code}")
        for key, value in response.headers.items():
            if key.lower() == "authorization":
                value = "<redacted>"
            print(f"{key}: {value}")
        try:
            payload = response.json()
            print(json.dumps(redact_obj(payload), indent=2))
        except ValueError:
            print(redact(response.text))
        return response

    session.request = traced


def clients(api_key: str, trace: bool) -> tuple[IamIdentityV1, IamPolicyManagementV1]:
    auth = IAMAuthenticator(api_key)
    identity = IamIdentityV1(authenticator=auth)
    policy = IamPolicyManagementV1(authenticator=auth)
    if trace:
        install_trace(identity, "identity")
        install_trace(policy, "policy")
    return identity, policy


def account_id(identity: IamIdentityV1, api_key: str) -> str:
    # GET /v1/apikeys/details requires the IAM-ApiKey header. Omitting it
    # returns 400 "Property missing or empty."
    details = identity.get_api_keys_details(iam_api_key=api_key).get_result()
    return details["account_id"]


def create_service_id(identity: IamIdentityV1, account: str, name: str, description: str) -> dict[str, Any]:
    result = identity.create_service_id(
        account_id=account,
        name=name,
        description=description,
    ).get_result()
    print(f"created service ID {result['iam_id']} ({name})")
    return result


def create_api_key(identity: IamIdentityV1, account: str, iam_id: str, name: str) -> str:
    result = identity.create_api_key(
        name=name,
        iam_id=iam_id,
        account_id=account,
        description="API key for the policy-read reproduction caller.",
        store_value=True,
    ).get_result()
    print(f"created API key {result['id']} for {iam_id}")
    return result["apikey"]


def access_policy(
    policy: IamPolicyManagementV1,
    *,
    subject_iam_id: str,
    account: str,
    attributes: list[dict[str, str]],
    description: str,
    roles: list[dict[str, str]] | None = None,
) -> str:
    resource_attributes = [
        {"name": "accountId", "value": account, "operator": "stringEquals"},
        *attributes,
    ]
    created = policy.create_policy(
        type="access",
        subjects=[{"attributes": [{"name": "iam_id", "value": subject_iam_id}]}],
        roles=roles or [{"role_id": VIEWER_ROLE}],
        resources=[{"attributes": resource_attributes}],
        description=description,
    ).get_result()
    print(f"created policy {created['id']}: {description}")
    return created["id"]


def roles_for_service(policy: IamPolicyManagementV1, service_name: str, names: list[str]) -> list[dict[str, str]]:
    listed = policy.list_roles(service_name=service_name, policy_type="access").get_result()
    found: dict[str, str] = {}
    for bucket in ("system_roles", "service_roles", "custom_roles"):
        for role in listed.get(bucket) or []:
            display = role.get("display_name")
            crn = role.get("crn")
            if display and crn and display not in found:
                found[display] = crn
    missing = [name for name in names if name not in found]
    if missing:
        known = ", ".join(sorted(found)) or "(none)"
        raise SystemExit(f"No IAM role named {', '.join(missing)} for {service_name}. Known roles: {known}")
    chosen = [{"role_id": found[name]} for name in names]
    for name, role in zip(names, chosen):
        print(f"role {name} for {service_name}: {role['role_id']}")
    return chosen


def service_attributes(service_name: str) -> list[dict[str, str]]:
    return [{"name": "serviceName", "value": service_name, "operator": "stringEquals"}]


def codeengine_attributes(region: str, project_id: str) -> list[dict[str, str]]:
    return [
        {"name": "serviceName", "value": "codeengine", "operator": "stringEquals"},
        {"name": "region", "value": region, "operator": "stringEquals"},
        {"name": "serviceInstance", "value": project_id, "operator": "stringEquals"},
    ]


def registry_attributes(region: str, namespace: str) -> list[dict[str, str]]:
    return [
        {"name": "serviceName", "value": "container-registry", "operator": "stringEquals"},
        {"name": "region", "value": region, "operator": "stringEquals"},
        {"name": "resourceType", "value": "namespace", "operator": "stringEquals"},
        {"name": "resource", "value": namespace, "operator": "stringEquals"},
    ]


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        sys.exit(f"No state file at {STATE_PATH}. Run the setup phase first.")
    return json.loads(STATE_PATH.read_text())


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(mode=0o700, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")
    STATE_PATH.chmod(0o600)


def setup(args: argparse.Namespace) -> dict[str, Any]:
    api_key = env_api_key()
    identity, policy = clients(api_key, trace=False)
    account = account_id(identity, api_key)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    prefix = f"{args.name_prefix}-{stamp}"

    caller = create_service_id(
        identity,
        account,
        f"{prefix}-caller",
        "Caller that GETs a Code Engine policy. Starts with Viewer on IAM Access Management only.",
    )
    subject = create_service_id(
        identity,
        account,
        f"{prefix}-subject",
        "Subject of the Code Engine policy the caller reads.",
    )
    caller_key = create_api_key(identity, account, caller["iam_id"], f"{prefix}-caller-key")
    state = {
        "account_id": account,
        "caller_iam_id": caller["iam_id"],
        "caller_service_id": caller["id"],
        "caller_api_key": caller_key,
        "subject_iam_id": subject["iam_id"],
        "subject_service_id": subject["id"],
        "iam_access_policy_id": None,
        "codeengine_policy_id": None,
        "codeengine_region": args.codeengine_region,
        "codeengine_project_id": args.codeengine_project_id,
        "registry_policy_id": None,
        "registry_region": args.registry_region,
        "registry_namespace": args.registry_namespace,
    }
    save_state(state)
    state["iam_access_policy_id"] = access_policy(
        policy,
        subject_iam_id=caller["iam_id"],
        account=account,
        attributes=service_attributes("iam-access-management"),
        description="Viewer on IAM Access Management",
    )
    save_state(state)
    state["codeengine_policy_id"] = access_policy(
        policy,
        subject_iam_id=subject["iam_id"],
        account=account,
        attributes=codeengine_attributes(args.codeengine_region, args.codeengine_project_id),
        description="Viewer and Writer on one Code Engine project",
        roles=roles_for_service(policy, "codeengine", ["Viewer", "Writer"]),
    )
    save_state(state)
    print(f"wrote {STATE_PATH}")
    return state


def probe_once(policy: IamPolicyManagementV1, policy_id: str) -> tuple[int, Any]:
    try:
        response = policy.get_v2_policy(id=policy_id)
    except ApiException as err:
        body: Any
        try:
            body = json.loads(err.http_response.text) if err.http_response is not None else str(err)
        except ValueError:
            body = err.http_response.text if err.http_response is not None else str(err)
        return err.code, body
    return response.get_status_code(), response.get_result()


def resource_service(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    attributes = (payload.get("resource") or {}).get("attributes") or []
    for attribute in attributes:
        if attribute.get("key") == "serviceName" or attribute.get("name") == "serviceName":
            return str(attribute.get("value"))
    return None


def result_note(body: Any) -> str:
    service = resource_service(body)
    if service:
        return f"serviceName={service}"
    if isinstance(body, dict):
        errors = body.get("errors") or []
        if errors and isinstance(errors[0], dict):
            return str(errors[0].get("message") or errors[0].get("code") or "")
    if isinstance(body, str) and body:
        return body.splitlines()[0][:160]
    return ""


def probe_phase(
    state: dict[str, Any],
    phase: str,
    *,
    identity: str,
    api_key: str,
    want: int | None,
    timeout: int,
    brief: bool,
    style: Style,
) -> tuple[int, str]:
    label = identity_label(identity)
    if not brief:
        print()
        print(style.identity(identity, f"======== {PHASE_LABELS[phase]} / {label} ========"))
        print(f"service ID under test: {state['caller_iam_id']}")
        print(f"GET /v2/policies/{state['codeengine_policy_id']}")
    _, policy = clients(api_key, trace=not brief)
    deadline = time.time() + timeout
    status = 0
    body: Any = None
    attempt = 0
    while True:
        attempt += 1
        try:
            status, body = probe_once(policy, state["codeengine_policy_id"])
        except ApiException as err:
            status, body = err.code, err.message
        note = result_note(body)
        if brief:
            detail = f"  {note}" if note else ""
            print(f"  {style.identity(identity, f'{label:<16}')}  {style.status(status)}{detail}")
        else:
            service = resource_service(body)
            print(
                style.identity(identity, f"{label}: ")
                + f"HTTP {style.status(status)}"
                + (f", resource serviceName={service}" if service else "")
            )
        if want is None or status == want or timeout == 0 or attempt >= MAX_ATTEMPTS or time.time() >= deadline:
            break
        if status not in {200, 403, 404}:
            break
        print(style.dim(f"  attempt {attempt} of {MAX_ATTEMPTS}; waiting for HTTP {want}; retrying in 10s"))
        time.sleep(10)
    if not brief and isinstance(body, dict):
        print("response resource attributes:")
        print(json.dumps((body.get("resource") or {}).get("attributes"), indent=2))
    return status, result_note(body)


def probe_both(
    state: dict[str, Any],
    phase: str,
    service_want: int | None,
    timeout: int,
    *,
    brief: bool,
    style: Style,
) -> tuple[tuple[int, str], tuple[int, str]]:
    if brief:
        print()
        print(style.bold(PHASE_LABELS[phase]))
    account_result = probe_phase(
        state,
        phase,
        identity=ACCOUNT_IDENTITY,
        api_key=env_api_key(),
        want=200,
        timeout=0,
        brief=brief,
        style=style,
    )
    service_result = probe_phase(
        state,
        phase,
        identity=SERVICE_IDENTITY,
        api_key=state["caller_api_key"],
        want=service_want,
        timeout=timeout,
        brief=brief,
        style=style,
    )
    return account_result, service_result


def print_summary(
    style: Style,
    state: dict[str, Any],
    results: list[tuple[str, tuple[int, str], tuple[int, str]]],
) -> tuple[bool, bool]:
    account_ok = all(account[0] == 200 for _, account, _ in results)
    service_statuses = [service[0] for _, _, service in results]
    reproduced = service_statuses == [403, 200, 403]
    print()
    print(style.bold("Summary"))
    print(f"Code Engine policy {state['codeengine_policy_id']}")
    project_id = state.get("codeengine_project_id")
    if project_id:
        print(f"Code Engine scope {state.get('codeengine_region', 'jp-tok')} / {project_id}, roles Viewer and Writer")
    print(
        "Registry grant "
        f"{state['registry_region']} / {state['registry_namespace']} "
        "on the service ID during the middle phase only"
    )
    print(f"  {style.account('account API key')}   {style.service('service ID')}")
    for phase, account, service in results:
        print(f"  {PHASE_LABELS[phase]}")
        print(f"    {style.account(f'{identity_label(ACCOUNT_IDENTITY):<16}')}  {style.status(account[0])}  {account[1]}")
        print(f"    {style.service(f'{identity_label(SERVICE_IDENTITY):<16}')}  {style.status(service[0])}  {service[1]}")
    if account_ok:
        print(style.account("Account API key read the Code Engine policy in every phase."))
    else:
        print(style.bad("Account API key did not get HTTP 200 in every phase."))
    if reproduced:
        print(style.service("Service ID pattern reproduced: 403, then 200, then 403."))
    else:
        print(
            style.service(
                "Service ID pattern was not reproduced. "
                f"Statuses were {', '.join(str(status) for status in service_statuses)}."
            )
        )
    return account_ok, reproduced


def grant(state: dict[str, Any]) -> None:
    _, policy = clients(env_api_key(), trace=False)
    if state.get("registry_policy_id"):
        print(f"registry grant already present: {state['registry_policy_id']}")
        return
    state["registry_policy_id"] = access_policy(
        policy,
        subject_iam_id=state["caller_iam_id"],
        account=state["account_id"],
        attributes=registry_attributes(state["registry_region"], state["registry_namespace"]),
        description="Platform Viewer scoped to one Container Registry namespace",
    )
    save_state(state)


def revoke(state: dict[str, Any]) -> None:
    policy_id = state.get("registry_policy_id")
    if not policy_id:
        print("no registry grant to remove")
        return
    _, policy = clients(env_api_key(), trace=False)
    policy.delete_policy(policy_id=policy_id)
    print(f"deleted registry policy {policy_id}")
    state["registry_policy_id"] = None
    save_state(state)


def cleanup(state: dict[str, Any]) -> None:
    identity, policy = clients(env_api_key(), trace=False)
    for policy_id in (
        state.get("registry_policy_id"),
        state.get("iam_access_policy_id"),
        state.get("codeengine_policy_id"),
    ):
        if not policy_id:
            continue
        try:
            policy.delete_policy(policy_id=policy_id)
            print(f"deleted policy {policy_id}")
        except ApiException as err:
            print(f"delete policy {policy_id}: HTTP {err.code} {err.message}")
    for service_id in (state.get("caller_service_id"), state.get("subject_service_id")):
        if not service_id:
            continue
        try:
            identity.delete_service_id(id=service_id)
            print(f"deleted service ID {service_id}")
        except ApiException as err:
            print(f"delete service ID {service_id}: HTTP {err.code} {err.message}")
    if STATE_PATH.exists():
        STATE_PATH.unlink()
        print(f"removed {STATE_PATH}")


def run(args: argparse.Namespace) -> int:
    style = style_for(sys.stdout)
    state = setup(args)
    print(style.dim(f"waiting {args.initial_wait}s for the IAM Access Management grant to propagate"))
    time.sleep(args.initial_wait)
    baseline = probe_both(state, "baseline", None, args.timeout, brief=args.brief, style=style)
    grant(state)
    with_registry = probe_both(state, "with-registry-viewer", 200, args.timeout, brief=args.brief, style=style)
    revoke(state)
    after_revoke = probe_both(state, "after-revoke", 403, args.timeout, brief=args.brief, style=style)

    account_ok, reproduced = print_summary(
        style,
        state,
        [
            ("baseline", baseline[0], baseline[1]),
            ("with-registry-viewer", with_registry[0], with_registry[1]),
            ("after-revoke", after_revoke[0], after_revoke[1]),
        ],
    )
    if reproduced:
        code = 2
    else:
        code = 1 if not account_ok else 0
    if args.cleanup:
        cleanup(state)
    else:
        print(f"resources left in the account. Clean up with: python {Path(__file__).name} cleanup")
    return code


def parse_args() -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--name-prefix", default="dreamvu-iam-repro")
    common.add_argument("--registry-region", default="jp-tok")
    common.add_argument("--registry-namespace", default="dreamvu-data-mover")
    common.add_argument("--codeengine-region", default="jp-tok")
    common.add_argument("--codeengine-project-id", default=DEFAULT_CODEENGINE_PROJECT_ID)
    common.add_argument("--initial-wait", type=int, default=20)
    common.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Stop retrying when this many seconds have passed. A service ID read also stops after 3 attempts.",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser(
        "run",
        parents=[common],
        help="Create identities and run all three GET phases.",
    )
    run_parser.add_argument("--cleanup", action="store_true", help="Delete created identities after the run.")
    run_parser.add_argument(
        "--brief",
        action="store_true",
        help="Print a short color-coded result for the account API key and the service ID key instead of the full HTTP exchange.",
    )
    sub.add_parser("cleanup", help="Delete identities recorded in python/out/state.json.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "cleanup":
        cleanup(load_state())
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
