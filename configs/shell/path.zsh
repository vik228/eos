path=(
  "$HOME/personal/eos/scripts"
  "$HOME/personal/eos/bin"
  "$HOME/.local/bin"
  "/opt/homebrew/bin"
  "/opt/homebrew/sbin"
  $path
)

typeset -U path
export PATH
