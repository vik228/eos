local M = {}

function M.apply(config)
  config.default_prog = { "zsh", "-l" }

  config.launch_menu = {
    { label = "Backend Workspace", args = { "zsh", "-lc", "backend" } },
    { label = "Research Workspace", args = { "zsh", "-lc", "research" } },
    { label = "Paper Workspace", args = { "zsh", "-lc", "paper" } },
    { label = "Algorithmic Coding Workspace", args = { "zsh", "-lc", "algo" } },
    { label = "Writing Workspace", args = { "zsh", "-lc", "write" } },
    { label = "Agents Workspace", args = { "zsh", "-lc", "agents" } },
    { label = "Work Shell", args = { "zsh", "-lc", "cd ~/work && zsh -l" } },
    { label = "Personal Shell", args = { "zsh", "-lc", "cd ~/personal && zsh -l" } },
    { label = "Research Shell", args = { "zsh", "-lc", "cd ~/research && zsh -l" } },
    { label = "Claude Work", args = { "zsh", "-lc", "claude-work; exec zsh -l" } },
    { label = "Claude Personal", args = { "zsh", "-lc", "claude-personal; exec zsh -l" } },
    { label = "Codex Work", args = { "zsh", "-lc", "codex-work; exec zsh -l" } },
    { label = "Codex Personal", args = { "zsh", "-lc", "codex-personal; exec zsh -l" } },
  }
end

return M
