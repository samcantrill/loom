"""Native outbound submit service around a test coordinator and fake scheduler."""

from dataclasses import replace
from pathlib import Path
from threading import Event, Thread

from loom.queue import LocalDaemon
from loom.queue.agent_sessions import AgentPolicyConfig, AgentPrincipalPolicy, SLURM_SUBMISSION_CAPABILITY, SLURM_PENDING_EFFECTS_CAPABILITY
from loom.queue.agent_session_transport import AgentTlsClientConfig, AgentTlsServerConfig, LocalDaemonAgentHttpClient, LocalDaemonAgentHttpServer
from loom.queue.deployment import OutboundAgentRegistrationConfig, OutboundAgentServiceConfig, run_outbound_agent_service
from loom.queue.shared_execution import STAGING_CONTINUATION_CAPABILITY
from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint


class OutboundSlurmCoordinator:
    """Retain coordinator/agent roots through explicit paired restarts."""

    capabilities = (SLURM_SUBMISSION_CAPABILITY, SLURM_PENDING_EFFECTS_CAPABILITY, STAGING_CONTINUATION_CAPABILITY)

    @classmethod
    def configure(cls, config):
        profile = config.slurm_profiles[0]
        return replace(config, agent_root=None, resident_worker_launch_profile=None,
                       cpu_capacity=0, memory_capacity_bytes=0, gpu_devices=(), agent_resource_providers=None,
                       container_capabilities=(), agent_policy=AgentPolicyConfig(agents=(
            AgentPrincipalPolicy('submit-credential', 'submit-principal', 'submit-agent',
                                 ('default',), cls.capabilities,
                                 external_slurm_profiles=((profile.profile_id, profile.configuration_fingerprint),)),
        )))

    def __init__(self, config, root: Path):
        self.daemon = LocalDaemon(config)
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.server = None
        self.thread = None
        self.stop_event = Event()
        self.failures = []

    def __getattr__(self, name):
        return getattr(self.daemon, name)

    def start(self):
        self.daemon.start()
        tls = self.root / 'tls'
        credentials = (mutual_tls_credentials(tls) if not tls.exists() else
                       {name: tls / name for name in ('ca', 'server', 'agent')})
        self.server = LocalDaemonAgentHttpServer(self.daemon, AgentTlsServerConfig(
            'localhost', int((self.root / 'port').read_text()) if (self.root / 'port').exists() else 0, credentials['server'].with_suffix('.crt'),
            credentials['server'].with_suffix('.key'), credentials['ca'].with_suffix('.crt'),
            {certificate_fingerprint(credentials['agent'].with_suffix('.crt')): 'submit-credential'},
        ))
        self.server.start()
        (self.root / 'port').write_text(str(self.server.port))
        config = AgentTlsClientConfig(
            url=f'https://localhost:{self.server.port}',
            server_ca_path=credentials['ca'].with_suffix('.crt'),
            certificate_path=credentials['agent'].with_suffix('.crt'),
            private_key_path=credentials['agent'].with_suffix('.key'),
            agent_root=self.root / 'agent', slurm_profiles=self.daemon.config.slurm_profiles,
        )
        assert config.agent_root is not None
        if not (config.agent_root / 'control.sqlite').exists():
            LocalDaemonAgentHttpClient.initialize_agent_root(config)
        service = OutboundAgentServiceConfig(
            config, OutboundAgentRegistrationConfig('config', 'inventory', 'availability', ('default',), self.capabilities),
            0.01, self.root / 'agent.yaml', '0' * 64, '1' * 64,
        )
        self.stop_event.clear()
        def run():
            try:
                run_outbound_agent_service(service, stop=self.stop_event)
            except BaseException as error:
                self.failures.append(error)
        self.thread = Thread(target=run)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(15)
            assert not self.thread.is_alive(), 'outbound service failed to stop'
        if self.server is not None:
            self.server.stop()
        self.daemon.stop()
        assert not self.failures, self.failures
