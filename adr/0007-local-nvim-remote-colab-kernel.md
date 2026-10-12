# ADR 0007: Local nvim, Remote Colab Kernel

## Status

Accepted

## Decision

Notebook editing and rendering stay on the local Mac. Only the Jupyter kernel
moves to Colab: nvim talks to it through molten's remote-kernel URL over an
SSH-forwarded port (`colab ssh --proxy-mode` plus `ssh -L`). No remote nvim,
no notebook file sync.

## Consequences

The WezTerm plot pane, plugin patches, autosave, and jupytext flow keep
working unchanged because outputs arrive as kernel messages. Kernel choice
sticks per buffer session; a switch is explicit. Idle runtimes stop after
`EOS_COLAB_IDLE_MINUTES` (default 15) and reconnects re-run cells, since a new
runtime is always a fresh kernel. The `colab` CLI must stay at 0.7.2 or newer.

Host key checking is disabled on the forwarded connection because the
transport is the authenticated `colab ssh --proxy-mode` bridge itself; no TCP
in this path is ever exposed beyond that channel. The Jupyter token is
per-connect, never stored, and the state file holding it is mode 600.
