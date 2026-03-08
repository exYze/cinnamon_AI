from setuptools import setup, find_packages

setup(
    name="nexus-core",
    version="0.1.0",
    description="NexusOS Agent Orchestration Engine",
    author="NexusOS Team",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "pydantic>=2.0",
        "click>=8.1",
        "rich>=13.0",
        "tomli>=2.0",
        "aiohttp>=3.9",
        "aiofiles>=23.0",
        "sqlalchemy>=2.0",
        "aiosqlite>=0.19",
    ],
    entry_points={
        "console_scripts": [
            "nexus-core=nexus_core.orchestrator:main",
        ],
    },
)
