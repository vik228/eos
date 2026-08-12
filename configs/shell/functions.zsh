wrk() { cd "$HOME/work"; }
per() { cd "$HOME/personal"; }
res() { cd "$HOME/research"; }
tools() { cd "$HOME/tools"; }

backend() {
  "$HOME/personal/eos/scripts/backend" "$@"
}

agents() {
  "$HOME/personal/eos/scripts/agents" "$@"
}

research() {
  "$HOME/personal/eos/scripts/research" "$@"
}

paper() {
  "$HOME/personal/eos/scripts/paper" "$@"
}

algo() {
  "$HOME/personal/eos/scripts/algo" "$@"
}

leetcode() {
  "$HOME/personal/eos/scripts/algo" "$@"
}

write() {
  "$HOME/personal/eos/scripts/write" "$@"
}
