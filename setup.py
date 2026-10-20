from setuptools import find_packages, setup

setup(
    name="background-agent-orchestration",
    version="0.1.0",
    description="Protocol and runtime toolkit for orchestrating autonomous background agents with FSM lifecycle tracking, milestone filtering, HITL steering, and SHA-256 artifact synthesis.",
    author="NoJuanNobody",
    packages=find_packages(exclude=["tests", "tests.*"]),
    python_requires=">=3.9",
    entry_points={
        "console_scripts": [
            "bg-orchestrator = background_agent_orchestration.cli:main",
        ],
    },
)
