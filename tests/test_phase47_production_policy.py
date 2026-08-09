from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from channels.youtube.channel import YouTubeChannelService
from channels.youtube.transport import HttpYouTubeTransport
from publication_calendar_runtime_handlers import register_calendar_runtime_handlers
from publication_git_runtime_handlers import register_git_runtime_handlers
from runtime_foundation_mappings import phase41_runtime_registry
from src.core.runtime import (
    CapabilityHandlerRegistry,
    DeploymentPolicy,
    ExecutionState,
    InstallGrants,
    PlaybookExecutor,
    RuntimePolicyEngine,
)
from tests.test_phase44_calendar_runtime_bridge import (
    calendar_deployment,
    calendar_event,
    calendar_stack,  # noqa: F401
    compile_calendar_plan,
)
from tests.test_phase45_git_runtime_bridge import (
    compile_git_plan,
    git_event,
    init_repo,
    repository_reference,
)
from tests.test_phase46_remote_read_bridge import (
    MockHttpResponse,
    compile_youtube_plan,
    read_video_records,
    youtube_deployment,
    youtube_event,
)
from youtube_runtime_handlers import register_youtube_runtime_handlers


def test_calendar_read_allowed_and_denied_by_policy(calendar_stack) -> None:  # noqa: F811
    registry = phase41_runtime_registry()
    deployment = calendar_deployment()
    handlers = CapabilityHandlerRegistry()
    handler = register_calendar_runtime_handlers(handlers, calendar_service=calendar_stack["calendar_service"])
    executor = PlaybookExecutor(
        handlers,
        policy_engine=RuntimePolicyEngine(registry=registry, deployments={deployment.deployment_id: deployment}),
    )

    with patch.object(handler, "execute", wraps=handler.execute) as execute_spy:
        outcome = executor.execute(plan=compile_calendar_plan(), trigger_event=calendar_event())

    assert outcome.execution.state == ExecutionState.SUCCEEDED.value
    assert execute_spy.call_count == 1

    denied_registry = phase41_runtime_registry()
    denied_registry.register_install(
        replace(denied_registry.installs["calendar-publication-local"], grants=InstallGrants())
    )
    denied_handlers = CapabilityHandlerRegistry()
    denied_handler = register_calendar_runtime_handlers(
        denied_handlers,
        calendar_service=calendar_stack["calendar_service"],
    )
    denied_executor = PlaybookExecutor(
        denied_handlers,
        policy_engine=RuntimePolicyEngine(
            registry=denied_registry,
            deployments={deployment.deployment_id: deployment},
        ),
    )

    with patch.object(denied_handler, "execute", wraps=denied_handler.execute) as execute_spy:
        denied = denied_executor.execute(plan=compile_calendar_plan(), trigger_event=calendar_event())

    assert denied.execution.state == ExecutionState.FAILED.value
    assert execute_spy.call_count == 0


def test_git_subprocess_policy_denies_before_git_command(tmp_path) -> None:
    repo = init_repo(tmp_path)
    registry = phase41_runtime_registry()
    registry.register_install(
        replace(
            registry.installs["github-don-website"],
            install_id="website-local-test",
            workspace_id="workspace-1",
            account_ref="repo-phase45",
            grants=InstallGrants(
                allowed_capabilities=("git.repository.status.read",),
                allow_filesystem=True,
                allow_subprocess=False,
            ),
        )
    )
    deployment = replace(
        __import__("tests.test_phase45_git_runtime_bridge", fromlist=["git_deployment"]).git_deployment(),
        policy=DeploymentPolicy(allow_filesystem=True, allow_subprocess=False),
    )
    handlers = CapabilityHandlerRegistry()
    handler = register_git_runtime_handlers(
        handlers,
        repositories_by_install_id={"website-local-test": repository_reference(repo)},
    )
    executor = PlaybookExecutor(
        handlers,
        policy_engine=RuntimePolicyEngine(registry=registry, deployments={deployment.deployment_id: deployment}),
    )

    with (
        patch.object(handler, "execute", wraps=handler.execute) as execute_spy,
        patch("channels.markdown_website.git_publisher.subprocess.run", side_effect=AssertionError("git forbidden")),
    ):
        outcome = executor.execute(plan=compile_git_plan(), trigger_event=git_event())

    assert outcome.execution.state == ExecutionState.FAILED.value
    assert execute_spy.call_count == 0


def test_youtube_policy_network_secret_and_domain_denials_prevent_http() -> None:
    deployment = replace(
        youtube_deployment(),
        policy=DeploymentPolicy(
            allow_network=True,
            allowed_network_domains=("www.googleapis.com", "oauth2.googleapis.com"),
        ),
    )
    for install_grants, policy, reason in [
        (
            InstallGrants(
                allowed_capabilities=("youtube.video.metadata.read",),
                allow_network=False,
                allowed_secret_refs=("youtube-access-token-ref",),
                allowed_network_domains=("www.googleapis.com", "oauth2.googleapis.com"),
            ),
            deployment.policy,
            "NETWORK_NOT_ALLOWED",
        ),
        (
            InstallGrants(
                allowed_capabilities=("youtube.video.metadata.read",),
                allow_network=True,
                allowed_network_domains=("www.googleapis.com", "oauth2.googleapis.com"),
            ),
            deployment.policy,
            "SECRET_NOT_GRANTED",
        ),
        (
            InstallGrants(
                allowed_capabilities=("youtube.video.metadata.read",),
                allow_network=True,
                allowed_secret_refs=("youtube-access-token-ref",),
                allowed_network_domains=("www.googleapis.com", "oauth2.googleapis.com"),
            ),
            DeploymentPolicy(allow_network=True, allowed_network_domains=("attacker.example",)),
            "DOMAIN_NOT_ALLOWED",
        ),
    ]:
        registry = phase41_runtime_registry()
        registry.register_install(
            replace(
                registry.installs["youtube-don-main-channel"],
                install_id="youtube-remote-test",
                workspace_id="workspace-1",
                secret_refs=("youtube-access-token-ref",),
                grants=install_grants,
            )
        )
        active_deployment = replace(deployment, policy=policy)
        handlers = CapabilityHandlerRegistry()
        register_youtube_runtime_handlers(
            handlers,
            youtube_service=YouTubeChannelService(transport=HttpYouTubeTransport(timeout=1)),
            access_tokens_by_install_id={"youtube-remote-test": "fixture-auth-value"},
        )
        executor = PlaybookExecutor(
            handlers,
            policy_engine=RuntimePolicyEngine(
                registry=registry,
                deployments={active_deployment.deployment_id: active_deployment},
            ),
        )

        with patch("channels.youtube.transport.urllib.request.urlopen", side_effect=AssertionError("http forbidden")):
            outcome = executor.execute(plan=compile_youtube_plan(), trigger_event=youtube_event())

        assert outcome.execution.state == ExecutionState.FAILED.value
        assert read_video_records(executor, outcome.execution.execution_id)[-1].error_code == reason


def test_youtube_allowed_policy_executes_existing_network_read() -> None:
    registry = phase41_runtime_registry()
    registry.register_install(
        replace(
            registry.installs["youtube-don-main-channel"],
            install_id="youtube-remote-test",
            workspace_id="workspace-1",
            secret_refs=("youtube-access-token-ref",),
            grants=InstallGrants(
                allowed_capabilities=("youtube.video.metadata.read",),
                allow_network=True,
                allowed_secret_refs=("youtube-access-token-ref",),
                allowed_network_domains=("www.googleapis.com", "oauth2.googleapis.com"),
            ),
        )
    )
    deployment = replace(
        youtube_deployment(),
        policy=DeploymentPolicy(
            allow_network=True,
            allowed_network_domains=("www.googleapis.com", "oauth2.googleapis.com"),
        ),
    )
    transport = HttpYouTubeTransport(timeout=2)
    handlers = CapabilityHandlerRegistry()
    register_youtube_runtime_handlers(
        handlers,
        youtube_service=YouTubeChannelService(transport=transport),
        access_tokens_by_install_id={"youtube-remote-test": "fixture-auth-value"},
    )
    executor = PlaybookExecutor(
        handlers,
        policy_engine=RuntimePolicyEngine(registry=registry, deployments={deployment.deployment_id: deployment}),
    )
    observed: list[str] = []

    def urlopen(request, *, timeout):  # type: ignore[no-untyped-def]
        observed.append(request.get_method())
        return MockHttpResponse({"items": [{"id": "abc123DEF45", "snippet": {"title": "Allowed read"}}]})

    with patch("channels.youtube.transport.urllib.request.urlopen", side_effect=urlopen):
        outcome = executor.execute(plan=compile_youtube_plan(), trigger_event=youtube_event())

    assert outcome.execution.state == ExecutionState.SUCCEEDED.value
    assert observed == ["GET"]
    trace = (
        __import__("src.core.runtime", fromlist=["trace_execution"])
        .trace_execution(
            executor.ledger,
            outcome.execution.execution_id,
        )
        .to_dict()
    )
    node = next(item for item in trace["nodes"] if item["node_id"] == "read-video" and item["state"] == "succeeded")
    assert node["metadata"]["policy_decision"] == "allow"
    assert "fixture-auth-value" not in str(trace)
