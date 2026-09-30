"""Structure of the four agent files (SPEC Section 9): tools, hooks and contracts."""

import pytest

from tests.agents.helpers import AGENT_NAMES, REPO, hook_command, load_agent, tool_names

KNOWN_FIELDS = {  # verified against https://code.claude.com/docs/en/sub-agents
    "name", "description", "tools", "disallowedTools", "model", "permissionMode", "maxTurns",
    "skills", "mcpServers", "hooks", "memory", "background", "omitClaudeMd", "effort", "isolation",
    "color", "initialPrompt", "experimental",
}  # fmt: skip


@pytest.mark.parametrize("name", AGENT_NAMES)
def test_frontmatter_is_valid(name):
    agent = load_agent(name)
    assert agent["name"] == name
    assert agent["description"]
    assert set(agent) <= KNOWN_FIELDS
    assert "permissionMode" not in agent, "the driver sets the permission mode, not the agent"


@pytest.mark.parametrize("name", ["hypothesis", "data", "report"])
def test_file_writing_agents_have_no_bash(name):
    tools = tool_names(load_agent(name))
    assert not [t for t in tools if t.startswith("Bash")]


def test_skeptic_bash_is_limited_to_tests():
    bash = [t for t in tool_names(load_agent("skeptic")) if t.startswith("Bash")]
    assert bash and all(
        t.startswith(("Bash(uv run pytest", "Bash(uv run lab leakage")) for t in bash
    )


@pytest.mark.parametrize("name", AGENT_NAMES)
def test_every_agent_that_can_write_has_a_path_hook(name):
    agent = load_agent(name)
    tools = tool_names(agent)
    assert not {"NotebookEdit", "MultiEdit"} & set(tools)
    for tool in {"Edit", "Write"} & set(tools):
        assert "path_allow.py" in hook_command(agent, tool)


def test_skeptic_bash_call_goes_through_the_command_hook():
    assert "bash_allow.py" in hook_command(load_agent("skeptic"), "Bash")


def test_only_the_hook_scripts_named_in_agent_files_exist():
    for script in ("path_allow.py", "bash_allow.py"):
        assert (REPO / ".claude" / "hooks" / script).is_file()


@pytest.mark.parametrize("name", AGENT_NAMES)
def test_contract_sections_are_present(name):
    body = (REPO / ".claude" / "agents" / f"{name}.md").read_text()
    for heading in ("## Writes", "## Must", "## Must not"):
        assert heading in body
