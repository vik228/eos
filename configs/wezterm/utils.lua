local M = {}

function M.home()
  return os.getenv("HOME")
end

function M.eos_root()
  return os.getenv("EOS_ROOT") or (M.home() .. "/personal/eos")
end

return M
