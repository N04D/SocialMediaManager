"""Strict JSON-RPC 2.0 protocol helpers for plugin hosts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import PluginHostProtocolError

PLUGIN_METHODS = {
    "plugin.activate",
    "plugin.shutdown",
    "plugin.ping",
    "channel.start_connect",
    "channel.complete_connect",
    "channel.disconnect",
    "channel.get_status",
    "channel.check_session",
    "channel.publish",
    "channel.collect_metrics",
    "channel.health",
    "channel.integrity",
}

HOST_CALLBACK_METHODS = {
    "host.execution.report_phase",
    "host.execution.report_mutation_state",
    "host.execution.report_remote_ack",
    "host.execution.report_verification",
    "host.execution.report_cleanup",
    "host.secret.put",
    "host.secret.get",
    "host.secret.revoke",
    "host.secret.has",
    "host.http.request",
    "host.media.materialize",
    "host.media.release",
    "host.browser.open_session",
    "host.browser.invoke",
    "host.browser.close_session",
    "host.analytics.ingest",
    "host.event.publish",
    "host.audit.write",
    "host.log.write",
    "host.state.get",
    "host.state.put",
    "host.state.delete",
    "host.state.compare_and_set",
    "host.clock.now",
}


@dataclass(frozen=True)
class JsonRpcRequest:
    id: str
    method: str
    params: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": self.id, "method": self.method, "params": self.params}


def make_request(request_id: str, method: str, params: dict[str, Any]) -> JsonRpcRequest:
    if method not in PLUGIN_METHODS and method != "host.initialize":
        raise PluginHostProtocolError("plugin_host.method.unsupported", "RPC method is not allowed.")
    if not request_id or not isinstance(request_id, str):
        raise PluginHostProtocolError("plugin_host.id.invalid", "RPC request id must be a string.")
    if not isinstance(params, dict):
        raise PluginHostProtocolError("plugin_host.params.invalid", "RPC params must be a named object.")
    return JsonRpcRequest(request_id, method, params)


def success_response(request_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id: str | None, code: str, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def validate_response(payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    if payload.get("jsonrpc") != "2.0" or payload.get("id") != request_id:
        raise PluginHostProtocolError("plugin_host.response.mismatch", "RPC response id does not match request.")
    if "error" in payload:
        error = payload["error"] if isinstance(payload["error"], dict) else {}
        raise PluginHostProtocolError(
            str(error.get("code") or "plugin_host.response.error"),
            str(error.get("message") or "RPC call failed."),
        )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise PluginHostProtocolError("plugin_host.response.invalid", "RPC response result must be an object.")
    return result


def validate_child_request(payload: dict[str, Any]) -> JsonRpcRequest:
    if payload.get("jsonrpc") != "2.0":
        raise PluginHostProtocolError("plugin_host.request.invalid", "RPC request must use JSON-RPC 2.0.")
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params")
    if not isinstance(request_id, str) or not isinstance(method, str) or not isinstance(params, dict):
        raise PluginHostProtocolError("plugin_host.request.invalid", "RPC request is malformed.")
    if method not in HOST_CALLBACK_METHODS:
        raise PluginHostProtocolError("plugin_host.callback.unsupported", "Host callback method is not allowed.")
    return JsonRpcRequest(request_id, method, params)


__all__ = [
    "HOST_CALLBACK_METHODS",
    "PLUGIN_METHODS",
    "JsonRpcRequest",
    "error_response",
    "make_request",
    "success_response",
    "validate_child_request",
    "validate_response",
]
