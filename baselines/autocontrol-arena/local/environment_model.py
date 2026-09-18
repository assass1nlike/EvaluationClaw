"""Select the model used by environment tools independently of the target."""

from dataclasses import asdict

from configs.config_manager import ConfigManager
from src.infra.llm.client_factory import get_openai_client
from src.infra.target_agent.base import BaseAgent
from src.orchestration.services.simulation_service import SimulationService


def configure_environment_model(profile):
    config = asdict(ConfigManager().load_llm_profile(profile))

    def build_caller(target_agent):
        environment_agent = BaseAgent(
            client=get_openai_client(config),
            model_name=config['model_name'],
            api_type=config['api_type'],
            provider=config['provider'],
            provider_fallback=config['provider_fallback'],
            default_temperature=config['temperature'],
            default_max_tokens=config['max_tokens'],
        )
        return environment_agent.call_llm_text

    SimulationService._build_llm_caller = staticmethod(build_caller)
